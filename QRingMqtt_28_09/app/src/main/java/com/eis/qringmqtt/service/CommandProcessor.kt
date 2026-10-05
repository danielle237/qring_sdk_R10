package com.eis.qringmqtt.service

import android.util.Log
import com.eis.qringmqtt.BuildConfig
import com.eis.qringmqtt.ble.Measurer
import com.eis.qringmqtt.ble.RingManager
import com.eis.qringmqtt.ble.Syncer
import com.eis.qringmqtt.data.ActiveMeasure
import com.eis.qringmqtt.data.AppState
import com.eis.qringmqtt.data.Cmd
import com.eis.qringmqtt.data.Command
import com.eis.qringmqtt.data.Err
import com.eis.qringmqtt.data.LogEntry
import com.eis.qringmqtt.data.Reading
import com.eis.qringmqtt.data.RingConn
import com.eis.qringmqtt.data.Source
import com.eis.qringmqtt.data.I18n
import com.eis.qringmqtt.data.Lang
import com.eis.qringmqtt.data.MeasureResult
import com.eis.qringmqtt.mqtt.MqttManager
import com.eis.qringmqtt.mqtt.NetInfo
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * File des commandes (MQTT ou boutons de l'interface).
 * La bague ne sait faire qu'une chose à la fois : les commandes sont exécutées l'une après l'autre.
 * ping / cancel / info répondent immédiatement.
 */
object CommandProcessor {

    private const val TAG = "CommandProcessor"
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val channel = Channel<Command>(Channel.UNLIMITED)
    private var worker: Job? = null
    private var currentJob: Job? = null

    /** Défini par le service quand la connexion MQTT existe. */
    var mqtt: MqttManager? = null

    fun start() {
        if (worker != null) return
        worker = scope.launch {
            for (c in channel) {
                AppState.queued.update { list -> list.toMutableList().also { it.remove(c.cmd) } }
                val job = launch { execute(c) }
                currentJob = job
                job.join()
                currentJob = null
            }
        }
    }

    // ------------------------------------------------------------------ entrée

    /**
     * Payload reçu sur {base}/cmd ou gateway/{nom}/cmd :
     * JSON {"cmd":"spo2","reqId":"a7","day":0}, {"cmd":"bind","mac":"C4:A1:…"}, {"cmd":"lang","value":"ar"}
     * ou simple texte "spo2".
     */
    fun onMqttPayload(payload: String, viaGateway: Boolean = false) {
        val text = payload.trim()
        var key: String? = null
        var reqId: String? = null
        var day = 0
        var arg: String? = null
        try {
            if (text.startsWith("{")) {
                val o = JSONObject(text)
                key = o.optString("cmd", o.optString("type", ""))
                reqId = o.optString("reqId").ifBlank { null }
                day = o.optInt("day", 0).coerceIn(0, 6)
                arg = listOf("mac", "value", "lang").map { o.optString(it) }.firstOrNull { it.isNotBlank() }
            } else {
                // "lang ar" ou "bind C4:A1:…" acceptés aussi en texte
                val parts = text.trim('"').split(' ', limit = 2)
                key = parts[0]
                arg = parts.getOrNull(1)?.trim()
            }
        } catch (e: Exception) {
            key = null
        }
        val cmd = Cmd.from(key)
        if (cmd == null) {
            publishError("cmd", Command(Cmd.PING, reqId, Source.MQTT, viaGateway = viaGateway), Err.UNKNOWN_COMMAND, extra = key)
            return
        }
        submit(Command(cmd, reqId, Source.MQTT, day, arg, viaGateway || cmd.gateway))
    }

    /** Point d'entrée commun (MQTT et interface). */
    fun submit(c: Command) {
        start()
        when (c.cmd) {
            Cmd.PING -> { mqtt?.publishStatusNow(true); return }
            Cmd.CANCEL -> { cancelCurrent(); return }
            Cmd.INFO -> { publishInfo(c); return }
            Cmd.LANG -> { setLang(c); return }
            Cmd.UNBIND -> { unbind(c); return }
            Cmd.BIND -> { bind(c); return }
            Cmd.SCAN -> { scan(c); return }
            else -> {}
        }
        // Bague déconnectée → erreur immédiate
        if (AppState.ring.value != RingConn.CONNECTED) {
            publishError(c.cmd.key, c, Err.RING_DISCONNECTED)
            if (c.cmd.measure) AppState.showError(c.cmd.key, Err.RING_DISCONNECTED)
            return
        }
        // Fonction non supportée par ce modèle
        val info = AppState.info.value
        if (c.cmd.measure && info.supportsKnown && c.cmd.key !in info.supports) {
            publishError(c.cmd.key, c, Err.NOT_SUPPORTED)
            AppState.showError(c.cmd.key, Err.NOT_SUPPORTED)
            return
        }
        // Déjà en cours ou en attente : on ignore le doublon venant de l'interface
        if (c.source == Source.MANUAL &&
            (AppState.active.value?.cmd == c.cmd || c.cmd in AppState.queued.value)
        ) return

        AppState.queued.update { it + c.cmd }
        channel.trySend(c)
    }

    fun cancelCurrent() {
        Measurer.cancel()
        currentJob?.cancel()
    }

    // ------------------------------------------------------------------ commandes du gateway

    private fun setLang(c: Command) {
        val l = Lang.from(c.arg)
        if (l == null) { publishError("lang", c, Err.BAD_REQUEST, extra = c.arg); return }
        AppState.setLang(l)
        mqtt?.publish("lang", base(c).put("status", "ok").put("lang", l.code), LogEntry.Kind.OUT, viaGateway = true)
        mqtt?.publishStatusNow(true)
    }

    /** Dissociation (bouton Réglages ou MQTT). L'historique est conservé. */
    fun unbind(c: Command) {
        val old = AppState.info.value
        if (AppState.active.value != null) cancelCurrent()
        RingManager.unbind()
        val o = base(c).put("status", "ok").put("ringMac", old.mac).put("ringModel", old.model)
        mqtt?.publish("unbind", o, LogEntry.Kind.OUT, viaGateway = true)
    }

    /** Association à distance : {"cmd":"bind","mac":"C4:A1:5F:22:A4:F1"} */
    private fun bind(c: Command) {
        val mac = c.arg
        if (mac.isNullOrBlank() || mac.count { it.isLetterOrDigit() } != 12) {
            publishError("bind", c, Err.BAD_REQUEST, extra = mac); return
        }
        if (AppState.active.value != null) { publishError("bind", c, Err.BUSY); return }
        mqtt?.publish("bind", base(c).put("status", "searching").put("mac", RingManager.normalizeMac(mac)),
            LogEntry.Kind.MEASURING, viaGateway = true)
        RingManager.bindRemote(mac) { err ->
            if (err != null) publishError("bind", c, err, extra = mac)
            else {
                val i = AppState.info.value
                mqtt?.publish("bind", base(c).put("status", "ok").put("ringMac", i.mac)
                    .put("ringModel", i.model).put("ringName", i.name), LogEntry.Kind.OUT, viaGateway = true)
            }
        }
    }

    /** Liste des bagues à proximité : {"cmd":"scan"} → gateway/{nom}/scan */
    private fun scan(c: Command) {
        if (!RingManager.isBluetoothOn()) { publishError("scan", c, Err.BLUETOOTH_OFF); return }
        RingManager.startScan()
        scope.launch {
            kotlinx.coroutines.delay(13_000)
            RingManager.stopScan()
            val arr = org.json.JSONArray()
            AppState.scanResults.value.forEach {
                arr.put(JSONObject().put("name", it.name).put("mac", it.mac).put("rssi", it.rssi))
            }
            mqtt?.publish("scan", base(c).put("status", "ok").put("count", arr.length()).put("rings", arr),
                LogEntry.Kind.OUT, viaGateway = true)
        }
    }

    // ------------------------------------------------------------------ exécution

    private suspend fun execute(c: Command) {
        if (AppState.ring.value != RingConn.CONNECTED) {
            publishError(c.cmd.key, c, Err.RING_DISCONNECTED)
            if (c.cmd.measure) AppState.showError(c.cmd.key, Err.RING_DISCONNECTED)
            return
        }
        try {
            if (c.cmd.measure) runMeasure(c) else runSync(c)
        } catch (e: kotlinx.coroutines.CancellationException) {
            if (c.cmd.measure) {
                publishError(c.cmd.key, c, Err.CANCELLED)
                AppState.active.value = null
            }
            throw e
        } catch (e: Exception) {
            Log.e(TAG, "execute ${c.cmd}", e)
            publishError(c.cmd.key, c, Err.MEASURE_FAILED)
        }
    }

    private suspend fun runMeasure(c: Command) {
        AppState.clearError(c.cmd.key)
        AppState.active.value = ActiveMeasure(c.cmd, c.source, System.currentTimeMillis())
        mqtt?.publish(c.cmd.key, base(c).put("status", "measuring"), LogEntry.Kind.MEASURING)

        val outcome = Measurer.measure(c.cmd) { live ->
            AppState.active.update { it?.copy(liveText = live) }
        }
        AppState.active.value = null

        // Si la bague s'est déconnectée pendant la mesure
        val result = if (outcome is Measurer.Outcome.Fail && AppState.ring.value != RingConn.CONNECTED)
            Measurer.Outcome.Fail(Err.RING_DISCONNECTED) else outcome

        when (result) {
            is Measurer.Outcome.Ok -> {
                setWorn(true)
                AppState.lastResult.value = MeasureResult(c.cmd, true, result.values, null, System.currentTimeMillis())
                val ts = nowSec()
                if (c.cmd == Cmd.ALL) {
                    // On range aussi chaque valeur dans sa carte
                    splitAll(result.values, ts, c.source)
                    AppState.addReading(Reading("all", result.values, ts, c.source))
                } else {
                    AppState.addReading(Reading(c.cmd.key, result.values, ts, c.source))
                }
                mqtt?.publish(c.cmd.key, base(c).put("status", "ok").merge(result.values), LogEntry.Kind.OUT)
            }
            is Measurer.Outcome.Fail -> {
                if (result.code == Err.RING_REMOVED) setWorn(false)
                if (result.code != Err.CANCELLED)
                    AppState.lastResult.value = MeasureResult(c.cmd, false, null, result.code, System.currentTimeMillis())
                publishError(c.cmd.key, c, result.code)
                AppState.showError(c.cmd.key, result.code)
            }
        }
    }

    /** Bague portée / retirée : mis à jour après chaque mesure, statut republié si ça change. */
    private fun setWorn(w: Boolean) {
        if (AppState.worn.value == w) return
        AppState.worn.value = w
        mqtt?.publishStatusNow(true)
    }

    private fun splitAll(v: JSONObject, ts: Long, src: Source) {
        if (v.has("hr")) AppState.addReading(Reading("hr", JSONObject().put("value", v.getInt("hr")).put("unit", "bpm")
            .apply { if (v.has("rri")) put("rri", v.getInt("rri")) }, ts, src))
        if (v.has("spo2")) AppState.addReading(Reading("spo2", JSONObject().put("value", v.getInt("spo2")).put("unit", "%"), ts, src))
        if (v.has("temp")) AppState.addReading(Reading("temp", JSONObject().put("value", v.getDouble("temp")).put("unit", "°C"), ts, src))
        if (v.has("sbp")) AppState.addReading(Reading("bp", JSONObject().put("sbp", v.getInt("sbp")).put("dbp", v.getInt("dbp")).put("unit", "mmHg"), ts, src))
        if (v.has("hrv")) AppState.addReading(Reading("hrv", JSONObject().put("value", v.getInt("hrv")).put("unit", "ms"), ts, src))
        if (v.has("stress")) AppState.addReading(Reading("stress", JSONObject().put("value", v.getInt("stress")).put("unit", "score"), ts, src))
    }

    private suspend fun runSync(c: Command) {
        AppState.syncing.value = c.cmd
        val data: JSONObject? = try { fetch(c) } finally { AppState.syncing.value = null }
        if (data == null) {
            publishError(c.cmd.key, c, if (AppState.ring.value != RingConn.CONNECTED) Err.RING_DISCONNECTED else Err.NO_DATA)
            AppState.showError(c.cmd.key, Err.NO_DATA)
            return
        }
        // Les données du jour sont gardées pour l'écran Activité
        if (c.cmd != Cmd.HISTORY && (c.day == 0 || c.cmd == Cmd.WORKOUTS || c.cmd == Cmd.SLEEP)) {
            AppState.addReading(Reading(c.cmd.key, data, nowSec(), c.source))
        }
        if (c.cmd == Cmd.HISTORY) importHistory(data)
        mqtt?.publish(c.cmd.key, base(c).put("status", "ok").merge(data), LogEntry.Kind.OUT)
    }

    private suspend fun fetch(c: Command): JSONObject? {
        return when (c.cmd) {
            Cmd.BATTERY -> RingManager.readBattery()?.let {
                JSONObject().put("value", it.batteryValue).put("charging", it.isCharging).put("unit", "%")
            }
            Cmd.STEPS -> Syncer.steps(c.day)
            Cmd.SLEEP -> Syncer.sleep(c.day)
            Cmd.SEDENTARY -> Syncer.sedentary(c.day)
            Cmd.WORKOUTS -> Syncer.workouts()
            Cmd.HISTORY -> Syncer.history(c.day)
            else -> null
        }
    }

    /** Ajoute les mesures automatiques de la bague à l'historique local (pour les courbes). */
    private fun importHistory(h: JSONObject) {
        val day = h.optInt("day", 0)
        val cal = java.util.Calendar.getInstance().apply {
            add(java.util.Calendar.DAY_OF_YEAR, -day)
            set(java.util.Calendar.HOUR_OF_DAY, 0); set(java.util.Calendar.MINUTE, 0)
            set(java.util.Calendar.SECOND, 0); set(java.util.Calendar.MILLISECOND, 0)
        }
        val midnight = cal.timeInMillis / 1000
        val existing = AppState.readings.value.filter { it.source == Source.AUTO }.map { it.type to it.ts }.toHashSet()
        val now = nowSec()
        for (type in listOf("hr", "stress", "hrv", "spo2", "temp")) {
            val arr = h.optJSONArray(type) ?: continue
            for (i in 0 until arr.length()) {
                val p = arr.getJSONObject(i)
                val ts = midnight + p.optInt("minute") * 60L
                if (ts > now || (type to ts) in existing) continue
                val v = JSONObject().put("value", if (type == "temp") p.optDouble("value") else p.optInt("value").toDouble())
                AppState.addReading(Reading(type, v, ts, Source.AUTO))
            }
        }
    }

    private fun publishInfo(c: Command) {
        val i = AppState.info.value
        val o = base(c).put("status", "ok")
            .put("ring", AppState.ring.value.json)
            .put("ringName", i.name)
            .put("firmware", i.firmware)
            .put("hardware", i.hardware)
            .put("battery", i.battery ?: JSONObject.NULL)
            .put("charging", i.charging)
            .put("supports", org.json.JSONArray(i.supports.sorted()))
        mqtt?.publish("info", o, LogEntry.Kind.OUT)
    }

    // ------------------------------------------------------------------ JSON

    /** Champs communs à tous les messages. */
    fun base(c: Command): JSONObject {
        val i = AppState.info.value
        return JSONObject().apply {
            if (c.reqId != null) put("reqId", c.reqId)
            put("type", c.cmd.key)
            put("source", c.source.json)
            put("ringMac", i.mac)
            put("ringModel", i.model)
            put("gateway", AppState.prefs.gatewayName)
            put("ts", nowSec())
        }
    }

    private fun publishError(sub: String, c: Command, code: String, extra: String? = null) {
        val o = base(c).put("status", "error").put("error", code)
        if (extra != null) o.put("received", extra)
        mqtt?.publish(sub, o, LogEntry.Kind.ERROR, viaGateway = c.viaGateway && c.cmd.gateway)
    }

    /** Message de statut (chaque minute + Last Will). */
    fun statusPayload(online: Boolean): JSONObject {
        val i = AppState.info.value
        return JSONObject().apply {
            put("online", online)
            put("ring", if (online) AppState.ring.value.json else "unknown")
            put("ringMac", i.mac)
            put("ringModel", i.model)
            put("ringName", i.name)
            put("firmware", i.firmware)
            put("battery", i.battery ?: JSONObject.NULL)
            put("charging", i.charging)
            put("worn", AppState.worn.value ?: JSONObject.NULL)
            put("measuring", AppState.active.value?.cmd?.key ?: JSONObject.NULL)
            put("gateway", AppState.prefs.gatewayName)
            put("deviceName", NetInfo.deviceName(AppState.appContext))
            put("lanIp", NetInfo.lanIp(AppState.appContext) ?: JSONObject.NULL)
            put("wanIp", NetInfo.wanIp ?: JSONObject.NULL)
            put("lang", I18n.lang.code)
            put("appVersion", BuildConfig.VERSION_NAME)
            put("ts", nowSec())
        }
    }

    private fun JSONObject.merge(other: JSONObject): JSONObject {
        val it = other.keys()
        while (it.hasNext()) {
            val k = it.next()
            put(k, other.get(k))
        }
        return this
    }

    private fun nowSec() = System.currentTimeMillis() / 1000
}
