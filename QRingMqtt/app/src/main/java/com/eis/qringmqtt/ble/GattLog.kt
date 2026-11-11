package com.eis.qringmqtt.ble

import android.os.SystemClock
import android.util.Log
import com.eis.qringmqtt.data.AppState
import com.eis.qringmqtt.data.LogEntry

/**
 * JALON 0 — journal GATT horodaté (horloge monotone, ms depuis le démarrage de l'appareil).
 * Une ligne par étape : CMD, CONNECT_CALL, CONNECTED, SERVICES, MEASURE_START, MEASURE_END,
 * DISCONNECT_CALL, DISCONNECTED, CLOSE, RELEASE_OK / RELEASE_UNKNOWN, SCAN_RESUME, BUSY,
 * UNEXPECTED_RECONNECT. Visible dans le Journal de l'app et dans logcat (tag QRingMqtt).
 * Aucun identifiant MQTT ni donnée personnelle.
 */
object GattLog {
    fun step(step: String, detail: String = "") {
        val t = SystemClock.elapsedRealtime()
        val mac = AppState.prefs.ringMac ?: "-"
        val line = "t=$t ms · $step · $mac" + if (detail.isNotBlank()) " · $detail" else ""
        try { Log.i("QRingMqtt", "GATT $line") } catch (_: Exception) {}
        AppState.log(LogEntry.Kind.INFO, "gatt", line)
    }
}
