package com.eis.qringmqtt.ble

import android.annotation.SuppressLint
import android.app.Application
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothManager
import android.bluetooth.le.ScanResult
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import androidx.core.content.ContextCompat
import androidx.localbroadcastmanager.content.LocalBroadcastManager
import com.eis.qringmqtt.data.AppState
import com.eis.qringmqtt.data.RingConn
import com.eis.qringmqtt.data.ScannedRing
import com.oudmon.ble.base.bluetooth.BleAction
import com.oudmon.ble.base.bluetooth.BleOperateManager
import com.oudmon.ble.base.bluetooth.DeviceManager
import com.oudmon.ble.base.bluetooth.QCBluetoothCallbackCloneReceiver
import com.oudmon.ble.base.communication.CommandHandle
import com.oudmon.ble.base.communication.Constants
import com.oudmon.ble.base.communication.ICommandResponse
import com.oudmon.ble.base.communication.LargeDataHandler
import com.oudmon.ble.base.communication.req.DeviceSupportReq
import com.oudmon.ble.base.communication.req.SetTimeReq
import com.oudmon.ble.base.communication.req.SimpleKeyReq
import com.oudmon.ble.base.communication.rsp.BatteryRsp
import com.oudmon.ble.base.communication.rsp.DeviceSupportFunctionRsp
import com.oudmon.ble.base.communication.rsp.SetTimeRsp
import com.oudmon.ble.base.scan.BleScannerHelper
import com.oudmon.ble.base.scan.ScanRecord
import com.oudmon.ble.base.scan.ScanWrapperCallback
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Connexion Bluetooth à la bague, reconnexion automatique, scan, batterie, infos.
 */
@SuppressLint("MissingPermission")
object RingManager {

    private const val TAG = "RingManager"
    private lateinit var app: Application
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    /** Émis à chaque changement d'état (connexion / déconnexion / infos) → le service republie le statut. */
    val events = MutableSharedFlow<String>(extraBufferCapacity = 16)

    private var reconnectJob: Job? = null
    internal var attempt = 0
    private var batteryPending = true
    private var initialized = false

    // ------------------------------------------------------------------ initialisation

    fun init(application: Application) {
        if (initialized) return
        initialized = true
        app = application
        BleOperateManager.getInstance(application)
        BleOperateManager.getInstance().init()

        // Callbacks de la bague (connexion, services, lecture des versions)
        LocalBroadcastManager.getInstance(application)
            .registerReceiver(RingCallbackReceiver(), BleAction.getIntentFilter())

        // Bluetooth activé / désactivé
        ContextCompat.registerReceiver(
            application, BluetoothStateReceiver(), BleAction.getDeviceIntentFilter(),
            ContextCompat.RECEIVER_EXPORTED
        )
    }

    val isReady: Boolean get() = AppState.ring.value == RingConn.CONNECTED

    fun isBluetoothOn(): Boolean {
        val bm = app.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
        return bm?.adapter?.isEnabled == true
    }

    // ------------------------------------------------------------------ association

    /** Associe une nouvelle bague (depuis l'écran Scan). */
    fun bind(mac: String, name: String) {
        val prefs = AppState.prefs
        val oldMac = prefs.ringMac
        if (oldMac != null && oldMac != mac) {
            try { BleOperateManager.getInstance().unBindDevice() } catch (_: Exception) {}
        }
        prefs.ringMac = mac
        prefs.ringName = name
        prefs.firmware = null
        prefs.hardware = null
        AppState.info.value = com.eis.qringmqtt.data.RingInfo(
            mac = mac, name = name, model = AppState.modelFromName(name)
        )
        batteryPending = true
        attempt = 0
        connect()
        // Le service change de topic MQTT (l'ancienne bague passe hors ligne)
        when {
            oldMac == null -> events.tryEmit("bound")
            oldMac != mac -> events.tryEmit("ring_changed:$oldMac")
            else -> events.tryEmit("info")
        }
    }

