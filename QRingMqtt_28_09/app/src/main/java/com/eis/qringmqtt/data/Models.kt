package com.eis.qringmqtt.data

import org.json.JSONObject

/** État de la connexion Bluetooth avec la bague. */
enum class RingConn(val json: String) {
    NO_RING("no_ring"),
    CONNECTING("connecting"),
    CONNECTED("connected"),
    DISCONNECTED("disconnected"),
    BLUETOOTH_OFF("bluetooth_off");

    val label: String get() = tr("ring.$json")
}

/** État de la connexion au broker MQTT. */
enum class BrokerConn(private val k: String) {
    OFFLINE("offline"),
    CONNECTING("connecting"),
    ONLINE("online");

    val label: String get() = tr("broker.$k")
}

/**
 * Toutes les commandes.
 * - [measure] : mesure « live » sur la bague (une à la fois, chargement à l'écran)
 * - [durationSec] : temps maximum avant « timeout » (cœur 60 s, SpO2 90 s)
 * - [gateway] : commande du gateway (fonctionne aussi sans bague associée)
 */
enum class Cmd(val key: String, val measure: Boolean, val durationSec: Int, val gateway: Boolean = false) {
    HR("hr", true, 60),
    SPO2("spo2", true, 90),
    TEMP("temp", true, 60),
    BP("bp", true, 60),
    HRV("hrv", true, 60),
    STRESS("stress", true, 60),
    ALL("all", true, 90),
    STEPS("steps", false, 0),
    SLEEP("sleep", false, 0),
    SEDENTARY("sedentary", false, 0),
    WORKOUTS("workouts", false, 0),
    HISTORY("history", false, 0),
    BATTERY("battery", false, 0),
    INFO("info", false, 0),
    PING("ping", false, 0, true),
    CANCEL("cancel", false, 0),
    BIND("bind", false, 0, true),
    UNBIND("unbind", false, 0, true),
    SCAN("scan", false, 0, true),
    LANG("lang", false, 0, true);

    val label: String get() = tr("m.$key")

    companion object {
        fun from(key: String?): Cmd? = values().firstOrNull { it.key.equals(key?.trim(), ignoreCase = true) }
    }
}

/** D'où vient une commande. */
enum class Source(val json: String) {
    MQTT("mqtt"), MANUAL("manual"), AUTO("auto");

    val label: String get() = tr("src.$json")
}

/** Une commande à exécuter (MQTT ou bouton). */
data class Command(
    val cmd: Cmd,
    val reqId: String?,
    val source: Source,
    val day: Int = 0,
    /** Paramètre : MAC pour bind, code langue pour lang. */
    val arg: String? = null,
    /** Topic sur lequel répondre ("gateway" ou "ring"). */
    val viaGateway: Boolean = false
)

/** Une valeur affichée sur une carte + publiée sur MQTT. */
data class Reading(
    val type: String,            // hr, spo2, temp, bp, hrv, stress, battery, steps, sleep…
    val values: JSONObject,      // {"value":72,"rri":833} ou {"sbp":120,"dbp":80}…
    val ts: Long,                // secondes
    val source: Source,
    val ringMac: String = ""     // bague qui a fait la mesure
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("type", type); put("values", values); put("ts", ts); put("source", source.json); put("ringMac", ringMac)
    }

    companion object {
        fun fromJson(o: JSONObject): Reading = Reading(
            o.getString("type"),
            o.optJSONObject("values") ?: JSONObject(),
            o.optLong("ts"),
            Source.values().firstOrNull { it.json == o.optString("source") } ?: Source.AUTO,
            o.optString("ringMac", "")
        )
    }
}

/** Mesure en cours (pour le chargement à l'écran). */
data class ActiveMeasure(
    val cmd: Cmd,
    val source: Source,
    val startedAtMs: Long,
    val liveText: String? = null
)

/** Dernier résultat de mesure (écran résultat sur TV). */
data class MeasureResult(
    val cmd: Cmd,
    val ok: Boolean,
    val values: JSONObject?,
    val error: String?,
    val atMs: Long
)

/** Erreur temporaire affichée sur une carte. */
data class CardError(val code: String, val untilMs: Long) {
    val message: String get() = Err.label(code)
}

/** Infos de la bague. */
data class RingInfo(
    val mac: String = "",
    val name: String = "",
    val model: String = "",
    val firmware: String = "",
    val hardware: String = "",
    val battery: Int? = null,
    val charging: Boolean = false,
    val supports: Set<String> = emptySet(),
    val supportsKnown: Boolean = false
)

/** Ligne du journal MQTT. */
data class LogEntry(
    val ts: Long,
    val kind: Kind,
    val topic: String,
    val payload: String
) {
    enum class Kind(private val k: String) {
        IN("in"), OUT("out"), STATUS("status"), MEASURING("measuring"), ERROR("error"), INFO("info");

        val label: String get() = tr("kind.$k")
    }
}

/** Un appareil trouvé pendant le scan. */
data class ScannedRing(val name: String, val mac: String, val rssi: Int)

/** Codes d'erreur envoyés sur MQTT. */
object Err {
    const val RING_DISCONNECTED = "ring_disconnected"
    const val RING_REMOVED = "ring_removed"
    const val TIMEOUT = "timeout"
    const val MEASURE_FAILED = "measure_failed"
    const val NOT_SUPPORTED = "not_supported"
    const val BUSY = "busy"
    const val INVALID_VALUE = "invalid_value"
    const val CANCELLED = "cancelled"
    const val UNKNOWN_COMMAND = "unknown_command"
    const val NO_DATA = "no_data"
    const val NOT_FOUND = "not_found"
    const val BLUETOOTH_OFF = "bluetooth_off"
    const val BAD_REQUEST = "bad_request"

    fun label(code: String): String = tr("err.$code")
}
