package com.eis.qringmqtt.ble

import org.json.JSONObject

/**
 * Compteurs de stabilité (Bluetooth + MQTT), publiés toutes les 5 min sur
 * eis/colmi/gateway/<TV>/diag et affichés dans l'admin.
 */
object Diag {
    private val disconnects = ArrayDeque<Long>()       // heures des déconnexions de la bague (24 h)
    private val startedAt = System.currentTimeMillis()
    @Volatile var connectedSinceMs = 0L
    @Volatile var lastError: String? = null
    @Volatile var lastErrorAt = 0L
    @Volatile var rescues = 0          // reconnexions de secours (SDK bloqué > 2 min)
    @Volatile var muteResets = 0       // bague connectée mais muette → déconnexion propre
    @Volatile var mqttReconnects = 0
    @Volatile var cmdOk = 0
    @Volatile var cmdMiss = 0

    @Synchronized
    fun disconnected() {
        val now = System.currentTimeMillis()
        disconnects.addLast(now)
        while (disconnects.isNotEmpty() && now - disconnects.first() > 86_400_000L) disconnects.removeFirst()
        connectedSinceMs = 0
    }

    fun connected() { connectedSinceMs = System.currentTimeMillis() }

    fun error(msg: String) {
        lastError = msg.take(160)
        lastErrorAt = System.currentTimeMillis()
    }

    fun command(ok: Boolean) { if (ok) cmdOk++ else cmdMiss++ }

    @Synchronized
    fun toJson(): JSONObject {
        val now = System.currentTimeMillis()
        while (disconnects.isNotEmpty() && now - disconnects.first() > 86_400_000L) disconnects.removeFirst()
        return JSONObject()
            .put("ts", now / 1000)
            .put("uptimeS", (now - startedAt) / 1000)
            .put("ringConnectedS", if (connectedSinceMs > 0) (now - connectedSinceMs) / 1000 else JSONObject.NULL)
            .put("disconnects1h", disconnects.count { now - it <= 3_600_000L })
            .put("disconnects24h", disconnects.size)
            .put("rescues", rescues)
            .put("muteResets", muteResets)
            .put("mqttReconnects", mqttReconnects)
            .put("cmdOk", cmdOk)
            .put("cmdMiss", cmdMiss)
            .put("lastError", lastError ?: JSONObject.NULL)
            .put("lastErrorAt", if (lastErrorAt > 0) lastErrorAt / 1000 else JSONObject.NULL)
    }
}
