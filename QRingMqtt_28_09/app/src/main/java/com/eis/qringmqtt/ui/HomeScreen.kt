package com.eis.qringmqtt.ui

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Bedtime
import androidx.compose.material.icons.filled.BatteryChargingFull
import androidx.compose.material.icons.filled.BatteryFull
import androidx.compose.material.icons.filled.Bluetooth
import androidx.compose.material.icons.filled.BluetoothSearching
import androidx.compose.material.icons.filled.Bolt
import androidx.compose.material.icons.filled.DirectionsRun
import androidx.compose.material.icons.filled.DirectionsWalk
import androidx.compose.material.icons.filled.EventSeat
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.MonitorHeart
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Speed
import androidx.compose.material.icons.filled.Thermostat
import androidx.compose.material.icons.filled.WaterDrop
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.eis.qringmqtt.ble.RingManager
import com.eis.qringmqtt.data.AppState
import com.eis.qringmqtt.data.BrokerConn
import com.eis.qringmqtt.data.Cmd
import com.eis.qringmqtt.data.Command
import com.eis.qringmqtt.data.Reading
import com.eis.qringmqtt.data.RingConn
import com.eis.qringmqtt.data.Source
import com.eis.qringmqtt.data.tr
import com.eis.qringmqtt.service.CommandProcessor
import kotlinx.coroutines.delay

/** Définition d'une carte de l'accueil. */
data class Metric(
    val key: String,
    val icon: ImageVector,
    val color: Color,
    val cmd: Cmd,
    val unit: String = ""
) {
    val label: String get() = tr("m.$key")
}

val METRICS = listOf(
    Metric("hr", Icons.Filled.Favorite, C.hr, Cmd.HR, "bpm"),
    Metric("spo2", Icons.Filled.WaterDrop, C.spo2, Cmd.SPO2, "%"),
    Metric("temp", Icons.Filled.Thermostat, C.temp, Cmd.TEMP, "°C"),
    Metric("bp", Icons.Filled.Speed, C.bp, Cmd.BP, "mmHg"),
    Metric("hrv", Icons.Filled.MonitorHeart, C.hrv, Cmd.HRV, "ms"),
    Metric("stress", Icons.Filled.Bolt, C.stress, Cmd.STRESS, "/100"),
    Metric("steps", Icons.Filled.DirectionsWalk, C.steps, Cmd.STEPS),
    Metric("sleep", Icons.Filled.Bedtime, C.sleep, Cmd.SLEEP),
    Metric("sedentary", Icons.Filled.EventSeat, C.warn, Cmd.SEDENTARY),
    Metric("workouts", Icons.Filled.DirectionsRun, C.ok, Cmd.WORKOUTS),
    Metric("battery", Icons.Filled.BatteryFull, C.ok, Cmd.BATTERY, "%")
)

/** Texte principal + détail d'une carte à partir de la dernière valeur. */
fun formatReading(m: Metric, r: Reading?): Pair<String, String?> {
    if (r == null) return "--" to null
    val v = r.values
    return when (m.key) {
        "hr" -> v.optInt("value").toString() to (if (v.has("rri")) tr("home.rri", v.optInt("rri")) else null)
        "spo2", "hrv", "stress" -> v.optInt("value").toString() to null
        "temp" -> "%.1f".format(v.optDouble("value")) to null
        "bp" -> "${v.optInt("sbp")}/${v.optInt("dbp")}" to null
        "steps" -> thousands(v.optInt("steps")) to
                "${"%.1f".format(v.optInt("distance") / 1000.0)} km · ${v.optInt("calories")} kcal"
        "sleep" -> duration(sleepSeconds(v.optInt("totalSeconds"))) to
                tr("home.deep", duration(sleepSeconds(v.optInt("deepSeconds"))))
        "sedentary" -> duration(v.optInt("sedentaryMinutes") * 60 + v.optInt("stillMinutes") * 60) to tr("home.still")
        "workouts" -> v.optInt("count").toString() to tr("home.sessions")
        else -> "--" to null
    }
}

