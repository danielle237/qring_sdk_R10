package com.eis.qringmqtt.dm

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.eis.qringmqtt.ble.RingManager
import com.eis.qringmqtt.data.AppState
import com.eis.qringmqtt.data.Cmd
import com.eis.qringmqtt.data.Err
import com.eis.qringmqtt.data.tr
import com.eis.qringmqtt.service.CommandProcessor
import kotlinx.coroutines.delay
import java.util.Locale

private val PANEL = Color(0xF20D1426)
private val TXT = Color(0xFFF4F6FC)
private val MUTED = Color(0xFF9AA3BF)
private val OK = Color(0xFF3ECF8E)
private val ERR = Color(0xFFFF6B6B)

private fun tintOf(c: Cmd): Color = when (c) {
    Cmd.HR -> Color(0xFFFF5D73); Cmd.SPO2 -> Color(0xFF29B6F6); Cmd.HRV -> Color(0xFF2EE59D)
    Cmd.TEMP -> Color(0xFFFFA726); else -> Color(0xFF6C8CFF)
}

private fun titleOf(c: Cmd): String = when (c) {
    Cmd.HR -> "HR"; Cmd.SPO2 -> "SpO₂"; Cmd.HRV -> "HRV"; Cmd.TEMP -> "Temp"; Cmd.ALL -> "HR + SpO₂ + Temp + HRV"
    else -> c.label
}

/** Valeur(s) d'un résultat : « 84 bpm », « 36.6 °C », ALL → plusieurs lignes. */
private fun resultLines(c: Cmd, v: org.json.JSONObject?): List<String> {
    if (v == null) return emptyList()
    fun one(key: String, unit: String, temp: Boolean = false): String? =
        if (!v.has(key)) null else if (temp) String.format(Locale.ROOT, "%.1f %s", v.optDouble(key), unit) else "${v.optInt(key)} $unit"
    return when (c) {
        Cmd.HR -> listOfNotNull(one("value", "bpm"))
        Cmd.SPO2 -> listOfNotNull(one("value", "%"))
        Cmd.HRV -> listOfNotNull(one("value", "ms"))
        Cmd.TEMP -> listOfNotNull(one("value", "°C", true))
        Cmd.ALL -> listOfNotNull(one("hr", "bpm")?.let { "HR $it" }, one("spo2", "%")?.let { "SpO₂ $it" },
            one("temp", "°C", true)?.let { "Temp $it" }, one("hrv", "ms")?.let { "HRV $it" })
        else -> emptyList()
    }
}

/**
 * Écran DM : popup de mesure (comme l'app Android normale, en plus lisible) :
 * « Connexion à la bague R12… » → « Mesure en cours… » (valeurs en direct) → « Déconnexion… »
 * → résultat (ou erreur) affiché 5 s. Désactivable depuis l'admin (réglage « Popup de mesure »).
 */
