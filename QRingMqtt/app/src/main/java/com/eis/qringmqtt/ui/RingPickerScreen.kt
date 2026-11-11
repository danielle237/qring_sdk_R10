package com.eis.qringmqtt.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import com.eis.qringmqtt.ble.RingManager
import com.eis.qringmqtt.data.AppState
import com.eis.qringmqtt.data.tr
import org.json.JSONArray

/** Une bague proposée : MAC, nom Bluetooth, nom du résident (admin), signal si vue autour. */
private data class Choice(val mac: String, val name: String, val label: String, val rssi: Int?)

private fun parse(json: String): List<Choice> = try {
    val a = JSONArray(json)
    (0 until a.length()).mapNotNull { i ->
        val o = a.optJSONObject(i) ?: return@mapNotNull null
        val mac = RingManager.normalizeMac(o.optString("mac"))
        if (mac.count { it.isLetterOrDigit() } != 12) null
        else Choice(mac, o.optString("name"), o.optString("label"), null)
    }
} catch (_: Exception) { emptyList() }

/**
 * « Bague active » : choisir LA bague que cette Gateway RHM utilise.
 * Trois listes : choisies dans l'admin · déjà utilisées ici · vues autour (recherche 10 s).
 * Toucher une bague → confirmation → la gateway lâche l'ancienne et associe celle-ci.
 */
@Composable
fun RingPickerScreen(isTv: Boolean, onDone: () -> Unit) {
    val scanning by AppState.scanning.collectAsState()
    val near by AppState.scanResults.collectAsState()
    val info by AppState.info.collectAsState()
    var ask by remember { mutableStateOf<Choice?>(null) }

    DisposableEffect(Unit) {
        RingManager.startScan()
        onDispose { RingManager.stopScan() }
    }

    val active = AppState.prefs.ringMac?.uppercase()
    val rssiOf = near.associate { it.mac.uppercase() to it.rssi }
    val admin = parse(AppState.prefs.allowedRingsJson).map { it.copy(rssi = rssiOf[it.mac]) }
    val used = parse(AppState.prefs.usedRingsJson).filter { u -> admin.none { it.mac == u.mac } }
        .map { it.copy(rssi = rssiOf[it.mac]) }
    val known = (admin + used).map { it.mac }.toSet()
    val labels = admin.associate { it.mac to it.label }
    val seen = near.filter { it.mac.uppercase() !in known }
        .map { Choice(it.mac.uppercase(), it.name, labels[it.mac.uppercase()] ?: "", it.rssi) }

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(if (isTv) 20.dp else 12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.focusClick(RoundedCornerShape(50), onClick = onDone).padding(8.dp)) {
                Icon(Icons.Filled.ArrowBack, tr("btn.back"), tint = C.text)
            }
            Spacer(Modifier.width(6.dp))
            Text(tr("pick.title"), color = C.text, fontSize = 20.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            Box(Modifier.focusClick(RoundedCornerShape(50)) { RingManager.startScan() }.padding(8.dp)) {
                if (scanning) CircularProgressIndicator(color = C.accent, strokeWidth = 2.dp, modifier = Modifier.size(20.dp))
                else Icon(Icons.Filled.Refresh, tr("pick.search"), tint = C.accent)
            }
        }
        // Bague active
        Panel(Modifier.fillMaxWidth(), padding = 10.dp) {
            Text(
                if (active == null) tr("pick.none") else "✅ ${info.name.ifBlank { active }}" +
                    (AppState.ringLabel.value.takeIf { it.isNotBlank() }?.let { " · $it" } ?: ""),
                color = C.text, fontWeight = FontWeight.Bold, fontSize = 14.sp, maxLines = 2
            )
        }
        Section(tr("pick.admin"), admin, active) { ask = it }
        Section(tr("pick.used"), used, active) { ask = it }
        SectionTitle(tr("pick.near") + if (scanning) " · " + tr("pick.searching") else "")
        if (seen.isEmpty()) Text(tr("pick.empty"), color = C.muted, fontSize = 12.sp)
        seen.forEach { c -> ChoiceRow(c, c.mac == active) { ask = c } }
    }

    ask?.let { c ->
        Dialog(onDismissRequest = { ask = null }) {
            Column(
                Modifier.background(C.surface, RoundedCornerShape(18.dp)).padding(18.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                Text(tr("pick.confirm", c.name.ifBlank { c.mac }), color = C.text, fontSize = 17.sp,
                    fontWeight = FontWeight.Bold, textAlign = TextAlign.Center)
                if (c.label.isNotBlank()) Text(c.label, color = C.muted, fontSize = 13.sp)
                Text(tr("pick.confirm_text"), color = C.muted, fontSize = 12.sp, textAlign = TextAlign.Center)
                BigButton(tr("pick.yes"), Modifier.fillMaxWidth()) {
                    ask = null
                    RingManager.stopScan()
                    if (c.mac != active) RingManager.bind(c.mac, c.name.ifBlank { c.mac })
                    onDone()
                }
                BigButton(tr("pick.no"), Modifier.fillMaxWidth(), color = C.card2) { ask = null }
            }
        }
    }
}

@Composable
private fun Section(title: String, list: List<Choice>, active: String?, onPick: (Choice) -> Unit) {
    if (list.isEmpty()) return
    SectionTitle(title)
    list.forEach { c -> ChoiceRow(c, c.mac == active) { onPick(c) } }
}

@Composable
private fun ChoiceRow(c: Choice, isActive: Boolean, onClick: () -> Unit) {
    val shape = RoundedCornerShape(14.dp)
    Box(
        Modifier
            .fillMaxWidth()
            .focusClick(shape, onClick = onClick)
            .background(C.card)
            .then(if (isActive) Modifier.border(1.5.dp, C.ok, shape) else Modifier)
            .padding(horizontal = 12.dp, vertical = 9.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(
                    (c.name.ifBlank { c.mac }) + if (isActive) "  " + tr("pick.active") else "",
                    color = C.text, fontWeight = FontWeight.Bold, fontSize = 14.sp, maxLines = 1, overflow = TextOverflow.Ellipsis
                )
                if (c.label.isNotBlank()) Text(c.label, color = C.accent, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(c.mac, color = C.muted, fontSize = 11.sp, fontFamily = FontFamily.Monospace)
            }
            Text(c.rssi?.let { "📶 $it dBm" } ?: "—", color = if (c.rssi != null) C.ok else C.muted, fontSize = 11.sp)
        }
    }
}
