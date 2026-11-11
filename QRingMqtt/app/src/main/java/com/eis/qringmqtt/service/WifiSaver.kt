package com.eis.qringmqtt.service

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.wifi.WifiManager
import android.os.Build
import com.eis.qringmqtt.data.AppState
import com.eis.qringmqtt.data.LogEntry
import com.eis.qringmqtt.mqtt.MqttManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Wi-Fi de la Gateway RHM Android (réglé depuis l'admin) :
 *  - « always » : Wi-Fi toujours actif (WifiLock), comme avant — TV ;
 *  - « eco »    : montre DM100 / DM80 : Wi-Fi coupé ; rallumé quand un résultat doit partir et toutes les
 *                 N minutes (wifiWakeMin) pour envoyer le statut et lire les ordres gardés par le broker
 *                 (session MQTT persistante, QoS 1). Avant de couper : statut « en veille jusqu'à HH:MM »
 *                 et déconnexion propre (pas de « hors ligne » chez l'admin).
 *  - Réseau par CÂBLE (Ethernet) : jamais de veille, envoi normal sans interruption.
 * Couper / rallumer le Wi-Fi n'est permis par Android que jusqu'à Android 9 (DM100 = 7.1, DM80 = 8.1) ;
 * au-delà, seul le WifiLock est relâché (économie du Wi-Fi par le système).
 */
object WifiSaver {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var ctx: Context? = null
    private var mqtt: MqttManager? = null
    private var wifiLock: WifiManager.WifiLock? = null
    private var loop: Job? = null
    private val wake = Channel<Unit>(Channel.CONFLATED)
    @Volatile private var awakeUntilMs = 0L
    /** Wi-Fi coupé par l'app (à rallumer si on quitte le mode éco). */
    private var turnedOff = false

    /** Heure (s) du prochain réveil quand le Wi-Fi est en veille, 0 sinon. */
    @Volatile var sleepUntil = 0L
        private set

    val eco: Boolean get() = AppState.prefs.wifiMode == "eco"

    fun init(context: Context, m: MqttManager) {
        ctx = context.applicationContext
        mqtt = m
        apply()
    }

    /** Mode changé (admin) ou démarrage. */
    fun apply() {
        if (!eco) {
            loop?.cancel(); loop = null
            sleepUntil = 0
            acquireLock()
            if (turnedOff) setWifi(true)
            mqtt?.resume()
        } else {
            releaseLock()
            if (loop == null) loop = scope.launch { run() }
        }
    }

    /** Un résultat attend d'être envoyé : réveil immédiat du Wi-Fi. */
    fun requestWake() {
        if (eco) wake.trySend(Unit)
    }

    /** Ordre reçu : on reste éveillé un moment (d'autres ordres peuvent suivre). */
    fun keepAwake(ms: Long = 60_000L) {
        awakeUntilMs = maxOf(awakeUntilMs, System.currentTimeMillis() + ms)
    }

    fun shutdown() {
        loop?.cancel(); loop = null
        releaseLock()
        if (turnedOff) setWifi(true)
    }

    /** « cable », « wifi », « mobile » ou « none ». */
    fun netType(): String {
        val cm = ctx?.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager ?: return "none"
        return try {
            @Suppress("DEPRECATION")
            val nets = cm.allNetworks
            var t = "none"
            for (n in nets) {
                val c = cm.getNetworkCapabilities(n) ?: continue
                if (c.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)) return "cable"
                if (c.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) t = "wifi"
                else if (c.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) && t == "none") t = "mobile"
            }
            t
        } catch (_: Exception) { "none" }
    }

    private fun onCable() = netType() == "cable"

    private suspend fun run() {
        while (scope.isActive && eco) {
            // ---- éveillé : Wi-Fi + MQTT, statut et ordres en attente
            val now0 = System.currentTimeMillis()
            awakeUntilMs = maxOf(awakeUntilMs, now0 + 60_000L)
            sleepUntil = 0
            setWifi(true)
            mqtt?.resume()
            while (true) {
                delay(2_000)
                if (!eco) return
                val now = System.currentTimeMillis()
                if (onCable()) { awakeUntilMs = now + 60_000L; continue }      // câble : toujours en ligne
                val m = mqtt
                val busy = AppState.active.value != null || AppState.syncing.value != null ||
                    AppState.queued.value.isNotEmpty() || AppState.pendingPublish.value > 0
                if (now >= awakeUntilMs && !busy && m != null && m.isConnected()) break
                if (now >= awakeUntilMs + 120_000L && AppState.active.value == null) break   // pas de réseau : on se rendort
            }
            // ---- veille
            val wakeMin = AppState.prefs.wifiWakeMin
            sleepUntil = System.currentTimeMillis() / 1000 + wakeMin * 60L
            AppState.log(LogEntry.Kind.INFO, "wifi", "Wi-Fi en veille pour $wakeMin min")
            mqtt?.sleep()
            delay(1_500)
            setWifi(false)
            withTimeoutOrNull(wakeMin * 60_000L) { wake.receive() }
            AppState.log(LogEntry.Kind.INFO, "wifi", "Réveil du Wi-Fi")
        }
    }

    private fun wm(): WifiManager? = ctx?.applicationContext?.getSystemService(Context.WIFI_SERVICE) as? WifiManager

    private fun setWifi(on: Boolean) {
        if (Build.VERSION.SDK_INT >= 29) return          // interdit par Android 10+
        val w = wm() ?: return
        try {
            if (w.isWifiEnabled == on) { if (on) turnedOff = false; return }
            @Suppress("DEPRECATION")
            w.isWifiEnabled = on
            turnedOff = !on
        } catch (_: Exception) {
        }
    }

    private fun acquireLock() {
        if (wifiLock?.isHeld == true) return
        try {
            @Suppress("DEPRECATION")
            wifiLock = wm()?.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "qring:wifi")?.apply {
                setReferenceCounted(false)
                acquire()
            }
        } catch (_: Exception) {
        }
    }

    private fun releaseLock() {
        try { wifiLock?.release() } catch (_: Exception) {}
        wifiLock = null
    }
}
