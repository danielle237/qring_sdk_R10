package com.eis.qringmqtt.ble

import android.util.Log
import com.eis.qringmqtt.data.AppState
import com.eis.qringmqtt.data.RingConn
import com.oudmon.ble.base.bluetooth.BleBaseControl
import com.oudmon.ble.base.bluetooth.BleOperateManager
import com.oudmon.ble.base.bluetooth.IBleListener
import com.oudmon.ble.base.request.ReadRssiRequest
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.lang.reflect.Proxy

/**
 * Force du signal (RSSI, dBm) de la bague CONNECTÉE, lue toutes les 5 s par la connexion Bluetooth
 * (ReadRssiRequest du SDK) : pas de scan, la connexion n'est pas dérangée.
 * Le SDK ne remonte pas la valeur : on intercale un relais devant son écouteur (IBleListener)
 * pour la récupérer, puis on lui transmet l'appel inchangé.
 */
object RssiReader {
    private const val TAG = "RssiReader"
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    /** Dernier RSSI lu (null = bague non connectée ou pas encore lu). */
    val rssi = MutableStateFlow<Int?>(null)
    @Volatile var atMs = 0L
        private set

    /** Réglage de l'admin (fiche de la bague, message « profile ») : la TV lit-elle le RSSI ? Oui par défaut. */
    @Volatile var enabled = true

    private var hooked: IBleListener? = null
    private var started = false

    fun start() {
        if (started) return
        started = true
        scope.launch {
            while (true) {
                delay(5_000)
                try { tick() } catch (e: Exception) { Log.w(TAG, "rssi", e) }
            }
        }
    }

    /** RSSI récent (moins de 30 s) pour le statut MQTT, sinon null. */
    fun fresh(): Int? = rssi.value?.takeIf { System.currentTimeMillis() - atMs < 30_000 }

    private suspend fun tick() {
        if (!enabled || AppState.ring.value != RingConn.CONNECTED) {
            rssi.value = null
            return
        }
        if (bleMutex.isLocked) return          // mesure / synchro en cours : on ne la dérange pas
        if (!hook()) return
        withContext(Dispatchers.IO) {
            try { BleOperateManager.getInstance().execute(ReadRssiRequest.getInstance()) } catch (_: Exception) {}
        }
    }

    /** Relais devant l'écouteur du SDK (refait si le SDK l'a remplacé). */
    private fun hook(): Boolean {
        val ctl = try { BleBaseControl.getInstance(AppState.appContext) } catch (_: Exception) { null } ?: return false
        val cur = ctl.listener ?: return false
        if (cur === hooked) return true
        val orig = cur
        val relay = Proxy.newProxyInstance(
            IBleListener::class.java.classLoader, arrayOf(IBleListener::class.java)
        ) { _, method, args ->
            if (method.name == "onReadRemoteRssi" && args != null && args.size == 3) {
                val value = args[1] as? Int
                val status = args[2] as? Int
                if (value != null && status == 0 && value < 0) {
                    atMs = System.currentTimeMillis()
                    scope.launch { rssi.value = value }
                }
            }
            if (args == null) method.invoke(orig) else method.invoke(orig, *args)
        } as IBleListener
        ctl.listener = relay
        hooked = relay
        return true
    }
}
