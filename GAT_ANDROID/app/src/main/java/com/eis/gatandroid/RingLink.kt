package com.eis.gatandroid

import android.annotation.SuppressLint
import android.app.Application
import android.bluetooth.BluetoothDevice
import android.util.Log
import androidx.localbroadcastmanager.content.LocalBroadcastManager
import com.oudmon.ble.base.bluetooth.BleAction
import com.oudmon.ble.base.bluetooth.BleOperateManager
import com.oudmon.ble.base.bluetooth.DeviceManager
import com.oudmon.ble.base.bluetooth.QCBluetoothCallbackCloneReceiver
import com.oudmon.ble.base.communication.CommandHandle
import com.oudmon.ble.base.communication.Constants
import com.oudmon.ble.base.communication.ICommandResponse
import com.oudmon.ble.base.communication.LargeDataHandler
import com.oudmon.ble.base.communication.req.SetTimeReq
import com.oudmon.ble.base.communication.req.SimpleKeyReq
import com.oudmon.ble.base.communication.rsp.BatteryRsp
import com.oudmon.ble.base.communication.rsp.SetTimeRsp
import com.oudmon.ble.base.communication.rsp.StartHeartRateRsp
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import kotlin.coroutines.resume

/**
 * Session GATT à la demande avec une bague (SDK QRing) :
 * connexion → batterie → mesure cœur → déconnexion. Une seule session à la fois.
 */
@SuppressLint("MissingPermission")
object RingLink {
    private const val TAG = "RingLink"
    private var initialized = false
    @Volatile private var ready: CompletableDeferred<Boolean>? = null

    fun init(app: Application) {
        if (initialized) return
        initialized = true
        BleOperateManager.getInstance(app)
        BleOperateManager.getInstance().init()
        LocalBroadcastManager.getInstance(app).registerReceiver(Receiver(), BleAction.getIntentFilter())
    }

    /** Se connecte à la bague. Deux essais : direct, puis via un scan du SDK. */
    suspend fun connect(mac: String): Boolean {
        val bom = BleOperateManager.getInstance()
        for (attempt in 0..1) {
            val d = CompletableDeferred<Boolean>()
            ready = d
            try {
                DeviceManager.getInstance().deviceAddress = mac
                bom.setNeedConnect(true)
                bom.reConnectMac = mac
                if (attempt == 0) bom.connectDirectly(mac) else bom.connectWithScan(mac)
            } catch (e: Exception) {
                Log.e(TAG, "connect", e)
            }
            val ok = withTimeoutOrNull(if (attempt == 0) 15_000L else 20_000L) { d.await() } ?: false
            if (ok) {
                // Mise à l'heure : la bague répond ensuite aux autres commandes
                delay(800)
                awaitCallback<SetTimeRsp?>(6000) { resume ->
                    CommandHandle.getInstance().executeReqCmd(SetTimeReq(0), ICommandResponse<SetTimeRsp> { resume(it) })
                }
                delay(300)
                return true
            }
            try { bom.disconnect() } catch (_: Exception) {}
            delay(1000)
        }
        return false
    }

    fun disconnect() {
        ready = null
        try {
            val bom = BleOperateManager.getInstance()
            bom.setNeedConnect(false)
            bom.disconnect()
        } catch (_: Exception) {}
    }

    /** Batterie et état de charge, ou null si la bague ne répond pas. */
    suspend fun readBattery(): BatteryRsp? =
        awaitCallback<BatteryRsp?>(6000) { resume ->
            CommandHandle.getInstance().executeReqCmd(
                SimpleKeyReq(Constants.CMD_GET_DEVICE_ELECTRICITY_VALUE),
                ICommandResponse<BatteryRsp> { resume(it) })
        }

    // ------------------------------------------------------------------ mesure cœur

    sealed class Hr {
        data class Ok(val bpm: Int) : Hr()
        /** code : ring_removed, timeout, invalid_value, measure_failed, cancelled */
        data class Fail(val code: String) : Hr()
    }

    private const val IDLE_END_MS = 12_000L
    private const val HARD_TIMEOUT_MS = 60_000L

    /**
     * Mesure la fréquence cardiaque. La bague envoie une valeur par seconde (0 pendant la
     * progression) : on termine après 6 valeurs valides, ou à la fin du silence / du temps maximum.
     */
    suspend fun measureHr(onLive: (Int) -> Unit): Hr = suspendCancellableCoroutine { cont ->
        var done = false
        var best = 0
        var valid = 0
        var empty = 0
        val bom = BleOperateManager.getInstance()

        lateinit var finish: (Hr) -> Unit
        val timeout = Runnable {
            finish(
                when {
                    best > 0 -> Hr.Ok(best)
                    empty > 0 -> Hr.Fail("ring_removed")
                    else -> Hr.Fail("timeout")
                }
            )
        }
        finish = { outcome ->
            if (!done) {
                done = true
                mainHandler.removeCallbacks(timeout)
                try { bom.manualModeHeart(null, true) } catch (_: Exception) {}
                val checked = if (outcome is Hr.Ok && outcome.bpm !in 30..220) Hr.Fail("invalid_value") else outcome
                if (cont.isActive) cont.resume(checked)
            }
        }

        val cb = ICommandResponse<StartHeartRateRsp> { r ->
            mainHandler.post {
                if (done) return@post
                mainHandler.removeCallbacks(timeout)
                mainHandler.postDelayed(timeout, IDLE_END_MS)
                if (r.errCode.toInt() != 0) {
                    finish(if (best > 0) Hr.Ok(best) else Hr.Fail("ring_removed"))
                    return@post
                }
                val v = r.value
                if (v > 0) {
                    best = v; valid++
                    onLive(v)
                    if (valid >= 6) finish(Hr.Ok(v))
                } else empty++
            }
        }

        mainHandler.postDelayed(timeout, HARD_TIMEOUT_MS)
        mainHandler.post {
            try { bom.manualModeHeart(cb, false) }
            catch (e: Exception) { Log.e(TAG, "manualModeHeart", e); finish(Hr.Fail("measure_failed")) }
        }
        cont.invokeOnCancellation { mainHandler.post { finish(Hr.Fail("cancelled")) } }
    }

    // ------------------------------------------------------------------ callbacks SDK

    private class Receiver : QCBluetoothCallbackCloneReceiver() {
        override fun connectStatue(device: BluetoothDevice?, connected: Boolean) {
            if (device != null && connected) {
                try {
                    val n = device.name
                    if (n != null) DeviceManager.getInstance().deviceName = n
                } catch (_: SecurityException) {}
            } else {
                // Déconnexion pendant la connexion = échec de cette tentative
                ready?.complete(false)
            }
        }

        override fun onServiceDiscovered() {
            try { LargeDataHandler.getInstance().initEnable() } catch (_: Exception) {}
            ready?.complete(true)
        }

        override fun onCharacteristicRead(uuid: String?, data: ByteArray?) {}
        override fun onCharacteristicChange(address: String?, uuid: String?, data: ByteArray?) {}
    }
}
