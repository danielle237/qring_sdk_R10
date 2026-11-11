package com.eis.qringmqtt.data

import android.content.Context
import android.content.SharedPreferences
import android.os.Build
import android.provider.Settings
import java.security.MessageDigest

/** Réglages persistants de l'application. */
class Prefs(private val context: Context) {

    private val sp: SharedPreferences =
        context.getSharedPreferences("qring_mqtt", Context.MODE_PRIVATE)

    // ---------- Broker MQTT ----------
    var host: String
        get() = sp.getString("host", DEFAULT_HOST)!!
        set(v) = sp.edit().putString("host", v.trim()).apply()

    var port: Int
        get() = sp.getInt("port", DEFAULT_PORT)
        set(v) = sp.edit().putInt("port", v).apply()

    var user: String
        get() = sp.getString("user", DEFAULT_USER)!!
        set(v) = sp.edit().putString("user", v).apply()

    var password: String
        get() = sp.getString("password", DEFAULT_PASSWORD)!!
        set(v) = sp.edit().putString("password", v).apply()

    /** Préfixe des topics, sans / final. Ex. "eis/colmi". */
    var topicPrefix: String
        get() = sp.getString("prefix", DEFAULT_PREFIX)!!
        set(v) = sp.edit().putString("prefix", v.trim().trim('/')).apply()

    /** Nom du gateway = nom de la TV (modifiable). Doit être unique. */
    var gatewayName: String
        get() = sp.getString("gateway", null)?.takeIf { it.isNotBlank() } ?: defaultGatewayName()
        set(v) = sp.edit().putString("gateway", v.trim()).apply()

    // ---------- Bague ----------
    /** Nouvelle bague associée → heure d'association ; dissociée → heures remises à zéro. */
    var ringMac: String?
        get() = sp.getString("ring_mac", null)
        set(v) {
            val old = sp.getString("ring_mac", null)
            val e = sp.edit().putString("ring_mac", v)
            if (v == null) e.putLong("bound_at", 0).putLong("removed_at", 0).remove("ring_label")
            else if (!v.equals(old, ignoreCase = true))
                e.putLong("bound_at", nowSec()).putLong("removed_at", 0).remove("ring_label")
            e.apply()
        }

    /** Heure (s) de l'association de la bague à cette Gateway RHM, 0 si inconnue. */
    val boundAt: Long
        get() = sp.getLong("bound_at", 0)

    /** Nom donné dans l'admin (base de données), ex. « Mme Martin » — reçu par MQTT (topic …/profile). */
    var ringLabel: String
        get() = sp.getString("ring_label", "") ?: ""
        set(v) = sp.edit().putString("ring_label", v).apply()

    /** Date (yyyy-MM-dd) de la dernière synchronisation automatique du sommeil. */
    var lastSleepSync: String
        get() = sp.getString("last_sleep_sync", "") ?: ""
        set(v) = sp.edit().putString("last_sleep_sync", v).apply()

    /** Heure (s) du retrait de la bague, 0 si portée ou inconnue. */
    var removedAt: Long
        get() = sp.getLong("removed_at", 0)
        set(v) = sp.edit().putLong("removed_at", v).apply()

    private fun nowSec() = System.currentTimeMillis() / 1000

    var ringName: String?
        get() = sp.getString("ring_name", null)
        set(v) = sp.edit().putString("ring_name", v).apply()

    var firmware: String?
        get() = sp.getString("fw", null)
        set(v) = sp.edit().putString("fw", v).apply()

    var hardware: String?
        get() = sp.getString("hw", null)
        set(v) = sp.edit().putString("hw", v).apply()

    // ---------- Langue (fr, en, ar) ----------
    var lang: String
        get() = sp.getString("lang", "fr")!!
        set(v) = sp.edit().putString("lang", v).apply()

    // ---------- Divers ----------
    var onboardingDone: Boolean
        get() = sp.getBoolean("onboarding_done", false)
        set(v) = sp.edit().putBoolean("onboarding_done", v).apply()

