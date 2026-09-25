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
            Intent.ACTION_MY_PACKAGE_REPLACED -> RingService.start(context.applicationContext)
        }
    }
}
