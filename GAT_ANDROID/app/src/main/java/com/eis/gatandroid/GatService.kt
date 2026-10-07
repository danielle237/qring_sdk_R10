package com.eis.gatandroid

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
import androidx.core.app.NotificationCompat

/** Service de premier plan : garde la gateway active écran éteint. */
class GatService : Service() {
    private var wake: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            Prefs.running = false
            Gateway.stop()
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
            return START_NOT_STICKY
        }
        startInForeground()
        Prefs.running = true
        try {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            if (wake == null) wake = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "gat:service").apply {
                setReferenceCounted(false); acquire()
            }
        } catch (_: Exception) {}
        Gateway.start(this)
        return START_STICKY
    }

    private fun startInForeground() {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(NotificationChannel(CHANNEL, "Gateway", NotificationManager.IMPORTANCE_LOW))
        }
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val n: Notification = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("GAT_ANDROID")
            .setContentText("Gateway BLE active : ${Prefs.gateway}")
            .setOngoing(true)
            .setContentIntent(open)
            .build()
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
        } else startForeground(1, n)
    }

    override fun onDestroy() {
        try { wake?.release() } catch (_: Exception) {}
        wake = null
        Gateway.stop()
        super.onDestroy()
    }

    companion object {
        const val CHANNEL = "gat"
        const val ACTION_STOP = "com.eis.gatandroid.STOP"
    }
}
