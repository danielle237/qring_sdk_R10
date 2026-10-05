package com.eis.qringmqtt.ui

import android.Manifest
import android.annotation.SuppressLint
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import androidx.core.content.ContextCompat

/** Autorisations nécessaires au fonctionnement en tâche de fond. */
object Background {

    /** Permissions à demander à l'utilisateur (fenêtres Android). */
    fun runtimePermissions(): Array<String> {
        val list = mutableListOf<String>()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            list += Manifest.permission.BLUETOOTH_SCAN
            list += Manifest.permission.BLUETOOTH_CONNECT
        }
        list += Manifest.permission.ACCESS_FINE_LOCATION
        list += Manifest.permission.ACCESS_COARSE_LOCATION
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) list += Manifest.permission.POST_NOTIFICATIONS
        return list.toTypedArray()
    }

    /** Permissions indispensables pour démarrer le service (Bluetooth). */
    fun hasBlePermissions(ctx: Context): Boolean {
        val needed = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S)
            listOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
        else listOf(Manifest.permission.ACCESS_FINE_LOCATION)
        return needed.all { ContextCompat.checkSelfPermission(ctx, it) == PackageManager.PERMISSION_GRANTED }
    }

    fun isIgnoringBattery(ctx: Context): Boolean {
        val pm = ctx.getSystemService(Context.POWER_SERVICE) as PowerManager
        return pm.isIgnoringBatteryOptimizations(ctx.packageName)
    }

    /** Ouvre directement la fenêtre « Autoriser l'app à tourner en arrière-plan ? ». */
    @SuppressLint("BatteryLife")
    fun requestIgnoreBattery(ctx: Context) {
        if (isIgnoringBattery(ctx)) return
        val direct = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
            .setData(Uri.parse("package:${ctx.packageName}"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        val list = Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        try { ctx.startActivity(direct) } catch (_: Exception) {
            try { ctx.startActivity(list) } catch (_: Exception) {}
        }
    }

    /** Pages « démarrage automatique » des fabricants (Xiaomi, Huawei, Oppo, Vivo…). */
    private val autostartIntents = listOf(
        ComponentName("com.miui.securitycenter", "com.miui.permcenter.autostart.AutoStartManagementActivity"),
        ComponentName("com.huawei.systemmanager", "com.huawei.systemmanager.startupmgr.ui.StartupNormalAppListActivity"),
        ComponentName("com.huawei.systemmanager", "com.huawei.systemmanager.optimize.process.ProtectActivity"),
        ComponentName("com.coloros.safecenter", "com.coloros.safecenter.permission.startup.StartupAppListActivity"),
        ComponentName("com.oppo.safe", "com.oppo.safe.permission.startup.StartupAppListActivity"),
        ComponentName("com.vivo.permissionmanager", "com.vivo.permissionmanager.activity.BgStartUpManagerActivity"),
        ComponentName("com.iqoo.secure", "com.iqoo.secure.ui.phoneoptimize.AddWhiteListActivity"),
        ComponentName("com.letv.android.letvsafe", "com.letv.android.letvsafe.AutobootManageActivity"),
        ComponentName("com.asus.mobilemanager", "com.asus.mobilemanager.MainActivity")
    )

    private fun autostartIntent(ctx: Context): Intent? =
        autostartIntents.map { Intent().setComponent(it).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) }
            .firstOrNull { ctx.packageManager.resolveActivity(it, 0) != null }

    fun hasAutostartPage(ctx: Context): Boolean = autostartIntent(ctx) != null

    fun openAutostart(ctx: Context) {
        val i = autostartIntent(ctx) ?: Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
            .setData(Uri.parse("package:${ctx.packageName}")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        try { ctx.startActivity(i) } catch (_: Exception) {}
    }
}
