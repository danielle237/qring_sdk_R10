package com.eis.qringmqtt.mqtt

import android.content.Context
import android.net.ConnectivityManager
import android.os.Build
import android.provider.Settings
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.NetworkInterface
import java.net.URL

/** Nom de l'appareil (TV), adresses LAN et WAN envoyés dans le statut MQTT. */
object NetInfo {

    @Volatile
    var wanIp: String? = null
        private set
    private var lastWanCheck = 0L

    /** Nom donné à la TV dans les paramètres Android (À propos → Nom de l'appareil). */
    fun deviceName(ctx: Context): String {
        val cr = ctx.contentResolver
        val names = listOfNotNull(
            if (Build.VERSION.SDK_INT >= 25) try { Settings.Global.getString(cr, Settings.Global.DEVICE_NAME) } catch (_: Exception) { null } else null,
            try { Settings.Secure.getString(cr, "bluetooth_name") } catch (_: Exception) { null },
            Build.MODEL
        )
        return names.firstOrNull { it.isNotBlank() } ?: "android"
    }

    /** « TV Chambre 104 » → « TV-Chambre-104 » (utilisable dans un topic MQTT). */
    fun topicSafe(name: String): String =
        name.trim().replace(Regex("[^A-Za-z0-9_.-]+"), "-").trim('-').ifBlank { "android" }

    /** IP locale (Wi-Fi / Ethernet), ex. 192.168.1.25 */
    fun lanIp(ctx: Context): String? {
        try {
            val cm = ctx.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            val lp = cm.getLinkProperties(cm.activeNetwork)
            lp?.linkAddresses?.map { it.address }?.firstOrNull { it is Inet4Address && !it.isLoopbackAddress }
                ?.hostAddress?.let { return it }
        } catch (_: Exception) {
        }
        try {
            for (ni in NetworkInterface.getNetworkInterfaces()) {
                if (!ni.isUp || ni.isLoopback) continue
                for (a in ni.inetAddresses) if (a is Inet4Address && !a.isLoopbackAddress) return a.hostAddress
            }
        } catch (_: Exception) {
        }
        return null
    }

    /** IP publique, demandée à api.ipify.org (au plus toutes les 30 min sauf [force]). */
    suspend fun refreshWan(force: Boolean = false): String? = withContext(Dispatchers.IO) {
        val now = System.currentTimeMillis()
        if (!force && wanIp != null && now - lastWanCheck < 30 * 60_000) return@withContext wanIp
        lastWanCheck = now
        try {
            val c = URL("https://api.ipify.org").openConnection() as HttpURLConnection
            c.connectTimeout = 5000
            c.readTimeout = 5000
            val ip = c.inputStream.bufferedReader().use { it.readText().trim() }
            c.disconnect()
            if (ip.matches(Regex("[0-9a-fA-F:.]{3,45}"))) wanIp = ip
        } catch (_: Exception) {
        }
        wanIp
    }
}