    /**
     * Association à distance (commande MQTT « bind ») : on vérifie d'abord que la bague
     * est à portée (scan ciblé, 15 s max), puis on l'associe.
     * [done] reçoit null si OK, sinon un code d'erreur (not_found, bluetooth_off).
     */
    fun bindRemote(mac: String, done: (String?) -> Unit) {
        val target = normalizeMac(mac)
        if (!isBluetoothOn()) { done(com.eis.qringmqtt.data.Err.BLUETOOTH_OFF); return }
        var finished = false
        val timeout = Runnable {
            if (!finished) {
                finished = true
                try { BleScannerHelper.getInstance().stopScan(app) } catch (_: Exception) {}
                done(com.eis.qringmqtt.data.Err.NOT_FOUND)
            }
        }
        mainHandler.postDelayed(timeout, 15_000)
        try {
            BleScannerHelper.getInstance().scanTheDevice(app, target, object : com.oudmon.ble.base.scan.OnTheScanResult {
                override fun onResult(device: BluetoothDevice?) {
                    mainHandler.post {
                        if (finished || device == null) return@post
                        finished = true
                        mainHandler.removeCallbacks(timeout)
                        val name = try { device.name } catch (_: SecurityException) { null } ?: AppState.prefs.ringName ?: target
                        bind(target, name)
                        done(null)
                    }
                }

                override fun onScanFailed(errorCode: Int) {
                    mainHandler.post {
                        if (finished) return@post
                        finished = true
                        mainHandler.removeCallbacks(timeout)
                        done(com.eis.qringmqtt.data.Err.NOT_FOUND)
                    }
                }
            })
        } catch (e: Exception) {
            Log.e(TAG, "bindRemote", e)
            if (!finished) { finished = true; mainHandler.removeCallbacks(timeout); done(com.eis.qringmqtt.data.Err.NOT_FOUND) }
        }
    }

    /** Dissocie la bague : plus de connexion ni de reconnexion. L'historique est conservé. */
    fun unbind() {
        val oldMac = AppState.prefs.ringMac ?: return
        reconnectJob?.cancel()
        AppState.reconnectInSec.value = null
        try {
            BleOperateManager.getInstance().setNeedConnect(false)
            BleOperateManager.getInstance().unBindDevice()
        } catch (_: Exception) {}
        val prefs = AppState.prefs
        prefs.ringMac = null
        prefs.ringName = null
        prefs.firmware = null
        prefs.hardware = null
        AppState.info.value = com.eis.qringmqtt.data.RingInfo()
        AppState.worn.value = null
        AppState.ring.value = RingConn.NO_RING
        events.tryEmit("unbound:$oldMac")
    }

    /** "c4a15f22a4f1" ou "C4-A1-…" → "C4:A1:5F:22:A4:F1" */
    fun normalizeMac(mac: String): String {
        val hex = mac.filter { it.isLetterOrDigit() }.uppercase()
        return if (hex.length == 12) hex.chunked(2).joinToString(":") else mac.uppercase()
    }

    /** Demande une lecture de batterie dès que possible (ouverture de l'app). */
    fun requestBatteryOnOpen() {
        batteryPending = true
        if (isReady) scope.launch { readBattery() }
    }

    // ------------------------------------------------------------------ connexion

    fun connect() {
        val mac = AppState.prefs.ringMac ?: run {
            AppState.ring.value = RingConn.NO_RING
            return
        }
        if (!isBluetoothOn()) {
            AppState.ring.value = RingConn.BLUETOOTH_OFF
            return
        }
        if (isReady && BleOperateManager.getInstance().isConnected) return
        reconnectJob?.cancel()
        AppState.reconnectInSec.value = null
        AppState.ring.value = RingConn.CONNECTING
        try {
            DeviceManager.getInstance().deviceAddress = mac
            BleOperateManager.getInstance().setNeedConnect(true)
            BleOperateManager.getInstance().reConnectMac = mac
            // Une tentative sur deux passe par un scan (plus fiable si la bague a changé de canal)
            if (attempt % 2 == 0) BleOperateManager.getInstance().connectDirectly(mac)
            else BleOperateManager.getInstance().connectWithScan(mac)
        } catch (e: Exception) {
            Log.e(TAG, "connect", e)
        }
        attempt++
        // Si rien ne se passe en 25 s → nouvelle tentative plus tard
        reconnectJob = scope.launch {
            delay(25_000)
            if (AppState.ring.value == RingConn.CONNECTING) scheduleReconnect()
        }
    }

    /** Reconnexion avec délai croissant : 5 s, 10 s, 30 s puis toutes les 60 s. */
    fun scheduleReconnect() {
        if (AppState.prefs.ringMac == null) return
        if (!isBluetoothOn()) {
            AppState.ring.value = RingConn.BLUETOOTH_OFF
            return
        }
        reconnectJob?.cancel()
        val wait = when (attempt) { 0, 1 -> 5; 2 -> 10; 3 -> 30; else -> 60 }
        AppState.ring.value = RingConn.DISCONNECTED
        reconnectJob = scope.launch {
            for (s in wait downTo 1) {
                AppState.reconnectInSec.value = s
                delay(1000)
            }
            AppState.reconnectInSec.value = null
            connect()
        }
    }

