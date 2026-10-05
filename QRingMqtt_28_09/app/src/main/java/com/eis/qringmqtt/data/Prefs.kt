package com.eis.qringmqtt.data

import android.content.Context
import android.content.SharedPreferences
import android.os.Build
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
    var ringMac: String?
        get() = sp.getString("ring_mac", null)
        set(v) = sp.edit().putString("ring_mac", v).apply()

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

    private fun hash(s: String): String {
        val d = MessageDigest.getInstance("SHA-256").digest(("qring:" + s).toByteArray())
        return d.joinToString("") { "%02x".format(it) }
    }

    private fun defaultGatewayName(): String =
        com.eis.qringmqtt.mqtt.NetInfo.deviceName(context)

    companion object {
        const val DEFAULT_HOST = "51.83.40.138"
        const val DEFAULT_PORT = 1883
        const val DEFAULT_USER = "tvclient"
        const val DEFAULT_PASSWORD = "tvclient210367@Tunis"
        const val DEFAULT_PREFIX = "eis/colmi"
        const val DEFAULT_PIN = "12345"
    }
}
