package com.eis.qringmqtt.mqtt

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.provider.Settings
import android.util.Log
import com.eis.qringmqtt.data.AppState
import com.eis.qringmqtt.data.BrokerConn
import com.eis.qringmqtt.data.LogEntry
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.eclipse.paho.client.mqttv3.IMqttActionListener
import org.eclipse.paho.client.mqttv3.IMqttDeliveryToken
import org.eclipse.paho.client.mqttv3.IMqttToken
import org.eclipse.paho.client.mqttv3.MqttAsyncClient
import org.eclipse.paho.client.mqttv3.MqttCallbackExtended
import org.eclipse.paho.client.mqttv3.MqttConnectOptions
import org.eclipse.paho.client.mqttv3.MqttMessage
import org.eclipse.paho.client.mqttv3.persist.MemoryPersistence
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * Connexion persistante au broker MQTT.
 * - reconnexion automatique (délai croissant + retour du réseau)
 * - « Last Will » : le broker publie {"online":false} si le gateway disparaît
 * - file d'attente : les résultats publiés hors ligne sont envoyés au retour du réseau
 */
class MqttManager(
    private val context: Context,
    /** (payload, reçu sur le topic du gateway ?) */
    private val onCommand: (String, Boolean) -> Unit,
    private val statusPayload: (online: Boolean) -> JSONObject,
    private val onConnected: () -> Unit
) {
    private val tag = "MqttManager"
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var client: MqttAsyncClient? = null
    private var retryJob: Job? = null
    private var retryCount = 0
    private var stopped = false

    /** Base des topics utilisée par la connexion actuelle (le Last Will en dépend). */
    private var connectedBase: String? = null
    private var connectedGateway: String? = null

    private val queueFile = File(context.filesDir, "mqtt_queue.json")
    private val queue = ArrayList<Pair<String, String>>()

    private val clientId: String by lazy {
        val id = Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID) ?: "x"
        "qring-$id"
    }

    // ------------------------------------------------------------------ topics

    /** eis/colmi/gateway/{nom-de-la-TV} : toujours écouté (bind, unbind, scan, lang, ping). */
    fun gatewayBase(): String {
        val p = AppState.prefs
        return "${p.topicPrefix}/gateway/${NetInfo.topicSafe(p.gatewayName)}"
    }

    /** eis/colmi/{MAC-bague} ou null si aucune bague associée. */
    fun ringBase(): String? {
        val p = AppState.prefs
        val mac = p.ringMac ?: return null
        return "${p.topicPrefix}/${macForTopic(mac)}"
    }

    /** Base des résultats : la bague si associée, sinon le gateway. */
    fun baseTopic(): String = ringBase() ?: gatewayBase()

    fun isConnected(): Boolean = client?.isConnected == true

    // ------------------------------------------------------------------ connexion

    fun start() {
        stopped = false
        loadQueue()
        registerNetworkCallback()
        connect()
    }

    fun stop() {
        stopped = true
        retryJob?.cancel()
        publishStatusNow(false)
        scope.launch {
            delay(500)
            try { client?.disconnect(1000) } catch (_: Exception) {}
            try { client?.close() } catch (_: Exception) {}
            client = null
        }
        unregisterNetworkCallback()
        AppState.broker.value = BrokerConn.OFFLINE
    }

    /** À appeler quand la bague associée change ou quand les réglages changent. */
    fun restart(oldBase: String? = null) {
        if (oldBase != null && isConnected()) {
            // L'ancienne bague passe hors ligne avant de changer de topic
            val off = statusPayload(false).put("reason", "ring_changed")
            publishRaw("$oldBase/status", off.toString(), retained = true, queueIfOffline = false)
        }
        scope.launch {
            delay(400)
            try { client?.disconnectForcibly(500, 500) } catch (_: Exception) {}
            try { client?.close() } catch (_: Exception) {}
            client = null
            retryCount = 0
            connect()
        }
    }

    private fun connect() {
        if (stopped) return
        if (client?.isConnected == true) return
        retryJob?.cancel()
        val p = AppState.prefs
        val base = baseTopic()
        val gw = gatewayBase()
        AppState.broker.value = BrokerConn.CONNECTING
        try {
            val uri = "tcp://${p.host}:${p.port}"
            val c = client ?: MqttAsyncClient(uri, clientId, MemoryPersistence()).also { client = it }
            c.setCallback(callback)
            val opts = MqttConnectOptions().apply {
                isCleanSession = false          // session persistante : commandes QoS 1 conservées
                isAutomaticReconnect = false    // on gère la reconnexion nous-mêmes
                keepAliveInterval = 30
                connectionTimeout = 15
                userName = p.user
                password = p.password.toCharArray()
                setWill("$base/status", statusPayload(false).toString().toByteArray(), 1, true)
            }
            c.connect(opts, null, object : IMqttActionListener {
                override fun onSuccess(asyncActionToken: IMqttToken?) {
                    scope.launch { onConnectedInternal(base, gw) }
                }

                override fun onFailure(asyncActionToken: IMqttToken?, exception: Throwable?) {
                    Log.w(tag, "connexion échouée", exception)
                    scope.launch {
                        AppState.log(LogEntry.Kind.ERROR, "broker", "Connexion impossible : ${exception?.message ?: "?"}")
                        scheduleRetry()
                    }
                }
            })
        } catch (e: Exception) {
            Log.e(tag, "connect", e)
            scheduleRetry()
        }
    }

    private fun onConnectedInternal(base: String, gw: String) {
        retryCount = 0
        connectedBase = base
        connectedGateway = gw
        AppState.broker.value = BrokerConn.ONLINE
        AppState.log(LogEntry.Kind.INFO, "broker", "OK ${AppState.prefs.host} · $gw")
        try {
            client?.subscribe("$gw/cmd", 1)
            if (base != gw) {
                client?.subscribe("$base/cmd", 1)
                // Nom donné dans l'admin (message retenu) : arrive tout de suite après l'abonnement
                client?.subscribe("$base/profile", 1)
            }
        } catch (e: Exception) {
            Log.e(tag, "subscribe", e)
        }
        publishStatusNow(true)
        flushQueue()
        onConnected()
    }

    private fun scheduleRetry() {
        if (stopped) return
        AppState.broker.value = BrokerConn.OFFLINE
        retryJob?.cancel()
        val wait = when (retryCount++) { 0 -> 3L; 1 -> 5L; 2 -> 10L; 3 -> 30L; else -> 60L }
        retryJob = scope.launch {
            delay(wait * 1000)
            connect()
        }
    }

    private val callback = object : MqttCallbackExtended {
        override fun connectComplete(reconnect: Boolean, serverURI: String?) {}

        override fun connectionLost(cause: Throwable?) {
            scope.launch {
                AppState.log(LogEntry.Kind.ERROR, "broker", "Connexion perdue : ${cause?.message ?: "?"}")
                scheduleRetry()
            }
        }

        override fun messageArrived(topic: String?, message: MqttMessage?) {
            val payload = message?.payload?.let { String(it, Charsets.UTF_8) } ?: return
            scope.launch {
                AppState.log(LogEntry.Kind.IN, topic ?: "", payload)
                if (topic != null && topic.endsWith("/profile")) {
                    onProfile(payload)
                    return@launch
                }
                val gw = connectedGateway
                onCommand(payload, gw != null && topic != null && topic.startsWith("$gw/"))
            }
        }

        override fun deliveryComplete(token: IMqttDeliveryToken?) {}
    }

    // ------------------------------------------------------------------ réseau

    private var netCallback: ConnectivityManager.NetworkCallback? = null

    private fun registerNetworkCallback() {
        if (netCallback != null) return
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager ?: return
        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                // Le réseau revient : on se reconnecte tout de suite
                scope.launch {
                    if (!isConnected()) {
                        retryCount = 0
                        delay(1000)
                        connect()
                    }
                    // Nouveau réseau : l'IP LAN / WAN a pu changer
                    delay(3000)
                    NetInfo.refreshWan(force = true)
                    if (isConnected()) publishStatusNow(true)
                }
            }
        }
        try {
            cm.registerDefaultNetworkCallback(cb)
            netCallback = cb
        } catch (_: Exception) {
        }
    }

    private fun unregisterNetworkCallback() {
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager ?: return
        netCallback?.let { try { cm.unregisterNetworkCallback(it) } catch (_: Exception) {} }
        netCallback = null
    }

    // ------------------------------------------------------------------ publication

    /** Statut publié sur le topic de la bague ET sur celui du gateway (retenu). */
    fun publishStatusNow(online: Boolean) {
        val payload = statusPayload(online).toString()
        val base = connectedBase ?: baseTopic()
        val gw = connectedGateway ?: gatewayBase()
        publishRaw("$base/status", payload, retained = true, queueIfOffline = false)
        if (gw != base) publishRaw("$gw/status", payload, retained = true, queueIfOffline = false)
    }

    /** Profil de la bague envoyé par l'admin : {"name":"Mme Martin"} (vide = pas de nom). */
    private fun onProfile(payload: String) {
        val name = try { JSONObject(payload).optString("name", "").trim() } catch (_: Exception) { "" }
        AppState.prefs.ringLabel = name
        AppState.ringLabel.value = name
    }

    /** Publie un message « hors ligne » sur l'ancien topic d'une bague (dissociée ou remplacée). */
    fun publishRingOffline(oldMac: String, reason: String) {
        val topic = "${AppState.prefs.topicPrefix}/${macForTopic(oldMac)}/status"
        val o = statusPayload(false).put("ring", "unbound").put("reason", reason)
            .put("ringMac", oldMac).put("unboundAt", System.currentTimeMillis() / 1000)
            .put("boundAt", JSONObject.NULL).put("removedAt", JSONObject.NULL)
        publishRaw(topic, o.toString(), retained = true, queueIfOffline = true)
    }

    /** Publie sur {base}/{sub}. Si hors ligne, le message est gardé et envoyé plus tard. */
    fun publish(sub: String, json: JSONObject, kind: LogEntry.Kind, viaGateway: Boolean = false) {
        val base = if (viaGateway) (connectedGateway ?: gatewayBase()) else (connectedBase ?: baseTopic())
        val topic = "$base/$sub"
        val payload = json.toString()
        AppState.log(kind, topic, payload)
        publishRaw(topic, payload, retained = false, queueIfOffline = true)
    }

    private fun publishRaw(topic: String, payload: String, retained: Boolean, queueIfOffline: Boolean) {
        val c = client
        if (c != null && c.isConnected) {
            try {
                c.publish(topic, payload.toByteArray(Charsets.UTF_8), 1, retained)
                return
            } catch (e: Exception) {
                Log.w(tag, "publish", e)
            }
        }
        if (queueIfOffline) {
            queue += topic to payload
            while (queue.size > 500) queue.removeAt(0)
            saveQueue()
        }
    }

    private fun flushQueue() {
        if (queue.isEmpty()) return
        val items = ArrayList(queue)
        queue.clear()
        saveQueue()
        items.forEach { (t, p) -> publishRaw(t, p, retained = false, queueIfOffline = true) }
    }

    private fun loadQueue() {
        try {
            if (!queueFile.exists()) return
            val arr = JSONArray(queueFile.readText())
            queue.clear()
            for (i in 0 until arr.length()) {
                val o = arr.getJSONObject(i)
                queue += o.getString("t") to o.getString("p")
            }
        } catch (_: Exception) {
        }
        AppState.pendingPublish.value = queue.size
    }

    private fun saveQueue() {
        try {
            val arr = JSONArray()
            queue.forEach { (t, p) -> arr.put(JSONObject().put("t", t).put("p", p)) }
            queueFile.writeText(arr.toString())
        } catch (_: Exception) {
        }
        AppState.pendingPublish.value = queue.size
    }

    companion object {
        /** "C4:A1:5F:22:A4:F1" → "C4A15F22A4F1" */
        fun macForTopic(mac: String) = mac.replace(":", "").replace("-", "").uppercase()
    }
}
