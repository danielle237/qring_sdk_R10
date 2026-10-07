package com.eis.gatandroid

import android.annotation.SuppressLint
import android.bluetooth.BluetoothManager
import android.bluetooth.le.BluetoothLeScanner
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.util.Log
import java.util.concurrent.ConcurrentHashMap

/**
 * Scan BLE passif (advertising seulement, aucune connexion GATT).
 * Sert à dire si une bague surveillée est détectée par cette gateway, et avec quel RSSI.
 */
@SuppressLint("MissingPermission")
object PassiveScanner {
    private const val TAG = "PassiveScanner"
    private var ctx: Context? = null
    private var scanner: BluetoothLeScanner? = null
    @Volatile private var active = false

    private val seen = ConcurrentHashMap<String, SeenRing>()
    /** RSSI reçus depuis le dernier envoi OBS, par bague surveillée. */
    private val window = ConcurrentHashMap<String, MutableList<Int>>()
    private val ringName = Regex("^R\\d{2}_", RegexOption.IGNORE_CASE)

    private val cb = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, r: ScanResult) {
            val mac = normMac(r.device.address)
            val name = r.scanRecord?.deviceName ?: try { r.device.name } catch (_: Exception) { null }
            val monitored = Prefs.rings.contains(mac)
            if (monitored) {
                window.getOrPut(mac) { java.util.Collections.synchronizedList(mutableListOf()) }.add(r.rssi)
            }
            if (monitored || (name != null && ringName.containsMatchIn(name))) {
                seen[mac] = SeenRing(mac, name ?: seen[mac]?.name, r.rssi, System.currentTimeMillis())
            }
        }

        override fun onScanFailed(errorCode: Int) {
            Log.w(TAG, "scan failed $errorCode")
            GatState.log("Scan BLE échoué (code $errorCode)")
            active = false
        }
    }

    fun init(c: Context) { ctx = c.applicationContext }

    val isActive: Boolean get() = active

    fun start() {
        val c = ctx ?: return
        if (active) return
        try {
            val bm = c.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager
            val ad = bm.adapter
            if (ad == null || !ad.isEnabled) { GatState.log("Bluetooth désactivé"); return }
            scanner = ad.bluetoothLeScanner
            val settings = ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build()
            scanner?.startScan(null, settings, cb)
            active = true
            GatState.log("Scan passif démarré")
        } catch (e: Exception) {
            Log.e(TAG, "start", e)
            GatState.log("Scan impossible : ${e.message}")
        }
    }

    fun stop() {
        if (!active) return
        try { scanner?.stopScan(cb) } catch (_: Exception) {}
        active = false
        GatState.log("Scan passif suspendu")
    }

    /** Médiane des RSSI vus depuis le dernier appel, par bague (et remet la fenêtre à zéro). */
    fun drainWindow(): Map<String, Int> {
        val out = HashMap<String, Int>()
        for (mac in window.keys.toList()) {
            val list = window.remove(mac) ?: continue
            val copy = synchronized(list) { list.sorted() }
            if (copy.isNotEmpty()) out[mac] = copy[copy.size / 2]
        }
        return out
    }

    fun snapshot(): List<SeenRing> {
        val now = System.currentTimeMillis()
        seen.entries.removeIf { now - it.value.lastMs > 120_000 }
        return seen.values.sortedByDescending { it.rssi }
    }

    fun nameOf(mac: String): String? = seen[mac]?.name
}
