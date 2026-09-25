package com.eis.qringmqtt.ble

import android.os.Handler
import android.os.Looper
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.coroutines.resume

internal val mainHandler = Handler(Looper.getMainLooper())

/**
 * Transforme un appel SDK à callback en fonction suspendue.
 * Renvoie null si la bague ne répond pas avant [timeoutMs].
 * Seule la première réponse est prise en compte.
 */
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

/** Horodatage courant en secondes. */
internal fun nowSec(): Long = System.currentTimeMillis() / 1000
