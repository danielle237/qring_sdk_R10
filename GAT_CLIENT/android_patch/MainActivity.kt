package com.eis.gat_client

import android.content.Context
import android.net.wifi.WifiManager
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

/** Verrou multicast Wi-Fi : sans lui Android filtre les paquets UDP multicast reçus. */
class MainActivity : FlutterActivity() {
    private var lock: WifiManager.MulticastLock? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "gat/multicast")
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "acquire" -> {
                        if (lock == null) {
                            val wm = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
                            lock = wm.createMulticastLock("gat-client").apply {
                                setReferenceCounted(false)
                                acquire()
                            }
                        }
                        result.success(true)
                    }
                    "release" -> {
                        try { lock?.release() } catch (_: Exception) {}
                        lock = null
                        result.success(true)
                    }
                    else -> result.notImplemented()
                }
            }
    }

    override fun onDestroy() {
        try { lock?.release() } catch (_: Exception) {}
        super.onDestroy()
    }
}