    // ---------- Code PIN (stocké haché) ----------
    fun checkPin(pin: String): Boolean =
        hash(pin) == (sp.getString("pin_hash", null) ?: hash(DEFAULT_PIN))

    fun setPin(pin: String) = sp.edit().putString("pin_hash", hash(pin)).apply()

    /** Nouveau PIN envoyé par l'admin, déjà haché (SHA-256 de « qring:<pin> »). */
    fun setPinHash(h: String) {
        val v = h.trim().lowercase()
        if (v.length == 64 && v.all { it in "0123456789abcdef" }) sp.edit().putString("pin_hash", v).apply()
    }

    // ---------- Réglages envoyés par l'admin (topic gateway/<nom>/config, retenu) ----------
    /** false = Journal, Scanner et Réglages s'ouvrent sans code PIN. */
    var pinEnabled: Boolean
        get() = sp.getBoolean("pin_enabled", false)   // installation : sans PIN
        set(v) = sp.edit().putBoolean("pin_enabled", v).apply()

    /** « permanent » (la bague reste connectée) ou « ondemand » (connectée pour une mesure puis lâchée). */
    var gattMode: String
        get() = sp.getString("gatt_mode", "ondemand") ?: "ondemand"   // installation : à la demande
        set(v) = sp.edit().putString("gatt_mode", v).apply()

    /** « always » (Wi-Fi toujours actif) ou « eco » (Wi-Fi coupé, rallumé pour envoyer + réveil périodique). */
    var wifiMode: String
        get() = sp.getString("wifi_mode", "always") ?: "always"
        set(v) = sp.edit().putString("wifi_mode", v).apply()

    // ---------- Écran DM (DM100 / DM80), réglé depuis l'admin ----------
    /** « auto » (modèle DM détecté), « on » (toujours l'écran DM), « off » (écran normal). */
    var dmMode: String
        get() = sp.getString("dm_mode", "auto") ?: "auto"
        set(v) = sp.edit().putString("dm_mode", v).apply()

    /** « auto », « round » (DM80) ou « rect » (DM100). */
    var dmShape: String
        get() = sp.getString("dm_shape", "auto") ?: "auto"
        set(v) = sp.edit().putString("dm_shape", v).apply()

    // ---------- Protocole MQTT (admin) ----------
    /** « eis » (eis/colmi, actuel) ou « rhm » (trames rhm/{client}/{site}/{gateway}/…, CC du 10/11/2026). */
    var protocol: String
        get() = sp.getString("protocol", "rhm") ?: "rhm"   // gateways Android : trames RHM par défaut
        set(v) = sp.edit().putString("protocol", v).apply()

    /** Client affecté par provisioning (set_site) ou saisi manuellement dans l'admin. Vide = non affecté :
     *  aucune donnée patient publiée (doc provisioning Android du 10/11/2026 -- avant "C001" en dur). */
    var rhmClient: String
        get() = sp.getString("rhm_client", "") ?: ""
        set(v) = sp.edit().putString("rhm_client", v.trim()).apply()

    /** Site affecté par provisioning (set_site) ou saisi manuellement dans l'admin. Vide = non affecté. */
    var rhmSite: String
        get() = sp.getString("rhm_site", "") ?: ""
        set(v) = sp.edit().putString("rhm_site", v.trim()).apply()

    /** Révision du reçu de provisioning (rhm/provision/android/<device_id>/state, §3.1 du doc du
     *  10/11/2026 "APK Android RHM -- réception des commandes et réponses MQTT"). Repris le 10/11/2026
     *  pour la structure du reçu READY ; la machine prepare/commit/finalize n'étant pas implémentée
     *  (signature HMAC non disponible), rien n'incrémente cette valeur aujourd'hui -- elle reste 0. */
    var provisionRevision: Int
        get() = sp.getInt("provision_revision", 0)
        set(v) = sp.edit().putInt("provision_revision", v).apply()

