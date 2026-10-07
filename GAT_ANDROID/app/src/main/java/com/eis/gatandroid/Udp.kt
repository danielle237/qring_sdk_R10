package com.eis.gatandroid

import android.content.Context
import android.net.ConnectivityManager
import android.net.wifi.WifiManager
import android.util.Log
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.MulticastSocket
import java.net.NetworkInterface
import java.util.concurrent.Executors

/**
 * UDP multicast, même protocole que la page « Live Ring Map » :
 *  - 239.10.10.10:5010  présence (OBS), envoyée par les gateways
 *  - 239.10.10.12:5012  commandes (GATT_CMD), reçues
 *  - 239.10.10.13:5013  statut / résultat de mesure (GATT_STATUS, GATT_RESULT), envoyés
 */
object Udp {
    private const val TAG = "Udp"
    const val OBS_GROUP = "239.10.10.10"; const val OBS_PORT = 5010
    const val CMD_GROUP = "239.10.10.12"; const val CMD_PORT = 5012
    const val RES_GROUP = "239.10.10.13"; const val RES_PORT = 5013

    private var sender: MulticastSocket? = null
    private var receiver: MulticastSocket? = null
    private var lock: WifiManager.MulticastLock? = null
    private var thread: Thread? = null
    @Volatile private var running = false
    private val sendExec = Executors.newSingleThreadExecutor()

    fun start(ctx: Context, onCommand: (JSONObject) -> Unit) {
        if (running) return
        val app = ctx.applicationContext
        try {
            val wm = app.getSystemService(Context.WIFI_SERVICE) as? WifiManager
            lock = wm?.createMulticastLock("gat-multicast")?.apply { setReferenceCounted(false); acquire() }
        } catch (e: Exception) { Log.w(TAG, "multicast lock", e) }

        val ni = pickInterface(app)
        try {
            val s = MulticastSocket()
            s.timeToLive = 1
            if (ni != null) try { s.networkInterface = ni } catch (_: Exception) {}
            sender = s

            val r = MulticastSocket(null as java.net.SocketAddress?)
            r.reuseAddress = true
            r.bind(InetSocketAddress(CMD_PORT))
            val grp = InetAddress.getByName(CMD_GROUP)
            if (ni != null) r.joinGroup(InetSocketAddress(grp, CMD_PORT), ni)
            else @Suppress("DEPRECATION") r.joinGroup(grp)
            r.soTimeout = 1000
            receiver = r
            running = true
            GatState.udp.value = "actif (${ni?.name ?: "interface par défaut"})"
            GatState.log("UDP prêt : OBS $OBS_GROUP:$OBS_PORT · CMD $CMD_GROUP:$CMD_PORT")
            thread = Thread({ loop(r, onCommand) }, "udp-cmd").also { it.isDaemon = true; it.start() }
        } catch (e: Exception) {
            Log.e(TAG, "start", e)
            GatState.udp.value = "erreur : ${e.message}"
            GatState.log("UDP erreur : ${e.message}")
            stop()
        }
    }

    private fun loop(r: MulticastSocket, onCommand: (JSONObject) -> Unit) {
        val buf = ByteArray(8192)
        while (running) {
            try {
                val p = DatagramPacket(buf, buf.size)
                r.receive(p)
                val o = JSONObject(String(p.data, 0, p.length, Charsets.UTF_8))
                onCommand(o)
            } catch (_: java.net.SocketTimeoutException) {
            } catch (e: org.json.JSONException) {
            } catch (e: Exception) {
                if (running) Log.w(TAG, "recv", e)
                if (!running) break
            }
        }
    }

    fun stop() {
        running = false
        try { receiver?.close() } catch (_: Exception) {}
        try { sender?.close() } catch (_: Exception) {}
        receiver = null; sender = null
        try { lock?.release() } catch (_: Exception) {}
        lock = null
        GatState.udp.value = "arrêté"
    }

    /** Envoie un message JSON compact vers un groupe (hors thread principal). */
    fun send(group: String, port: Int, obj: JSONObject) {
        val s = sender ?: return
        val data = obj.toString().toByteArray(Charsets.UTF_8)
        sendExec.execute {
            try { s.send(DatagramPacket(data, data.size, InetAddress.getByName(group), port)) }
            catch (e: Exception) { Log.w(TAG, "send", e) }
        }
    }

    /** Interface du réseau actif (Wi-Fi ou Ethernet), pour le multicast. */
    private fun pickInterface(ctx: Context): NetworkInterface? = try {
        val cm = ctx.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val name = cm.getLinkProperties(cm.activeNetwork)?.interfaceName
        if (name != null) NetworkInterface.getByName(name) else null
    } catch (_: Exception) { null }
}