@Composable
fun HomeScreen(isTv: Boolean, onScan: () -> Unit) {
    val ring by AppState.ring.collectAsState()
    val broker by AppState.broker.collectAsState()
    val info by AppState.info.collectAsState()
    val reconnectIn by AppState.reconnectInSec.collectAsState()
    val readings by AppState.readings.collectAsState()
    val active by AppState.active.collectAsState()
    val syncing by AppState.syncing.collectAsState()
    val queued by AppState.queued.collectAsState()
    val errors by AppState.errors.collectAsState()
    val worn by AppState.worn.collectAsState()

    // Horloge pour « il y a X min » et la progression
    val now = remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) { while (true) { now.longValue = System.currentTimeMillis(); delay(1000) } }

    val connected = ring == RingConn.CONNECTED
    val visible = METRICS.filter { m ->
        !(m.cmd.measure && info.supportsKnown && m.key !in info.supports)
    }
    // Uniquement les mesures de la bague associée
    val latest = remember(readings, info.mac) {
        readings.filter { it.ringMac == info.mac }.groupBy { it.type }.mapValues { it.value.last() }
    }

    LazyVerticalGrid(
        columns = if (isTv) GridCells.Fixed(4) else GridCells.Adaptive(158.dp),
        contentPadding = PaddingValues(if (isTv) 20.dp else 12.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
        modifier = Modifier.fillMaxSize()
    ) {
        // ---- En-tête : état des connexions
        item(span = { GridItemSpan(maxLineSpan) }) {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                if (ring == RingConn.DISCONNECTED || ring == RingConn.BLUETOOTH_OFF) {
                    DisconnectedBanner(ring, reconnectIn, isTv)
                } else if (connected && worn == false) {
                    WearBanner(isTv)
                }
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    StatusPill(
                        tr("lbl.ring"), ring.label,
                        when (ring) {
                            RingConn.CONNECTED -> C.ok
                            RingConn.CONNECTING -> C.warn
                            else -> C.err
                        },
                        Modifier.weight(1f)
                    )
                    StatusPill(
                        tr("lbl.broker"), broker.label,
                        when (broker) {
                            BrokerConn.ONLINE -> C.ok
                            BrokerConn.CONNECTING -> C.warn
                            else -> C.err
                        },
                        Modifier.weight(1f)
                    )
                }
                RingHeader(onScan)
            }
        }

        // ---- Cartes des modules
        items(visible, key = { it.key }) { m ->
            val isActive = active?.cmd == m.cmd || (active?.cmd == Cmd.ALL && m.cmd.measure)
            val isSyncing = syncing == m.cmd
            val isQueued = m.cmd in queued
            val err = errors[m.key]?.takeIf { it.untilMs > now.longValue }
            val reading = if (m.key == "battery") null else latest[m.key]
            MetricCard(
                m = m,
                reading = reading,
                batteryText = if (m.key == "battery") info.battery?.let { "$it" } else null,
                charging = info.charging,
                active = isActive,
                activeStartMs = active?.startedAtMs ?: 0L,
                activeDuration = active?.cmd?.durationSec ?: 30,
                live = active?.liveText,
                syncing = isSyncing,
                queued = isQueued,
                error = err?.message,
                enabled = connected,
                nowMs = now.longValue,
                onClick = { CommandProcessor.submit(Command(m.cmd, null, Source.MANUAL)) }
            )
        }

        // ---- Tout mesurer
        item(span = { GridItemSpan(maxLineSpan) }) {
            BigButton(
                if (active?.cmd == Cmd.ALL) tr("home.all_running") else tr("m.all"),
                Modifier.fillMaxWidth(),
                enabled = connected && active == null,
                icon = Icons.Filled.PlayArrow
            ) { CommandProcessor.submit(Command(Cmd.ALL, null, Source.MANUAL)) }
        }
    }
}

