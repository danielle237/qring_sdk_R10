package com.eis.qringmqtt.mqtt

import android.os.SystemClock
import org.json.JSONObject

/**
 * APK RHM V0.1 — présence des bagues par ADVERTISING (aucune connexion GATT).
 * Chaque annonce reçue pendant les fenêtres de scan est comptée : MAC, nom, dernier RSSI,
 * nombre de paquets de la dernière fenêtre, heure de la dernière annonce. Uniquement des valeurs observées.
 */
object PresenceTracker {
    private data class Seen(var name: String, var rssi: Int, var lastMs: Long, var packets: Int)
    private val seen = LinkedHashMap<String, Seen>()
    private val nameRx = Regex("(COLMI|QRING|\\bR\\d{2,3}[_ ])", RegexOption.IGNORE_CASE)

    /** Bague COLMI / QRing (d'après le nom annoncé). */
    fun isRing(name: String?): Boolean = !name.isNullOrBlank() && nameRx.containsMatchIn(name)

    @Synchronized fun onAdvertising(mac: String, name: String?, rssi: Int) {
        val m = mac.uppercase()
        if (!isRing(name) && seen[m] == null) return
        val now = SystemClock.elapsedRealtime()
        val s = seen.getOrPut(m) { Seen(name ?: "", rssi, now, 0) }
        if (!name.isNullOrBlank()) s.name = name
        s.rssi = rssi; s.lastMs = now; s.packets++
    }

    /** Début d'une nouvelle fenêtre de scan : le compteur de paquets repart de zéro. */
    @Synchronized fun newWindow() { seen.values.forEach { it.packets = 0 } }

    @Synchronized fun nameOf(mac: String): String? = seen[mac.uppercase()]?.name?.takeIf { it.isNotBlank() }

    @Synchronized fun lastSeenMs(mac: String): Long? = seen[mac.uppercase()]?.let { SystemClock.elapsedRealtime() - it.lastMs }

    /**
     * {"ring_0":{"mac","seen","rssi","last_seen_ms","packets"}, …} — format à confirmer par EIS.
     * Bagues vues depuis moins de 2 min ; la bague suivie est toujours incluse (seen=false si absente).
     */
    @Synchronized fun json(followedMac: String?): JSONObject {
        val now = SystemClock.elapsedRealtime()
        val out = JSONObject()
        var i = 0
        val macs = LinkedHashSet<String>()
        followedMac?.uppercase()?.let { macs += it }
        seen.filter { now - it.value.lastMs < 120_000L }.keys.forEach { macs += it }
        for (m in macs) {
            val s = seen[m]
            val fresh = s != null && now - s.lastMs < 60_000L
            out.put("ring_$i", JSONObject()
                .put("mac", m)
                .put("seen", fresh)
                .put("rssi", if (s != null && fresh) s.rssi else JSONObject.NULL)
                .put("last_seen_ms", s?.let { now - it.lastMs } ?: JSONObject.NULL)
                .put("packets", if (fresh) s!!.packets else 0))
            i++
        }
        return out
    }
}
