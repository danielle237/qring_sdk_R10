package com.eis.qringmqtt.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** Démarre le service au démarrage du téléphone / de la TV et après une mise à jour de l'app. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.action) {
            Intent.ACTION_BOOT_COMPLETED,
            Intent.ACTION_LOCKED_BOOT_COMPLETED,
            "android.intent.action.QUICKBOOT_POWERON",
            "com.htc.intent.action.QUICKBOOT_POWERON",
            Intent.ACTION_USER_PRESENT,
            Intent.ACTION_MY_PACKAGE_REPLACED -> {
                // Démarrage de la montre / TV, mise à jour, déverrouillage : service lancé + réveil de secours
                if (!RingService.running) RingService.start(context.applicationContext)
                KeepAlive.schedule(context)
            }
        }
    }
}