    /** Bouton « Reconnecter ». */
    fun reconnectNow() {
        attempt = 0
        reconnectJob?.cancel()
        try { BleOperateManager.getInstance().disconnect() } catch (_: Exception) {}
        connect()
    }

    internal fun onConnectedAndReady() {
        reconnectJob?.cancel()
        attempt = 0
        AppState.reconnectInSec.value = null
        AppState.ring.value = RingConn.CONNECTED
        events.tryEmit("connected")
        scope.launch {
            delay(800)
            syncTimeAndSupports()
            delay(300)
            try {
                CommandHandle.getInstance().executeReqCmdNoCallback(SimpleKeyReq(Constants.CMD_BIND_SUCCESS))
            } catch (_: Exception) {}
            delay(300)
            readVersions()
            if (batteryPending || AppState.info.value.battery == null) {
                delay(500)
                readBattery()
            }
            events.tryEmit("info")
        }
    }

    internal fun onDisconnected() {
        if (AppState.prefs.ringMac == null) {
            AppState.ring.value = RingConn.NO_RING
            return
        }
        events.tryEmit("disconnected")
        scheduleReconnect()
    }

    // ------------------------------------------------------------------ infos bague

    /** Met la bague à l'heure et récupère la liste des fonctions supportées. */
    private suspend fun syncTimeAndSupports() {
        val rsp = awaitCallback<SetTimeRsp?>(6000) { resume ->
            CommandHandle.getInstance().executeReqCmd(SetTimeReq(0), ICommandResponse<SetTimeRsp> { resume(it) })
        } ?: return
        val s = mutableSetOf("hr", "stress", "steps", "sleep", "sedentary", "history", "battery")
        if (rsp.mSupportBloodOxygen) s += "spo2"
        if (rsp.mSupportTemperature) s += "temp"
        if (rsp.mSupportBloodPressure) s += "bp"
        if (rsp.mSupportHrv) s += "hrv"
        if (rsp.mSupportOneKeyCheck) s += "all"
        val known = rsp.mSupportBloodOxygen || rsp.mSupportTemperature || rsp.mSupportHrv || rsp.mSupportBloodPressure
        AppState.info.update { it.copy(supports = s, supportsKnown = known) }

        // Fonctions complémentaires (données de température/SpO2 par intervalle)
        val sup = awaitCallback<DeviceSupportFunctionRsp?>(4000) { resume ->
            CommandHandle.getInstance().executeReqCmd(
                DeviceSupportReq.getReadInstance(),
                ICommandResponse<DeviceSupportFunctionRsp> { resume(it) })
        }
        if (sup != null) {
            AppState.info.update {
                val extra = it.supports.toMutableSet()
                if (sup.supportIntervalTemperature) extra += "temp_history"
                if (sup.supportIntervalBloodOxygen) extra += "spo2_history"
                it.copy(supports = extra)
            }
        }
    }

    private fun readVersions() {
        try {
            val ch = CommandHandle.getInstance()
            ch.execReadCmd(ch.readFmRequest)
            mainHandler.postDelayed({
                try { ch.execReadCmd(ch.readHwRequest) } catch (_: Exception) {}
            }, 400)
        } catch (e: Exception) {
            Log.w(TAG, "readVersions", e)
        }
    }

    /** Lit la batterie. Renvoie null si la bague ne répond pas. */
    suspend fun readBattery(): BatteryRsp? {
        if (!isReady) return null
        val rsp = awaitCallback<BatteryRsp?>(6000) { resume ->
            CommandHandle.getInstance().executeReqCmd(
                SimpleKeyReq(Constants.CMD_GET_DEVICE_ELECTRICITY_VALUE),
                ICommandResponse<BatteryRsp> { resume(it) })
        }
        if (rsp != null) {
            batteryPending = false
            AppState.info.update {
                it.copy(battery = rsp.batteryValue, charging = rsp.isCharging, batteryAtMs = System.currentTimeMillis())
            }
            events.tryEmit("battery")
        }
        return rsp
    }

    // ------------------------------------------------------------------ scan

