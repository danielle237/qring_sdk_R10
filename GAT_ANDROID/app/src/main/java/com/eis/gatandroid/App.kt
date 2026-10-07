package com.eis.gatandroid

import android.app.Application
import android.content.Context
import android.content.Intent
import android.content.BroadcastReceiver
import androidx.core.content.ContextCompat

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        Prefs.init(this)
        PassiveScanner.init(this)
        RingLink.init(this)
    }
}

/** Relance la gateway au démarrage de l'appareil si elle tournait. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        Prefs.init(context)
        if (Prefs.running) {
            try {
                ContextCompat.startForegroundService(context, Intent(context, GatService::class.java))
            } catch (_: Exception) {}
        }
    }
}