@Composable
fun DmMeasurePopup() {
    if (!AppState.prefs.dmPopup) return
    val active by AppState.active.collectAsState()
    val last by AppState.lastResult.collectAsState()
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(active, last) { while (true) { now = System.currentTimeMillis(); delay(500) } }

    val a = active
    val res = last?.takeIf { now - it.atMs < 5_000 && it.error != Err.CANCELLED }
    if (a == null && res == null) return
    val cmd = a?.cmd ?: res!!.cmd
    val tint = tintOf(cmd)

    BoxWithConstraints(Modifier.fillMaxSize().background(Color(0x99000000)), contentAlignment = Alignment.Center) {
        val side = if (maxWidth < maxHeight) maxWidth else maxHeight
        val k = (side.value / 384f).coerceIn(0.7f, 2f)
        val round = DmMode.round(androidx.compose.ui.platform.LocalContext.current)
        Column(
            Modifier.fillMaxWidth(if (round) 0.72f else 0.88f)
                .clip(RoundedCornerShape((22 * k).dp)).background(PANEL)
                .border(1.5.dp, tint.copy(alpha = 0.6f), RoundedCornerShape((22 * k).dp))
                .padding((16 * k).dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy((8 * k).dp)
        ) {
            Text(titleOf(cmd), color = tint, fontSize = (24 * k).sp, fontWeight = FontWeight.ExtraBold, textAlign = TextAlign.Center)
            if (a != null) {
                // En cours : étape (connexion, mesure, déconnexion) + valeur en direct
                val elapsed = ((now - a.startedAtMs) / 1000).toInt()
                CircularProgressIndicator(color = tint, strokeWidth = (5 * k).dp, modifier = Modifier.size((54 * k).dp))
                Text(a.liveText ?: tr("meas.running"), color = TXT, fontSize = (20 * k).sp, fontWeight = FontWeight.Bold,
                    textAlign = TextAlign.Center, maxLines = 2)
                Text(if (RingManager.searchingForMeasure) "$elapsed s" else "$elapsed s / ${a.cmd.durationSec} s",
                    color = MUTED, fontSize = (14 * k).sp)
                Box(
                    Modifier.clip(RoundedCornerShape(50)).background(Color(0x33FF6B6B))
                        .clickable { CommandProcessor.cancelCurrent() }
                        .padding(horizontal = (20 * k).dp, vertical = (8 * k).dp)
                ) { Text(tr("btn.cancel"), color = ERR, fontSize = (15 * k).sp, fontWeight = FontWeight.Bold) }
            } else if (res != null) {
                // Terminé : résultat (la bague a été libérée)
                if (res.ok) {
                    Text("✅", fontSize = (30 * k).sp)
                    resultLines(res.cmd, res.values).forEach {
                        Text(it, color = TXT, fontSize = (if (res.cmd == Cmd.ALL) 22 else 40).let { f -> (f * k).sp },
                            fontWeight = FontWeight.ExtraBold, textAlign = TextAlign.Center)
                    }
                    Text(tr("meas.sent"), color = OK, fontSize = (15 * k).sp)
                } else {
                    Text("⚠️", fontSize = (30 * k).sp)
                    Text(Err.label(res.error ?: Err.MEASURE_FAILED), color = ERR, fontSize = (20 * k).sp,
                        fontWeight = FontWeight.Bold, textAlign = TextAlign.Center)
                }
                Text(tr("dm.ring_released", RingManager.modelLabel()), color = MUTED, fontSize = (13 * k).sp, textAlign = TextAlign.Center)
            }
        }
    }
}

/** Montre sans bague : on touche une tuile → « Aucune bague affectée : choisir une bague ? » */
@Composable
fun DmNoRingPopup(onPick: () -> Unit, onClose: () -> Unit) {
    BoxWithConstraints(Modifier.fillMaxSize().background(Color(0x99000000)).clickable { onClose() }, contentAlignment = Alignment.Center) {
        val side = if (maxWidth < maxHeight) maxWidth else maxHeight
        val k = (side.value / 384f).coerceIn(0.7f, 2f)
        val round = DmMode.round(androidx.compose.ui.platform.LocalContext.current)
        Column(
            Modifier.fillMaxWidth(if (round) 0.72f else 0.88f)
                .clip(RoundedCornerShape((22 * k).dp)).background(PANEL)
                .border(1.5.dp, Color(0x886C8CFF), RoundedCornerShape((22 * k).dp))
                .clickable(enabled = false) {}
                .padding((16 * k).dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy((10 * k).dp)
        ) {
            Text("💍", fontSize = (30 * k).sp)
            Text(tr("dm.noring_title"), color = TXT, fontSize = (20 * k).sp, fontWeight = FontWeight.ExtraBold, textAlign = TextAlign.Center)
            Text(tr("dm.noring_text"), color = MUTED, fontSize = (14 * k).sp, textAlign = TextAlign.Center)
            Row(horizontalArrangement = Arrangement.spacedBy((10 * k).dp)) {
                Box(Modifier.clip(RoundedCornerShape(50)).background(Color(0xFF35E0C2)).clickable { onPick() }
                    .padding(horizontal = (18 * k).dp, vertical = (9 * k).dp)) {
                    Text(tr("dm.noring_pick"), color = Color(0xFF06201D), fontSize = (15 * k).sp, fontWeight = FontWeight.Bold)
                }
                Box(Modifier.clip(RoundedCornerShape(50)).background(Color(0xFF252C45)).clickable { onClose() }
                    .padding(horizontal = (18 * k).dp, vertical = (9 * k).dp)) {
                    Text(tr("pick.no"), color = TXT, fontSize = (15 * k).sp, fontWeight = FontWeight.Bold)
                }
            }
            Spacer(Modifier.height(1.dp))
        }
    }
}