@Composable
private fun RingHeader(onScan: () -> Unit) {
    val info by AppState.info.collectAsState()
    val ring by AppState.ring.collectAsState()
    Panel(Modifier.fillMaxWidth(), color = C.card2) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            val b = info.battery
            RingProgress((b ?: 0) / 100f, if ((b ?: 100) < 20) C.err else C.ok, Modifier.size(52.dp), 5.dp) {
                Text(b?.let { "$it%" } ?: "--", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = C.text)
            }
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        info.name.ifBlank { tr("home.no_ring") }, fontWeight = FontWeight.Bold, fontSize = 15.sp,
                        color = C.text, maxLines = 1, overflow = TextOverflow.Ellipsis
                    )
                    if (info.charging) {
                        Spacer(Modifier.width(6.dp))
                        Icon(Icons.Filled.BatteryChargingFull, null, tint = C.ok, modifier = Modifier.size(15.dp))
                        Text(tr("home.charging"), color = C.ok, fontSize = 11.sp)
                    }
                }
                Text(
                    listOf(info.mac, info.model, info.firmware.takeIf { it.isNotBlank() }?.let { "fw $it" })
                        .filter { !it.isNullOrBlank() }.joinToString(" · ").ifBlank { tr("home.press_scan") },
                    color = C.muted, fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis
                )
                Text(
                    if (ring == RingConn.CONNECTED) tr("home.service_active") else ring.label,
                    color = C.muted, fontSize = 11.sp
                )
            }
            Spacer(Modifier.width(8.dp))
            Box(
                Modifier
                    .focusClick(RoundedCornerShape(12.dp), onClick = onScan)
                    .background(C.accent.copy(alpha = 0.18f))
                    .padding(horizontal = 12.dp, vertical = 9.dp)
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Filled.BluetoothSearching, null, tint = C.accent, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(6.dp))
                    Text(tr("btn.scan"), color = C.accent, fontWeight = FontWeight.Bold, fontSize = 13.sp)
                }
            }
        }
    }
}

@Composable
private fun DisconnectedBanner(ring: RingConn, reconnectIn: Int?, isTv: Boolean) {
    Box(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(C.err.copy(alpha = 0.13f))
            .border(1.dp, C.err.copy(alpha = 0.35f), RoundedCornerShape(14.dp))
            .padding(horizontal = 14.dp, vertical = if (isTv) 16.dp else 11.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Filled.Warning, null, tint = C.err, modifier = Modifier.size(if (isTv) 34.dp else 24.dp))
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    if (ring == RingConn.BLUETOOTH_OFF) tr("home.bt_off_title") else tr("home.disc_title"),
                    color = C.err, fontWeight = FontWeight.ExtraBold, fontSize = if (isTv) 22.sp else 15.sp
                )
                Text(
                    when {
                        ring == RingConn.BLUETOOTH_OFF -> tr("home.bt_off_text")
                        reconnectIn != null -> tr("home.reconnect_in", reconnectIn)
                        else -> tr("home.reconnecting")
                    },
                    color = C.muted, fontSize = if (isTv) 14.sp else 11.sp
                )
            }
            if (ring != RingConn.BLUETOOTH_OFF) {
                Box(
                    Modifier
                        .focusClick(RoundedCornerShape(10.dp)) { RingManager.reconnectNow() }
                        .background(C.err)
                        .padding(horizontal = 12.dp, vertical = 8.dp)
                ) { Text(tr("btn.reconnect"), color = Color.White, fontWeight = FontWeight.Bold, fontSize = 12.sp) }
            }
        }
    }
}

/** Bague retirée : « Veuillez porter la bague ». */
@Composable
private fun WearBanner(isTv: Boolean) {
    Box(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(C.warn.copy(alpha = 0.14f))
            .border(1.dp, C.warn.copy(alpha = 0.4f), RoundedCornerShape(14.dp))
            .padding(horizontal = 14.dp, vertical = if (isTv) 16.dp else 11.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Filled.Warning, null, tint = C.warn, modifier = Modifier.size(if (isTv) 34.dp else 24.dp))
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(tr("home.wear_title"), color = C.warn, fontWeight = FontWeight.ExtraBold, fontSize = if (isTv) 22.sp else 15.sp)
                Text(tr("home.wear_text"), color = C.text, fontSize = if (isTv) 15.sp else 12.sp)
            }
        }
    }
}

