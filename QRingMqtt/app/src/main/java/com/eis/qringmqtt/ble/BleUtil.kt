package com.eis.qringmqtt.ble

import android.os.Handler
import android.os.Looper
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.withTimeoutOrNull
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.coroutines.resume

internal val mainHandler = Handler(Looper.getMainLooper())

/** Une seule commande Bluetooth à la fois : mesures, mise à l'heure, versions, batterie (file de commandes). */
internal val bleMutex = Mutex()

/**
 * Bague « connectée mais muette » : 3 commandes sans réponse de suite → déconnexion propre,
 * le SDK se reconnecte (RingManager.onMute). Seules les commandes simples comptent (heure, batterie).
 */
internal object BleHealth {
    @Volatile var missed = 0
    fun ok() { missed = 0 }
    fun miss() {
        missed++
        if (missed >= 3) {
            missed = 0
            mainHandler.post { RingManager.onMute() }
        }
    }
}

/**
 * Transforme un appel SDK à callback en fonction suspendue.
 * Renvoie null si la bague ne répond pas avant [timeoutMs].
 * Seule la première réponse est prise en compte.
 */
internal suspend fun <T> awaitCallback(timeoutMs: Long, health: Boolean = false,
                                       block: (resume: (T) -> Unit) -> Unit): T? {
    val r = withTimeoutOrNull(timeoutMs) {
        suspendCancellableCoroutine<T?> { cont ->
            val done = AtomicBoolean(false)
            try {
                block { v -> if (done.compareAndSet(false, true) && cont.isActive) cont.resume(v) }
            } catch (e: Exception) {
                if (done.compareAndSet(false, true) && cont.isActive) cont.resume(null)
            }
        }
    }
    if (health) {
        if (r == null) BleHealth.miss() else BleHealth.ok()
        Diag.command(r != null)
    }
    return r
}

/** Horodatage courant en secondes. */
internal fun nowSec(): Long = System.currentTimeMillis() / 1000
