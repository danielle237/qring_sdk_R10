package com.eis.qringmqtt.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.focusable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.eis.qringmqtt.data.AppState
import com.eis.qringmqtt.data.tr
import kotlinx.coroutines.delay

/** Déverrouillage partagé par Journal et Réglages (valable 5 minutes). */
object PinLock {
    var unlockedUntil by mutableLongStateOf(0L)
    var failed by mutableIntStateOf(0)
    var blockedUntil by mutableLongStateOf(0L)

    val isUnlocked: Boolean get() = System.currentTimeMillis() < unlockedUntil
    fun lock() { unlockedUntil = 0L }
    fun touch() { if (isUnlocked) unlockedUntil = System.currentTimeMillis() + 5 * 60_000 }
}

/**
 * Affiche [content] seulement après saisie du bon code PIN.
 * Rien de la page n'est visible avant.
 */
@Composable
fun PinGate(title: String, content: @Composable () -> Unit) {
    var tick by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) { while (true) { delay(1000); tick = System.currentTimeMillis() } }
    if (tick < PinLock.unlockedUntil) {
        content()
    } else {
        PinPad(title, tick)
    }
}

@Composable
private fun PinPad(title: String, now: Long) {
    var pin by remember { mutableStateOf("") }
    var wrong by remember { mutableStateOf(false) }
    val blocked = now < PinLock.blockedUntil
    val focus = remember { FocusRequester() }

    fun submit() {
        if (blocked || pin.isEmpty()) return
        if (AppState.prefs.checkPin(pin)) {
            PinLock.failed = 0
            PinLock.unlockedUntil = System.currentTimeMillis() + 5 * 60_000
        } else {
            PinLock.failed++
            wrong = true
            if (PinLock.failed >= 5) {
                PinLock.blockedUntil = System.currentTimeMillis() + 5 * 60_000
                PinLock.failed = 0
            }
        }
        pin = ""
    }

    fun press(k: String) {
        if (blocked) return
        wrong = false
        when (k) {
            "⌫" -> pin = pin.dropLast(1)
            "OK" -> submit()
            else -> if (pin.length < 8) pin += k
        }
    }

    LaunchedEffect(Unit) { try { focus.requestFocus() } catch (_: Exception) {} }

    Box(
        Modifier
            .fillMaxSize()
            // Touches chiffres de la télécommande / clavier
            .onPreviewKeyEvent { ev ->
                if (ev.type != KeyEventType.KeyDown) return@onPreviewKeyEvent false
                val digit = when (ev.key) {
                    Key.Zero, Key.NumPad0 -> "0"; Key.One, Key.NumPad1 -> "1"; Key.Two, Key.NumPad2 -> "2"
                    Key.Three, Key.NumPad3 -> "3"; Key.Four, Key.NumPad4 -> "4"; Key.Five, Key.NumPad5 -> "5"
                    Key.Six, Key.NumPad6 -> "6"; Key.Seven, Key.NumPad7 -> "7"; Key.Eight, Key.NumPad8 -> "8"
                    Key.Nine, Key.NumPad9 -> "9"; Key.Backspace, Key.Delete -> "⌫"
                    else -> null
                }
                if (digit != null) { press(digit); true } else false
            },
        contentAlignment = Alignment.Center
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Icon(Icons.Filled.Lock, null, tint = C.accent, modifier = Modifier.size(36.dp))
            Spacer(Modifier.height(8.dp))
            Text(title, color = C.text, fontSize = 18.sp, fontWeight = FontWeight.Bold)
            Text(
                when {
                    blocked -> tr("pin.blocked", (PinLock.blockedUntil - now) / 1000 + 1)
                    wrong -> tr("pin.wrong")
                    else -> tr("pin.enter")
                },
                color = if (blocked || wrong) C.err else C.muted, fontSize = 13.sp
            )
            Spacer(Modifier.height(14.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                repeat(5.coerceAtLeast(pin.length)) { i ->
                    Box(Modifier.size(14.dp).clip(CircleShape).background(if (i < pin.length) C.accent else C.line))
                }
            }
            Spacer(Modifier.height(18.dp))
            val rows = listOf(listOf("1", "2", "3"), listOf("4", "5", "6"), listOf("7", "8", "9"), listOf("⌫", "0", "OK"))
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                rows.forEachIndexed { ri, row ->
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        row.forEachIndexed { ci, k ->
                            val first = ri == 0 && ci == 0
                            Box(
                                Modifier
                                    .size(64.dp)
                                    .then(if (first) Modifier.focusRequester(focus) else Modifier)
                                    .focusClick(RoundedCornerShape(16.dp)) { press(k) }
                                    .background(if (k == "OK") C.accent else C.card),
                                contentAlignment = Alignment.Center
                            ) {
                                Text(k, color = C.text, fontSize = if (k == "OK") 16.sp else 22.sp, fontWeight = FontWeight.Bold)
                            }
                        }
                    }
                }
            }
        }
    }
}
