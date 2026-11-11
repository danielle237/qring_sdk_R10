package com.eis.qringmqtt.service

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.SystemClock

/**
 * Le service ne doit jamais rester arrêté (montres Android 7 / 8 qui ferment les apps en arrière-plan) :
 *  - réveil toutes les 15 min (AlarmManager) → relance le service s'il a été tué ;
 *  - relance 2 s après si l'app est balayée ou le service détruit ;
 *  - relance aussi au déverrouillage de l'écran (USER_PRESENT, reçu jusqu'à Android 7.1).
 */
object KeepAlive {
    private const val EVERY_MS = 15 * 60_000L

    private fun pi(ctx: Context, code: Int): PendingIntent =
        PendingIntent.getBroadcast(
            ctx, code, Intent(ctx, KeepAliveReceiver::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

    fun schedule(context: Context) {
        val ctx = context.applicationContext
        try {
            val am = ctx.getSystemService(Context.ALARM_SERVICE) as AlarmManager
            am.setInexactRepeating(
                AlarmManager.ELAPSED_REALTIME_WAKEUP,
                SystemClock.elapsedRealtime() + 60_000L, EVERY_MS, pi(ctx, 7001)
            )
        } catch (_: Exception) {
        }
    }

    fun restartSoon(context: Context, delayMs: Long = 2_000L) {
        val ctx = context.applicationContext
        try {
            val am = ctx.getSystemService(Context.ALARM_SERVICE) as AlarmManager
            am.set(AlarmManager.ELAPSED_REALTIME_WAKEUP, SystemClock.elapsedRealtime() + delayMs, pi(ctx, 7002))
        } catch (_: Exception) {
        }
    }
}

class KeepAliveReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (!RingService.running) RingService.start(context.applicationContext)
    }
}
