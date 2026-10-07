package com.eis.gatandroid

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Cœur de la gateway :
 *  - présence : un message OBS par bague surveillée toutes les 5 s (scan passif, sans GATT) ;
 *  - mesure : sur GATT_CMD visant cette gateway, une seule session GATT (HR + batterie),
 *    pendant laquelle la présence est suspendue ; puis la présence reprend.
 */
object Gateway {
    private const val OBS_PERIOD_MS = 5_000L
    private const val VERSION = 5

    private var scope: CoroutineScope? = null
    private var jobs = mutableListOf<Job>()
    private val busy = AtomicBoolean(false)
    @Volatile private var paused = false
    private var seq = 0

    fun start(ctx: Context) {
        if (scope != null) return
        val sc = CoroutineScope(SupervisorJob() + Dispatchers.Main)
        scope = sc
        GatState.running.value = true
        GatState.log("Gateway ${Prefs.gateway} démarrée (zone : ${Prefs.zone.ifBlank { "—" }})")

        Udp.start(ctx) { cmd -> sc.launch { onCommand(cmd) } }
        PassiveScanner.start()

        // Présence périodique
        jobs += sc.launch {
            while (isActive) {
                delay(OBS_PERIOD_MS)
                if (paused) continue
                if (!PassiveScanner.isActive) PassiveScanner.start()
                sendObservations(PassiveScanner.drainWindow())
            }
        }
        // Mise à jour de l'écran
        jobs += sc.launch {
            while (isActive) {
                GatState.seen.value = PassiveScanner.snapshot()
                delay(1000)
            }
        }
    }

    fun stop() {
        val sc = scope ?: return
        scope = null
        sc.cancel()
        jobs.clear()
        PassiveScanner.stop()
        RingLink.disconnect()
        Udp.stop()
        busy.set(false)
        paused = false
        GatState.running.value = false
        GatState.log("Gateway arrêtée")
    }

    // ------------------------------------------------------------------ présence

    private fun sendObservations(rssiByRing: Map<String, Int>) {
        for (mac in Prefs.rings) {
            val rssi = rssiByRing[mac]
            val o = JSONObject()
                .put("type", "OBS")
                .put("version", VERSION)
                .put("gw", Prefs.gateway)
                .put("zone", Prefs.zone)
                .put("ring", mac)
                .put("reachable", rssi != null)
                .put("rssi", rssi ?: JSONObject.NULL)
                .put("reach_status", if (rssi != null) "REACHABLE" else "NOT_AVAILABLE")
                .put("seq", ++seq)
                .put("scan_s", OBS_PERIOD_MS / 1000.0)
                .put("ts", nowIso())
            Udp.send(Udp.OBS_GROUP, Udp.OBS_PORT, o)
            GatState.obsSent.value = GatState.obsSent.value + 1
        }
        GatState.lastScanOrder.value = hhmmss()
    }

    // ------------------------------------------------------------------ mesure à la demande

    private suspend fun onCommand(o: JSONObject) {
        if (o.optString("type") != "GATT_CMD") return
        if (o.optString("target").trim() != Prefs.gateway) return // pas pour nous
        val req = o.optString("req")
        val cmd = o.optString("cmd").trim().lowercase()
        val mac = resolveRing(o.optString("ring"))

        if (cmd != "hr") {
            result(req, o.optString("ring"), cmd, "ERROR", "ERROR", "UNSUPPORTED_CMD")
            return
        }
        if (mac == null) {
            result(req, o.optString("ring"), cmd, "ERROR", "ERROR", "RING_NOT_MONITORED")
            return
        }
        if (!busy.compareAndSet(false, true)) {
            status(req, mac, cmd, "BUSY")
            return
        }
        try {
            withTimeout(150_000) { runHr(req, mac) }
        } catch (e: Exception) {
            result(req, mac, "hr", "ERROR", "ERROR", "EXCEPTION:${e.javaClass.simpleName}")
        } finally {
            RingLink.disconnect()
            paused = false
            if (scope != null) PassiveScanner.start()
            busy.set(false)
        }
    }

