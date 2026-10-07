package com.eis.gatandroid

import android.content.Context
import android.content.SharedPreferences
import android.os.Build
import android.os.Handler
import android.os.Looper
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.coroutines.resume

internal val mainHandler = Handler(Looper.getMainLooper())

/** Transforme un appel SDK à callback en fonction suspendue (null si pas de réponse à temps). */
internal suspend fun <T> awaitCallback(timeoutMs: Long, block: (resume: (T) -> Unit) -> Unit): T? =
    withTimeoutOrNull(timeoutMs) {
        suspendCancellableCoroutine { cont ->
            val done = AtomicBoolean(false)
            try {
                block { v -> if (done.compareAndSet(false, true) && cont.isActive) cont.resume(v) }
            } catch (e: Exception) {
                if (done.compareAndSet(false, true) && cont.isActive) cont.resume(null as T)
            }
        }
    }

/** "30:32:42:32:64:01" / "303242326401" / "30-32-…" → "30:32:42:32:64:01" (sinon texte en majuscules). */
fun normMac(s: String): String {
    val hex = s.filter { it.isLetterOrDigit() }.uppercase()
    return if (hex.length == 12 && hex.all { it in '0'..'9' || it in 'A'..'F' }) hex.chunked(2).joinToString(":")
    else s.trim().uppercase()
}

private val isoFmt = ThreadLocal.withInitial { SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSSXXX", Locale.US) }

/** Heure ISO locale avec fuseau, comme le script Python (now_iso). */
fun nowIso(ms: Long = System.currentTimeMillis()): String = isoFmt.get()!!.format(Date(ms))

fun hhmmss(ms: Long = System.currentTimeMillis()): String =
    SimpleDateFormat("HH:mm:ss", Locale.US).format(Date(ms))

/** Réglages enregistrés. */
object Prefs {
    private lateinit var sp: SharedPreferences
    fun init(c: Context) { sp = c.getSharedPreferences("gat", Context.MODE_PRIVATE) }

    var gateway: String
        get() = sp.getString("gw", null)?.takeIf { it.isNotBlank() }
            ?: ("GW_ANDROID_" + Build.MODEL.replace(Regex("[^A-Za-z0-9]"), ""))
        set(v) { sp.edit().putString("gw", v.trim()).apply() }

    var zone: String
        get() = sp.getString("zone", "") ?: ""
        set(v) { sp.edit().putString("zone", v.trim()).apply() }

    /** Bagues surveillées (MAC normalisées). */
    var rings: List<String>
        get() = (sp.getString("rings", "") ?: "").split(",").map { it.trim() }.filter { it.isNotEmpty() }
        set(v) { sp.edit().putString("rings", v.map { normMac(it) }.distinct().joinToString(",")).apply() }

    /** Le service doit tourner (relancé au démarrage de l'appareil). */
    var running: Boolean
        get() = sp.getBoolean("running", false)
        set(v) { sp.edit().putBoolean("running", v).apply() }
}

data class SeenRing(val mac: String, val name: String?, val rssi: Int, val lastMs: Long)

data class GattInfo(
    val state: String = "PRÊT",
    val req: String? = null,
    val ring: String? = null,
    val value: Int? = null,
    val battery: Int? = null,
    val charging: Boolean? = null,
    val detail: String = "",
    val atMs: Long = 0
)

/** État partagé entre le service et l'écran. */
object GatState {
    val running = MutableStateFlow(false)
    val udp = MutableStateFlow("arrêté")
    val seen = MutableStateFlow<List<SeenRing>>(emptyList())
    val gatt = MutableStateFlow(GattInfo())
    val log = MutableStateFlow<List<String>>(emptyList())
    val obsSent = MutableStateFlow(0)
    val lastScanOrder = MutableStateFlow("—")

    fun log(msg: String) {
        log.update { (listOf("${hhmmss()}  $msg") + it).take(40) }
    }
}
