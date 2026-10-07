package com.eis.qringmqtt.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import com.eis.qringmqtt.R
import com.eis.qringmqtt.ble.RingManager
import com.eis.qringmqtt.data.AppState
import com.eis.qringmqtt.data.BrokerConn
import com.eis.qringmqtt.data.Cmd
import com.eis.qringmqtt.data.Command
import com.eis.qringmqtt.data.Source
import com.eis.qringmqtt.data.RingConn
import com.eis.qringmqtt.data.tr
import com.eis.qringmqtt.mqtt.MqttManager
import com.eis.qringmqtt.mqtt.NetInfo
import com.eis.qringmqtt.ui.MainActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Service en tâche de fond : garde la bague et le broker connectés,
 * reçoit les commandes MQTT, lance les mesures, publie le statut chaque minute.
 * Il tourne même si l'interface est fermée, et redémarre au boot.
 */
class RingService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var mqtt: MqttManager? = null
    private var wakeLock: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        running = true
        createChannel()
        if (!goForeground()) {
            // Permissions Bluetooth pas encore accordées : l'interface relancera le service
            running = false
            stopSelf()
            return
        }
        acquireWakeLock()

        RingManager.init(application)
        CommandProcessor.start()

        val m = MqttManager(
            context = applicationContext,
            onCommand = { payload, viaGateway -> CommandProcessor.onMqttPayload(payload, viaGateway) },
            statusPayload = { online -> CommandProcessor.statusPayload(online) },
            onConnected = {}
        )
        mqtt = m
        CommandProcessor.mqtt = m
        m.start()
        RingManager.connect()

        // Sommeil : synchronisation automatique une fois par jour (à partir de 8 h), bague connectée
        // et libre → les nuits de la bague (≈ 7 jours) partent au serveur, qui garde 30 jours et plus.
        scope.launch {
            delay(60_000)
            while (isActive) {
                val cal = java.util.Calendar.getInstance()
                val today = java.text.SimpleDateFormat("yyyy-MM-dd", java.util.Locale.ROOT).format(cal.time)
                if (cal.get(java.util.Calendar.HOUR_OF_DAY) >= 8 && AppState.prefs.lastSleepSync != today &&
                    AppState.ring.value == RingConn.CONNECTED && AppState.active.value == null &&
                    AppState.syncing.value == null
                ) {
                    AppState.prefs.lastSleepSync = today
                    CommandProcessor.submit(Command(Cmd.SLEEP, null, Source.AUTO))
                }
                delay(10 * 60_000L)
            }
        }

        // Statut toutes les 60 secondes tant que le gateway est connecté (+ IP publique)
        scope.launch {
            NetInfo.refreshWan(force = true)
            if (m.isConnected()) m.publishStatusNow(true)
            while (isActive) {
                delay(60_000)
                NetInfo.refreshWan()
                if (m.isConnected()) m.publishStatusNow(true)
            }
        }

        // Statut republié immédiatement à chaque changement (connexion bague, batterie…)
        scope.launch {
            RingManager.events.collect { ev ->
                if (ev.startsWith("ring_changed:")) {
                    val oldMac = ev.substringAfter(':')
                    m.publishRingOffline(oldMac, "ring_changed")
                    m.restart()
                } else if (ev.startsWith("unbound:")) {
                    // Dissociation : l'ancienne bague passe hors ligne, le gateway reste en ligne
                    m.publishRingOffline(ev.substringAfter(':'), "ring_unbound")
                    m.restart()
                } else if (ev == "bound" && AppState.prefs.ringMac != null) {
                    // première association : on passe du topic gateway au topic de la bague
                    m.restart()
                } else if (m.isConnected()) {
                    m.publishStatusNow(true)
                }
            }
        }

        // Notification mise à jour avec l'état
        scope.launch {
            combine(AppState.ring, AppState.broker, AppState.info, AppState.active) { r, b, i, a ->
                buildText(r, b, i.battery, a?.cmd?.label)
            }.distinctUntilChanged().collect { updateNotification(it) }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_RESTART_MQTT -> mqtt?.restart()
            ACTION_CANCEL -> CommandProcessor.cancelCurrent()
        }
        // START_STICKY : Android relance le service s'il est tué
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        CommandProcessor.mqtt = null
        mqtt?.stop()
        scope.cancel()
        try { wakeLock?.release() } catch (_: Exception) {}
        super.onDestroy()
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        // L'utilisateur a balayé l'app : le service continue
        super.onTaskRemoved(rootIntent)
    }

    // ------------------------------------------------------------------ notification

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val ch = NotificationChannel(CHANNEL, tr("n.channel"), NotificationManager.IMPORTANCE_LOW)
            ch.setShowBadge(false)
            getSystemService(NotificationManager::class.java).createNotificationChannel(ch)
        }
    }

    private fun buildNotification(text: String): Notification {
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val cancel = PendingIntent.getService(
            this, 1, Intent(this, RingService::class.java).setAction(ACTION_CANCEL),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val b = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(tr("n.title"))
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(open)
            .setPriority(NotificationCompat.PRIORITY_LOW)
        if (AppState.active.value != null) b.addAction(0, tr("n.cancel"), cancel)
        return b.build()
    }

    private fun buildText(r: RingConn, b: BrokerConn, battery: Int?, measuring: String?): String {
        val ring = when (r) {
            RingConn.CONNECTED -> tr("n.ring_ok") + (battery?.let { " · $it %" } ?: "")
            RingConn.DISCONNECTED -> tr("err.ring_disconnected")
            else -> r.label
        }
        val broker = tr("n.broker", b.label)
        val m = measuring?.let { "\n" + tr("n.measuring", it) } ?: ""
        return "$ring · $broker$m"
    }

    private fun updateNotification(text: String) {
        try {
            getSystemService(NotificationManager::class.java).notify(NOTIF_ID, buildNotification(text))
        } catch (_: Exception) {
        }
    }

    private fun goForeground(): Boolean = try {
        val n = buildNotification(tr("n.starting"))
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q)
            ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE else 0
        ServiceCompat.startForeground(this, NOTIF_ID, n, type)
        true
    } catch (e: Exception) {
        Log.e("RingService", "startForeground", e)
        false
    }

    private fun acquireWakeLock() {
        try {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "qring:service").apply {
                setReferenceCounted(false)
                acquire()
            }
        } catch (_: Exception) {
        }
    }

    companion object {
        private const val CHANNEL = "qring_service"
        private const val NOTIF_ID = 42
        const val ACTION_RESTART_MQTT = "com.eis.qringmqtt.RESTART_MQTT"
        const val ACTION_CANCEL = "com.eis.qringmqtt.CANCEL"

        @Volatile
        var running = false
            private set

        fun start(context: Context) {
            try {
                ContextCompat.startForegroundService(context, Intent(context, RingService::class.java))
            } catch (e: Exception) {
                Log.e("RingService", "start", e)
            }
        }

        fun restartMqtt(context: Context) {
            if (!running) return start(context)
            context.startService(Intent(context, RingService::class.java).setAction(ACTION_RESTART_MQTT))
        }
    }
}