    private suspend fun runHr(req: String, mac: String) {
        GatState.log("Mesure HR demandée ($req) pour $mac")
        paused = true
        PassiveScanner.stop()
        status(req, mac, "hr", "ACCEPTED")

        status(req, mac, "hr", "CONNECTING")
        if (!RingLink.connect(mac)) {
            result(req, mac, "hr", "OUT_OF_RANGE", "OUT_OF_RANGE", "CONNECT_FAILED")
            return
        }
        status(req, mac, "hr", "CONNECTED")

        val batt = RingLink.readBattery()
        val battery = batt?.batteryValue
        val charging = batt?.isCharging
        val battAt = if (batt != null) nowIso() else null

        status(req, mac, "hr", "MEASURING", battery = battery, charging = charging)
        val hr = RingLink.measureHr { live ->
            status(req, mac, "hr", "MEASURING", value = live, battery = battery, charging = charging)
        }
        when (hr) {
            is RingLink.Hr.Ok -> result(
                req, mac, "hr", "SUCCESS", "SUCCESS", null,
                value = hr.bpm, battery = battery, charging = charging, battAt = battAt, hrAt = nowIso()
            )
            is RingLink.Hr.Fail -> when (hr.code) {
                "ring_removed", "timeout", "invalid_value" -> result(
                    req, mac, "hr", "CONNECTED_NOT_WORN", "CONNECTED_NOT_WORN", hr.code,
                    battery = battery, charging = charging, battAt = battAt
                )
                else -> result(
                    req, mac, "hr", "ERROR", "ERROR", hr.code,
                    battery = battery, charging = charging, battAt = battAt
                )
            }
        }
    }

    /** "ring" de la commande → MAC surveillée (par MAC ou par nom de bague vu au scan). */
    private fun resolveRing(ring: String): String? {
        val n = normMac(ring)
        val monitored = Prefs.rings
        if (monitored.contains(n)) return n
        return monitored.firstOrNull { PassiveScanner.nameOf(it).equals(ring.trim(), ignoreCase = true) }
    }

    // ------------------------------------------------------------------ messages de mesure

    private fun status(
        req: String, ring: String, cmd: String, status: String,
        value: Int? = null, battery: Int? = null, charging: Boolean? = null
    ) {
        val o = JSONObject()
            .put("type", "GATT_STATUS").put("version", VERSION)
            .put("req", req).put("gateway", Prefs.gateway).put("ring", ring).put("cmd", cmd)
            .put("status", status).put("value", value ?: JSONObject.NULL)
            .put("battery", battery ?: JSONObject.NULL).put("charging", charging ?: JSONObject.NULL)
            .put("ts", nowIso())
        Udp.send(Udp.RES_GROUP, Udp.RES_PORT, o)
        GatState.gatt.value = GatState.gatt.value.copy(
            state = status, req = req, ring = ring, value = value ?: GatState.gatt.value.value,
            battery = battery ?: GatState.gatt.value.battery,
            charging = charging ?: GatState.gatt.value.charging,
            detail = "", atMs = System.currentTimeMillis()
        )
    }

    private fun result(
        req: String, ring: String, cmd: String, status: String, functional: String, reason: String?,
        value: Int? = null, battery: Int? = null, charging: Boolean? = null,
        battAt: String? = null, hrAt: String? = null
    ) {
        val now = nowIso()
        val o = JSONObject()
            .put("type", "GATT_RESULT").put("version", VERSION)
            .put("req", req).put("gateway", Prefs.gateway).put("ring", ring).put("cmd", cmd)
            .put("status", status).put("functional_state", functional)
            .put("reason", reason ?: JSONObject.NULL)
            .put("value", value ?: JSONObject.NULL)
            .put("battery", battery ?: JSONObject.NULL).put("charging", charging ?: JSONObject.NULL)
            .put("battery_measured_at", battAt ?: JSONObject.NULL)
            .put("hr_measured_at", hrAt ?: JSONObject.NULL)
            .put("completed_at", now).put("ts", now)
        Udp.send(Udp.RES_GROUP, Udp.RES_PORT, o)
        GatState.gatt.value = GattInfo(
            state = functional, req = req, ring = ring, value = value, battery = battery,
            charging = charging, detail = reason ?: "", atMs = System.currentTimeMillis()
        )
        GatState.log("Résultat $req : $functional${value?.let { " · $it bpm" } ?: ""}${reason?.let { " ($it)" } ?: ""}")
    }
}