    /** Identifiant permanent (32 hex minuscules) pour le canal rhm/provision/android/<device_id>/...
     *  (doc "APK Android RHM" du 10/11/2026, §2). Généré une seule fois depuis ANDROID_ID puis conservé.
     *  Ce n'est PAS un identifiant déjà enrôlé dans un registre EIS réel : rien ne garantit qu'un
     *  serveur l'associe à une clé HMAC aujourd'hui. */
    val provisionDeviceId: String
        get() {
            sp.getString("provision_device_id", null)?.let { return it }
            val androidId = Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID) ?: "unknown"
            val id32 = sha256Hex("device:$androidId").substring(0, 32)
            sp.edit().putString("provision_device_id", id32).apply()
            return id32
        }

    /** Écran DM : popup de mesure (connexion → mesure → déconnexion → résultat), désactivable par l'admin. */
    var dmPopup: Boolean
        get() = sp.getBoolean("dm_popup", true)
        set(v) = sp.edit().putBoolean("dm_popup", v).apply()

    /** Tailles des textes de l'écran DM, en % (admin) : {"header","title","value","unit","status"}. */
    var dmSizes: String
        get() = sp.getString("dm_sizes", "{}") ?: "{}"
        set(v) = sp.edit().putString("dm_sizes", v).apply()

    /** Client / établissement affiché sur l'écran DM (configuration de l'admin). */
    var clientName: String
        get() = sp.getString("client_name", "") ?: ""
        set(v) = sp.edit().putString("client_name", v.trim()).apply()

    // ---------- Bagues proposées par « Changer de bague » ----------
    /** Bagues déjà utilisées sur cette gateway : JSON [{"mac","name","ts"}] (20 dernières). */
    var usedRingsJson: String
        get() = sp.getString("used_rings", "[]") ?: "[]"
        set(v) = sp.edit().putString("used_rings", v).apply()

    /** Bagues autorisées par l'admin : JSON [{"mac","name","label"}] (gardé dans l'app). */
    var allowedRingsJson: String
        get() = sp.getString("allowed_rings", "[]") ?: "[]"
        set(v) = sp.edit().putString("allowed_rings", v).apply()

    fun rememberUsedRing(mac: String, name: String) {
        val arr = try { org.json.JSONArray(usedRingsJson) } catch (_: Exception) { org.json.JSONArray() }
        val out = org.json.JSONArray()
        out.put(org.json.JSONObject().put("mac", mac.uppercase()).put("name", name).put("ts", nowSec()))
        for (i in 0 until arr.length()) {
            val o = arr.optJSONObject(i) ?: continue
            if (!o.optString("mac").equals(mac, ignoreCase = true) && out.length() < 20) out.put(o)
        }
        usedRingsJson = out.toString()
    }

    /** Mode Wi-Fi économie : réveil toutes les N minutes pour envoyer le statut et lire les ordres. */
    var wifiWakeMin: Int
        get() = sp.getInt("wifi_wake_min", 10)
        set(v) = sp.edit().putInt("wifi_wake_min", v.coerceIn(2, 120)).apply()

    private fun hash(s: String): String {
        val d = MessageDigest.getInstance("SHA-256").digest(("qring:" + s).toByteArray())
        return d.joinToString("") { "%02x".format(it) }
    }

    private fun sha256Hex(s: String): String {
        val d = MessageDigest.getInstance("SHA-256").digest(s.toByteArray(Charsets.UTF_8))
        return d.joinToString("") { "%02x".format(it) }
    }

    /** Nom par défaut : le modèle sur les montres (« DM100 », « DM80 »), sinon le nom de l'appareil. */
    private fun defaultGatewayName(): String =
        com.eis.qringmqtt.dm.DmMode.model().ifBlank { com.eis.qringmqtt.mqtt.NetInfo.deviceName(context) }

    companion object {
        const val DEFAULT_HOST = "51.83.40.138"
        const val DEFAULT_PORT = 1883
        const val DEFAULT_USER = "tvclient"
        const val DEFAULT_PASSWORD = "tvclient210367@Tunis"
        const val DEFAULT_PREFIX = "rhm_admin_test"
        const val DEFAULT_PIN = "12345"
    }
}
