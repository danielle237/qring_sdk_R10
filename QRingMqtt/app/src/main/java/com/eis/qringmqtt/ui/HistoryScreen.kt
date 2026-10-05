package com.eis.qringmqtt.ui

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.eis.qringmqtt.data.AppState
import com.eis.qringmqtt.data.Cmd
import com.eis.qringmqtt.data.Command
import com.eis.qringmqtt.data.Reading
import com.eis.qringmqtt.data.RingConn
import com.eis.qringmqtt.data.Source
import com.eis.qringmqtt.data.tr
import com.eis.qringmqtt.service.CommandProcessor

/** Valeur spéciale du sélecteur de bague. */
private const val ALL_RINGS = "*"

@Composable
fun HistoryScreen(isTv: Boolean) {
    val readings by AppState.readings.collectAsState()
    val ring by AppState.ring.collectAsState()
    val syncing by AppState.syncing.collectAsState()
    val info by AppState.info.collectAsState()
    val metrics = METRICS.filter { it.cmd.measure }
    var selKey by remember { mutableStateOf(metrics.first().key) }
    val sel = metrics.first { it.key == selKey }
    var range by remember { mutableIntStateOf(0) } // 0 = jour, 1 = 7 jours, 2 = 30 jours

    // Bagues présentes dans l'historique (la bague actuelle en premier)
    val rings = remember(readings, info.mac) {
        (listOf(info.mac) + readings.map { it.ringMac }).filter { it.isNotBlank() }.distinct()
    }
    var ringSel by remember { mutableStateOf(info.mac.ifBlank { ALL_RINGS }) }

    val nowS = System.currentTimeMillis() / 1000
    val from = nowS - when (range) { 0 -> 86400L; 1 -> 7 * 86400L; else -> 30 * 86400L }
    val list = remember(readings, selKey, range, ringSel) {
        readings.filter {
            it.type == selKey && it.ts >= from && (ringSel == ALL_RINGS || it.ringMac == ringSel)
        }.sortedBy { it.ts }
    }
    val pts = list.mapNotNull { r ->
        val y = if (selKey == "bp") r.values.optInt("sbp").toFloat() else r.values.optDouble("value", Double.NaN).toFloat()
        if (y.isNaN() || y <= 0f) null else r.ts.toFloat() to y
    }

    Column(Modifier.fillMaxSize().padding(if (isTv) 20.dp else 12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        // Choix de la bague
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            rings.forEach { mac ->
                val label = if (mac == info.mac) "${info.name.ifBlank { mac }} (${tr("hist.current")})" else mac
                Chip(label, ringSel == mac) { ringSel = mac }
            }
            Chip(tr("hist.all_rings"), ringSel == ALL_RINGS) { ringSel = ALL_RINGS }
        }
        // Choix de la mesure
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            metrics.forEach { m -> Chip(m.label, m.key == selKey) { selKey = m.key } }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Chip(tr("hist.day"), range == 0) { range = 0 }
            Chip(tr("hist.7d"), range == 1) { range = 1 }
            Chip(tr("hist.30d"), range == 2) { range = 2 }
            Spacer(Modifier.weight(1f))
            Chip(if (syncing == Cmd.HISTORY) tr("hist.importing") else tr("hist.import"), false) {
                if (ring == RingConn.CONNECTED) CommandProcessor.submit(Command(Cmd.HISTORY, null, Source.MANUAL))
            }
        }
        Panel(Modifier.fillMaxWidth()) {
            Column {
                val ys = pts.map { it.second }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(sel.label, color = C.text, fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                    if (ys.isNotEmpty()) Text(
                        tr("hist.stats", fmtNum(ys.average().toFloat()), fmtNum(ys.min()), fmtNum(ys.max())),
                        color = C.muted, fontSize = 11.sp
                    )
                }
                Spacer(Modifier.height(8.dp))
                if (pts.isEmpty()) {
                    Text(tr("hist.none"), color = C.muted, fontSize = 12.sp, modifier = Modifier.padding(vertical = 30.dp))
                } else {
                    LineChart(pts, sel.color, Modifier.fillMaxWidth().height(if (isTv) 200.dp else 150.dp))
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        val a = pts.first().first.toLong(); val b = pts.last().first.toLong()
                        Text(if (range == 0) hhmm(a) else dayMonth(a), color = C.muted, fontSize = 9.sp)
                        Text(if (range == 0) hhmm(b) else dayMonth(b), color = C.muted, fontSize = 9.sp)
                    }
                }
            }
        }
        SectionTitle(tr("hist.measures"))
        LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            items(list.reversed().take(100)) { r -> HistoryRow(sel, r) }
        }
    }
}

@Composable
private fun HistoryRow(m: Metric, r: Reading) {
    Panel(Modifier.fillMaxWidth(), padding = 10.dp) {
        Column {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("${formatReading(m, r).first} ${m.unit}", color = C.text, fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                Text("${dayMonth(r.ts)} ${hhmm(r.ts)} · ${r.label}", color = C.muted, fontSize = 11.sp)
            }
            Text(r.ringMac, color = C.muted, fontSize = 10.sp)
        }
    }
}

private fun fmtNum(f: Float): String = if (f % 1f == 0f) f.toInt().toString() else "%.1f".format(f)
