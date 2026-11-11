package com.eis.qringmqtt.service

import com.eis.qringmqtt.ble.RingManager
import com.eis.qringmqtt.data.AppState
import com.eis.qringmqtt.data.LogEntry
import com.eis.qringmqtt.mqtt.MqttManager
import org.json.JSONObject

/**
 * Réglages envoyés par l'admin sur eis/colmi/gateway/<nom>/config (message retenu) :
 *   {"pinEnabled":false, "gattMode":"ondemand", "wifiMode":"eco", "wifiWakeMin":10, "v":1731150000}
 * Ils sont GARDÉS dans l'app (Prefs) : ils restent même après un redémarrage ou sans réseau.
 * Installation neuve : connexion à la demande, sans PIN, Wi-Fi toujours actif.
 * Réponse : gateway/<nom>/configAck {"status":"ok","cfg":{…}} + statut republié (champ « cfg »).
 */
object GatewayConfig {

    fun apply(payload: String, mqtt: MqttManager?) {
        val o = try { JSONObject(payload) } catch (_: Exception) { return }
        val p = AppState.prefs
        val changes = ArrayList<String>()
        if (o.has("pinEnabled")) {
            val v = o.optBoolean("pinEnabled", p.pinEnabled)
            if (v != p.pinEnabled) { p.pinEnabled = v; changes += if (v) "PIN activé" else "PIN retiré" }
        }
        // Connexion à la bague : EN DUR « à la demande » (le réglage « gattMode » de l'admin est ignoré)
        var wifiChanged = false
        if (o.has("wifiWakeMin")) {
            val v = o.optInt("wifiWakeMin", p.wifiWakeMin).coerceIn(2, 120)
            if (v != p.wifiWakeMin) { p.wifiWakeMin = v; changes += "réveil Wi-Fi $v min" }
        }
        if (o.has("wifiMode")) {
            val v = if (o.optString("wifiMode") == "eco") "eco" else "always"
            if (v != p.wifiMode) { p.wifiMode = v; wifiChanged = true; changes += "Wi-Fi : $v" }
        }
        // Écran DM : mode, forme, nom du client
        if (o.has("dmMode")) { val v = o.optString("dmMode").takeIf { it in setOf("auto", "on", "off") } ?: "auto"
            if (v != p.dmMode) { p.dmMode = v; changes += "écran DM : $v" } }
        if (o.has("dmShape")) { val v = o.optString("dmShape").takeIf { it in setOf("auto", "round", "rect") } ?: "auto"
            if (v != p.dmShape) { p.dmShape = v; changes += "forme : $v" } }
        o.optJSONObject("dmSizes")?.let { z ->
            val v = z.toString()
            if (v != p.dmSizes) { p.dmSizes = v; com.eis.qringmqtt.dm.DmMode.sizesTick.value++; changes += "tailles écran DM" }
        }
        if (o.has("dmPopup")) { val v = o.optBoolean("dmPopup", true)
            if (v != p.dmPopup) { p.dmPopup = v; changes += if (v) "popup de mesure activé" else "popup de mesure désactivé" } }
        // Protocole MQTT : eis/colmi ou trames RHM (rhm/{client}/{site}/{gateway}/…)
        var mqttRestart = false
        if (o.has("protocol")) { val v = if (o.optString("protocol") == "rhm") "rhm" else "eis"
            if (v != p.protocol) { p.protocol = v; mqttRestart = true; changes += "protocole MQTT : $v" } }
        if (o.has("rhmClient")) { val v = o.optString("rhmClient").trim().ifBlank { "C001" }
            if (v != p.rhmClient) { p.rhmClient = v; mqttRestart = true; changes += "client RHM : $v" } }
        if (o.has("rhmSite")) { val v = o.optString("rhmSite").trim().ifBlank { "S001" }
            if (v != p.rhmSite) { p.rhmSite = v; mqttRestart = true; changes += "site RHM : $v" } }
        if (o.has("clientName")) { val v = o.optString("clientName").trim()
            if (v != p.clientName) { p.clientName = v; changes += "client : $v" } }
        // Bagues autorisées pour cette gateway (liste « Changer de bague »)
        o.optJSONArray("rings")?.let { arr ->
            val s = arr.toString()
            if (s != p.allowedRingsJson) { p.allowedRingsJson = s; changes += "${arr.length()} bague(s) autorisée(s)" }
        }
        if (changes.isNotEmpty()) AppState.log(LogEntry.Kind.INFO, "admin", "Réglages reçus : " + changes.joinToString(", "))
        mqtt?.publish("configAck", JSONObject().put("status", "ok").put("cfg", json())
            .put("v", o.opt("v") ?: JSONObject.NULL).put("gateway", p.gatewayName)
            .put("ts", System.currentTimeMillis() / 1000), LogEntry.Kind.OUT, viaGateway = true)
        if (wifiChanged) WifiSaver.apply()
        if (mqttRestart) mqtt?.restart()
        mqtt?.publishStatusNow(true)
    }

    /** Réglages en vigueur (dans chaque statut → l'admin voit ce qui est appliqué). */
    fun json(): JSONObject {
        val p = AppState.prefs
        return JSONObject()
            .put("pinEnabled", p.pinEnabled)
            .put("gattMode", "ondemand")
            .put("wifiMode", p.wifiMode)
            .put("wifiWakeMin", p.wifiWakeMin)
            .put("net", WifiSaver.netType())
            .put("dmMode", p.dmMode).put("dmShape", p.dmShape).put("clientName", p.clientName).put("dmPopup", p.dmPopup)
            .put("protocol", p.protocol).put("rhmClient", p.rhmClient).put("rhmSite", p.rhmSite)
            .put("dmSizes", try { org.json.JSONObject(p.dmSizes) } catch (_: Exception) { org.json.JSONObject() })
            .put("dmActive", com.eis.qringmqtt.dm.DmMode.active).put("dmModel", com.eis.qringmqtt.dm.DmMode.model())
            .put("released", com.eis.qringmqtt.ble.RingManager.lastReleased ?: org.json.JSONObject.NULL)
            .put("releaseFault", com.eis.qringmqtt.ble.RingManager.releaseFault)
    }
}