    fun startScan() {
        if (!isBluetoothOn()) return
        AppState.scanResults.value = emptyList()
        AppState.scanning.value = true
        try {
            BleScannerHelper.getInstance().reSetCallback()
            BleScannerHelper.getInstance().scanDevice(app, null, scanCallback)
        } catch (e: Exception) {
            Log.e(TAG, "scan", e)
            AppState.scanning.value = false
        }
        mainHandler.removeCallbacks(stopScanRunnable)
        mainHandler.postDelayed(stopScanRunnable, 15_000)
    }

    fun stopScan() {
        mainHandler.removeCallbacks(stopScanRunnable)
        try { BleScannerHelper.getInstance().stopScan(app) } catch (_: Exception) {}
        AppState.scanning.value = false
    }

    private val stopScanRunnable = Runnable { stopScan() }

    private val scanCallback = object : ScanWrapperCallback {
        override fun onStart() {}
        override fun onStop() { AppState.scanning.value = false }
        override fun onLeScan(device: BluetoothDevice?, rssi: Int, scanRecord: ByteArray?) {
            if (device == null) return
            val name = try { device.name } catch (_: SecurityException) { null }
            if (name.isNullOrBlank()) return
            val item = ScannedRing(name, device.address, rssi)
            mainHandler.post {
                AppState.scanResults.update { list ->
                    (list.filter { it.mac != item.mac } + item).sortedByDescending { it.rssi }
                }
            }
        }
        override fun onScanFailed(errorCode: Int) { AppState.scanning.value = false }
        override fun onParsedData(device: BluetoothDevice?, scanRecord: ScanRecord?) {}
        override fun onBatchScanResults(results: MutableList<ScanResult>?) {}
    }

    // ------------------------------------------------------------------ callbacks SDK

    /** Reçoit les événements de la bague envoyés par le SDK. */
    class RingCallbackReceiver : QCBluetoothCallbackCloneReceiver() {
        override fun connectStatue(device: BluetoothDevice?, connected: Boolean) {
            mainHandler.post {
                if (device != null && connected) {
                    try {
                        val n = device.name
                        if (n != null) DeviceManager.getInstance().deviceName = n
                    } catch (_: SecurityException) {}
                    // "connected" mais pas encore prêt : on attend onServiceDiscovered
                    if (AppState.ring.value != RingConn.CONNECTED) AppState.ring.value = RingConn.CONNECTING
                } else {
                    RingManager.onDisconnected()
                }
            }
        }

        override fun onServiceDiscovered() {
            // Obligatoire avant d'envoyer d'autres commandes
            try { LargeDataHandler.getInstance().initEnable() } catch (_: Exception) {}
            mainHandler.post { RingManager.onConnectedAndReady() }
        }

        override fun onCharacteristicRead(uuid: String?, data: ByteArray?) {
            if (uuid == null || data == null) return
            val text = String(data, Charsets.UTF_8).trim { it <= ' ' || it == '\u0000' }
            mainHandler.post {
                when (uuid) {
                    Constants.CHAR_FIRMWARE_REVISION.toString() -> {
                        AppState.prefs.firmware = text
                        AppState.info.update { it.copy(firmware = text) }
                        RingManager.events.tryEmit("info")
                    }
                    Constants.CHAR_HW_REVISION.toString() -> {
                        AppState.prefs.hardware = text
                        AppState.info.update { it.copy(hardware = text) }
                        RingManager.events.tryEmit("info")
                    }
                }
            }
        }

        override fun onCharacteristicChange(address: String?, uuid: String?, data: ByteArray?) {}
    }

    /** Bluetooth du téléphone / de la TV activé ou désactivé. */
    class BluetoothStateReceiver : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.action != BluetoothAdapter.ACTION_STATE_CHANGED) return
            when (intent.getIntExtra(BluetoothAdapter.EXTRA_STATE, -1)) {
                BluetoothAdapter.STATE_OFF -> {
                    try {
                        BleOperateManager.getInstance().setBluetoothTurnOff(false)
                        BleOperateManager.getInstance().disconnect()
                    } catch (_: Exception) {}
                    if (AppState.prefs.ringMac != null) AppState.ring.value = RingConn.BLUETOOTH_OFF
                    RingManager.events.tryEmit("bluetooth_off")
                }
                BluetoothAdapter.STATE_ON -> {
                    try { BleOperateManager.getInstance().setBluetoothTurnOff(true) } catch (_: Exception) {}
                    RingManager.attempt = 0
                    mainHandler.postDelayed({ RingManager.connect() }, 1500)
                }
            }
        }
    }
}
