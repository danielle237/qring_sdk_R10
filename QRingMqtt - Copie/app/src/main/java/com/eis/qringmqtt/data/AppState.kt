package com.eis.qringmqtt.data

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import org.json.JSONArray
import java.io.File

/**
 * État partagé entre le service (tâche de fond) et l'interface.
 * Le service écrit, l'interface observe.
 */
object AppState {

    lateinit var prefs: Prefs
        private set
    lateinit var appContext: Context
        private set
    private lateinit var historyFile: File

    val ring = MutableStateFlow(RingConn.NO_RING)
    val broker = MutableStateFlow(BrokerConn.OFFLINE)
    val info = MutableStateFlow(RingInfo())
    val reconnectInSec = MutableStateFlow<Int?>(null)
    /** Bague portée au doigt ? null = inconnu, false = retirée (mesure sans signal). */
    val worn = MutableStateFlow<Boolean?>(null)
    /** Dernier résultat de mesure (affiché en grand sur TV). */
    val lastResult = MutableStateFlow<MeasureResult?>(null)

    val active = MutableStateFlow<ActiveMeasure?>(null)
    /** Synchronisation en cours (pas, sommeil…) */
    val syncing = MutableStateFlow<Cmd?>(null)
    val queued = MutableStateFlow<List<Cmd>>(emptyList())
    val errors = MutableStateFlow<Map<String, CardError>>(emptyMap())

    /** Historique local (30 jours) : sert aux cartes (dernière valeur) et aux courbes. */
    val readings = MutableStateFlow<List<Reading>>(emptyList())

    val log = MutableStateFlow<List<LogEntry>>(emptyList())
    val pendingPublish = MutableStateFlow(0)

    val scanning = MutableStateFlow(false)
    val scanResults = MutableStateFlow<List<ScannedRing>>(emptyList())

    fun init(context: Context) {
        if (::prefs.isInitialized) return
        appContext = context.applicationContext
        prefs = Prefs(appContext)
        I18n.lang = Lang.from(prefs.lang) ?: Lang.FR
        historyFile = File(context.filesDir, "history.json")
        loadHistory()
        val mac = prefs.ringMac
        // Anciennes mesures sans MAC → rattachées à la bague actuelle
        if (mac != null && readings.value.any { it.ringMac.isBlank() }) {
            readings.value = readings.value.map { if (it.ringMac.isBlank()) it.copy(ringMac = mac) else it }
            saveHistory()
        }
        if (mac != null) {
            info.value = RingInfo(
                mac = mac,
                name = prefs.ringName ?: "",
                model = modelFromName(prefs.ringName),
                firmware = prefs.firmware ?: "",
                hardware = prefs.hardware ?: ""
            )
            ring.value = RingConn.DISCONNECTED
        }
    }

    // ------------------------------------------------------------------ historique

    /** Change la langue (Réglages ou MQTT) et la garde en mémoire. */
    fun setLang(l: Lang) {
        I18n.lang = l
        prefs.lang = l.code
    }

    fun addReading(r0: Reading) {
        val r = if (r0.ringMac.isBlank()) r0.copy(ringMac = prefs.ringMac ?: "") else r0
        readings.update { list ->
            val minTs = r.ts - 30L * 24 * 3600
            (list + r).filter { it.ts >= minTs }.takeLast(MAX_READINGS)
        }
        saveHistory()
    }

    fun latest(type: String): Reading? {
        val mac = prefs.ringMac ?: return null
        return readings.value.lastOrNull { it.type == type && it.ringMac == mac }
    }

    private fun loadHistory() {
        try {
            if (!historyFile.exists()) return
            val arr = JSONArray(historyFile.readText())
            val out = ArrayList<Reading>(arr.length())
            for (i in 0 until arr.length()) out += Reading.fromJson(arr.getJSONObject(i))
            readings.value = out
        } catch (_: Exception) {
        }
    }

    private fun saveHistory() {
        try {
            val arr = JSONArray()
            readings.value.forEach { arr.put(it.toJson()) }
            historyFile.writeText(arr.toString())
        } catch (_: Exception) {
        }
    }

    // ------------------------------------------------------------------ journal

    fun log(kind: LogEntry.Kind, topic: String, payload: String) {
        log.update { (listOf(LogEntry(System.currentTimeMillis(), kind, topic, payload)) + it).take(300) }
    }

    fun clearLog() {
        log.value = emptyList()
    }

    // ------------------------------------------------------------------ erreurs de carte

    fun showError(type: String, code: String) {
        errors.update { it + (type to CardError(code, System.currentTimeMillis() + 8000)) }
    }

    fun clearError(type: String) {
        errors.update { it - type }
    }

    /** Déduit le modèle (R02, R06, R10…) du nom Bluetooth, ex. "R06_A4F1" → "R06". */
    fun modelFromName(name: String?): String {
        if (name.isNullOrBlank()) return ""
        return name.split('_', ' ', '-').firstOrNull()?.uppercase() ?: name
    }

    private const val MAX_READINGS = 6000
}