@Composable
private fun MetricCard(
    m: Metric,
    reading: Reading?,
    batteryText: String?,
    charging: Boolean,
    active: Boolean,
    activeStartMs: Long,
    activeDuration: Int,
    live: String?,
    syncing: Boolean,
    queued: Boolean,
    error: String?,
    enabled: Boolean,
    nowMs: Long,
    onClick: () -> Unit
) {
    val (main, detail) = if (batteryText != null) batteryText to (if (charging) tr("home.charging") else null)
    else formatReading(m, reading)
    val shape = RoundedCornerShape(16.dp)
    val pulse = rememberInfiniteTransition(label = "pulse")
    val a by pulse.animateFloat(0.45f, 1f, infiniteRepeatable(tween(700), RepeatMode.Reverse), label = "a")

    Box(
        Modifier
            .heightIn(min = 112.dp)
            .focusClick(shape, onClick = onClick)
            .background(C.card)
            .then(if (active) Modifier.border(1.5.dp, m.color, shape) else Modifier)
            .alpha(if (enabled || active) 1f else 0.45f)
            .padding(12.dp)
    ) {
        Column(Modifier.fillMaxWidth()) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                IconBadge(m.icon, m.color)
                Spacer(Modifier.width(7.dp))
                Text(m.label, color = C.muted, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            Spacer(Modifier.height(8.dp))
            when {
                active -> {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(color = m.color, strokeWidth = 2.5.dp, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(8.dp))
                        Text(
                            live ?: tr("home.measuring"), color = m.color, fontWeight = FontWeight.Bold,
                            fontSize = if (live != null) 20.sp else 15.sp, modifier = Modifier.alpha(if (live == null) a else 1f)
                        )
                    }
                    val elapsed = ((nowMs - activeStartMs) / 1000).toInt()
                    Spacer(Modifier.height(8.dp))
                    LinearProgressIndicator(
                        progress = { (elapsed.toFloat() / activeDuration).coerceIn(0f, 1f) },
                        color = m.color, trackColor = C.line,
                        modifier = Modifier.fillMaxWidth().height(4.dp)
                    )
                    Text("$elapsed s / $activeDuration s", color = C.muted, fontSize = 10.sp, modifier = Modifier.padding(top = 3.dp))
                }
                syncing -> {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(color = m.color, strokeWidth = 2.5.dp, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(8.dp))
                        Text(tr("home.syncing"), color = m.color, fontSize = 14.sp, modifier = Modifier.alpha(a))
                    }
                }
                else -> {
                    Row(verticalAlignment = Alignment.Bottom) {
                        Text(main, color = C.text, fontSize = 26.sp, fontWeight = FontWeight.Bold, maxLines = 1)
                        if (m.unit.isNotBlank() && main != "--") {
                            Spacer(Modifier.width(3.dp))
                            Text(m.unit, color = C.muted, fontSize = 12.sp, modifier = Modifier.padding(bottom = 4.dp))
                        }
                    }
                    val sub = when {
                        error != null -> error
                        queued -> tr("home.queued")
                        detail != null && reading != null -> "$detail · ${ago(reading.ts, nowMs)}"
                        detail != null -> detail
                        reading != null -> "${ago(reading.ts, nowMs)} · ${reading.source.label}"
                        else -> if (m.cmd.measure) tr("home.tap_measure") else tr("home.tap_sync")
                    }
                    Text(
                        sub, color = if (error != null) C.err else C.muted, fontSize = 11.sp,
                        maxLines = 1, overflow = TextOverflow.Ellipsis
                    )
                }
            }
        }
    }
}
