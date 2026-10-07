package com.eis.qringmqtt.ui

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Bedtime
import androidx.compose.material.icons.filled.BatteryChargingFull
import androidx.compose.material.icons.filled.BatteryFull
import androidx.compose.material.icons.filled.Battery1Bar
import androidx.compose.material.icons.filled.Battery3Bar
import androidx.compose.material.icons.filled.Battery5Bar
import androidx.compose.material.icons.filled.BatteryUnknown
import androidx.compose.material.icons.filled.Bolt
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.DirectionsRun
import androidx.compose.material.icons.filled.DirectionsWalk
import androidx.compose.material.icons.filled.EventSeat
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.HourglassTop
import androidx.compose.material.icons.filled.MonitorHeart
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Speed
import androidx.compose.material.icons.filled.Thermostat
import androidx.compose.material.icons.filled.WaterDrop
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
import com.eis.qringmqtt.R
import androidx.compose.ui.res.painterResource
import androidx.compose.foundation.Image
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.runtime.setValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
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

/**
 * Ordre des cartes (TV : 4 par ligne) :
 * HR · SpO2 · Température · HRV / Pas · Stress · Sédentarité · Sommeil (Tension retirée de l'app)
 */
val METRICS = listOf(
    Metric("hr", Icons.Filled.Favorite, C.hr, Cmd.HR, "bpm"),
    Metric("spo2", Icons.Filled.WaterDrop, C.spo2, Cmd.SPO2, "%"),
    Metric("temp", Icons.Filled.Thermostat, C.temp, Cmd.TEMP, "°C"),
    Metric("hrv", Icons.Filled.MonitorHeart, C.hrv, Cmd.HRV, "ms"),
    Metric("battery", Icons.Filled.BatteryFull, C.ok, Cmd.BATTERY, "%"),
    Metric("steps", Icons.Filled.DirectionsWalk, C.steps, Cmd.STEPS),
    Metric("stress", Icons.Filled.Bolt, C.stress, Cmd.STRESS, "/100"),
    Metric("sedentary", Icons.Filled.EventSeat, C.warn, Cmd.SEDENTARY),
    Metric("workouts", Icons.Filled.DirectionsRun, C.ok, Cmd.WORKOUTS),
    Metric("sleep", Icons.Filled.Bedtime, C.sleep, Cmd.SLEEP)
)

/** Calories en kcal : certaines bagues envoient des calories (cal) → ÷ 1000 si la valeur est aberrante. */
fun kcal(v: org.json.JSONObject): String {
    val c = v.optInt("calories")
    val steps = v.optInt("steps")
    val k = if (c > 1000 && (steps == 0 || c > steps * 2)) c / 1000.0 else c.toDouble()
    return "%.1f".format(k)
}

/** Texte principal + détail d'une carte à partir de la dernière valeur. */
fun formatReading(m: Metric, r: Reading?): Pair<String, String?> {
    if (r == null) return "--" to null
    val v = r.values
    return when (m.key) {
        // Le RRI reste dans l'historique ; la carte affiche l'origine de la mesure
        "hr" -> v.optInt("value").toString() to null
        "spo2", "hrv", "stress" -> v.optInt("value").toString() to null
        "temp" -> "%.1f".format(v.optDouble("value")) to null
        "bp" -> "${v.optInt("sbp")}/${v.optInt("dbp")}" to null
        "steps" -> thousands(v.optInt("steps")) to
                "${"%.1f".format(v.optInt("distance") / 1000.0)} km"
        "sleep" -> duration(sleepSeconds(v.optInt("totalSeconds"))) to
                tr("home.deep", duration(sleepSeconds(v.optInt("deepSeconds"))))
        "sedentary" -> duration(v.optInt("sedentaryMinutes") * 60 + v.optInt("stillMinutes") * 60) to tr("home.still")
        "workouts" -> v.optInt("count").toString() to tr("home.sessions")
        else -> "--" to null
    }
}

@Composable
fun HomeScreen(isTv: Boolean) {
    val ring by AppState.ring.collectAsState()
    val info by AppState.info.collectAsState()
    val readings by AppState.readings.collectAsState()
    val active by AppState.active.collectAsState()
    val syncing by AppState.syncing.collectAsState()
    val queued by AppState.queued.collectAsState()
    val errors by AppState.errors.collectAsState()

    // Horloge pour « il y a X min », la progression et le compte à rebours
    val now = remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) { while (true) { now.longValue = System.currentTimeMillis(); delay(1000) } }

    val connected = ring == RingConn.CONNECTED
    val visible = METRICS.filter { m ->
        !(m.cmd.measure && info.supportsKnown && m.key !in info.supports) &&
            // TV : la batterie est dans le bandeau du haut ; Entraînements retiré
            !(isTv && (m.key == "battery" || m.key == "workouts"))
    }
    // Uniquement les mesures de la bague associée
    val latest = remember(readings, info.mac) {
        readings.filter { it.ringMac == info.mac }.groupBy { it.type }.mapValues { it.value.last() }
    }

    // Une carte (TV et téléphone)
    val card: @Composable (Metric, Modifier, Boolean) -> Unit = { m, mod, compact ->
        val isActive = active?.cmd == m.cmd || (active?.cmd == Cmd.ALL && m.cmd.measure)
        val err = errors[m.key]?.takeIf { it.untilMs > now.longValue }
        MetricCard(
            m = m,
            reading = if (m.key == "battery") null else latest[m.key],
            batteryText = if (m.key == "battery") info.battery?.let { "$it" } else null,
            batteryDetail = if (m.key == "battery") batteryDetail(info.charging, info.batteryAtMs, now.longValue)?.let { d ->
                // Origine de la lecture de batterie (📱 prise / actualisée · login) si elle vient du téléphone
                val br = latest["battery"]
                val at = info.batteryAtMs
                if (br != null && br.by.isNotEmpty() && at != null && kotlin.math.abs(br.ts * 1000 - at) < 10_000)
                    "$d · ${br.label}" else d
            } else null,
            active = isActive,
            activeStartMs = active?.startedAtMs ?: 0L,
            activeDuration = active?.cmd?.durationSec ?: 30,
            live = active?.liveText,
            syncing = syncing == m.cmd,
            queued = m.cmd in queued,
            error = err?.message,
            enabled = connected,
            nowMs = now.longValue,
            modifier = mod,
            compact = compact,
            onClick = { CommandProcessor.submit(Command(m.cmd, null, Source.MANUAL)) }
        )
    }
    val allButton: @Composable (Modifier) -> Unit = { mod ->
        BigButton(
            if (active?.cmd == Cmd.ALL) tr("home.all_running") else tr("m.all"),
            mod,
            enabled = connected && active == null,
            icon = Icons.Filled.PlayArrow
        ) { CommandProcessor.submit(Command(Cmd.ALL, null, Source.MANUAL)) }
    }

    // ---- TV : tout l'écran sans défilement (bandeau, lignes de cartes qui se partagent la hauteur, boutons)
    if (isTv) {
        Column(
            Modifier.fillMaxSize().padding(horizontal = 16.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            // Bandeau d'infos de la bague en tête, puis les modules
            RingHeader(true, now.longValue)
            // 2 lignes de cartes → cartes plus hautes ; 3 lignes (avec Tension) → 100 dp max
            val rowMax = if (visible.size <= 8) 150.dp else 110.dp
            visible.chunked(4).forEach { row ->
                Row(
                    Modifier.fillMaxWidth().weight(1f, fill = false).heightIn(max = rowMax),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    row.forEach { m -> card(m, Modifier.weight(1f).fillMaxHeight(), true) }
                    repeat(4 - row.size) { Spacer(Modifier.weight(1f)) }
                }
            }
            Spacer(Modifier.weight(0.001f))
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                allButton(Modifier.weight(1f).height(46.dp))
                RefreshButton(Modifier.weight(1f).height(46.dp), now.longValue)
            }
        }
        return
    }

    // ---- Téléphone : grille qui défile
    LazyVerticalGrid(
        columns = if (isTv) GridCells.Fixed(4) else GridCells.Adaptive(158.dp),
        contentPadding = PaddingValues(if (isTv) 20.dp else 12.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
        modifier = Modifier.fillMaxSize()
    ) {
        // ---- Bandeau d'infos de la bague en tête : infos + état (portée / retirée / hors portée)
        item(span = { GridItemSpan(maxLineSpan) }) {
            RingHeader(isTv, now.longValue)
        }

        // ---- Cartes des modules
        items(visible, key = { it.key }) { m ->
            card(m, Modifier.heightIn(min = 112.dp), false)
        }

        // ---- En bas : Tout mesurer puis Actualiser l'état de la bague
        item(span = { GridItemSpan(maxLineSpan) }) {
            val all: @Composable (Modifier) -> Unit = { mod -> allButton(mod.heightIn(min = 48.dp)) }
            if (isTv) {
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.padding(top = 4.dp)) {
                    all(Modifier.weight(1f))
                    RefreshButton(Modifier.weight(1f).heightIn(min = 54.dp), now.longValue)
                }
            } else {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.padding(top = 4.dp)) {
                    all(Modifier.fillMaxWidth())
                    RefreshButton(Modifier.fillMaxWidth().heightIn(min = 48.dp), now.longValue)
                }
            }
        }
    }
}

/** « en charge · il y a 3 min » */
fun batteryDetail(charging: Boolean, atMs: Long?, nowMs: Long = System.currentTimeMillis()): String? =
    listOfNotNull(
        if (charging) tr("home.charging") else null,
        atMs?.let { ago(it / 1000, nowMs) }
    ).joinToString(" · ").ifBlank { null }

/** Clignotement (0 → 1 → 0) pour attirer l'attention. */
@Composable
fun blinkPhase(enabled: Boolean): Float {
    if (!enabled) return 1f
    val t = rememberInfiniteTransition(label = "blink")
    val p by t.animateFloat(0f, 1f, infiniteRepeatable(tween(650), RepeatMode.Reverse), label = "p")
    return p
}

/**
 * Bouton « Actualiser l'état de la bague » :
 *  1) cliquable => clignote ; 2) vérification => « Vérification… 8 s / 15 s » ;
 *  3) ensuite 3 min grisé => « Actualiser dans 2:47 ».
 */
@Composable
fun RefreshButton(modifier: Modifier, nowMs: Long) {
    val ring by AppState.ring.collectAsState()
    val st by StatusCheck.state.collectAsState()
    val cooldown by StatusCheck.cooldownUntil.collectAsState()
    val waiting by StatusCheck.waiting.collectAsState()
    val s = st
    val can = StatusCheck.canStart(ring, s, cooldown, nowMs)
    val p = blinkPhase(can)

    val label: String
    val icon: ImageVector
    when {
        s != null && !s.final -> {
            val elapsed = s.measureStartMs?.let { ((nowMs - it) / 1000).toInt().coerceAtLeast(0) } ?: 0
            label = when (s.phase) {
                StatusCheck.Phase.WORN_MEASURING -> "✓ ${tr("rs.worn_title")} · ${tr("st.measuring", s.cmd.label, elapsed, s.cmd.durationSec)}"
                StatusCheck.Phase.CHECKING -> tr("st.checking_btn", elapsed, (StatusCheck.WEAR_MS / 1000).toInt())
                else -> tr("rs.checking")
            }
            icon = Icons.Filled.HourglassTop
        }
        waiting -> {
            label = tr("st.waiting")
            icon = Icons.Filled.HourglassTop
        }
        else -> {
            label = tr("st.refresh")
            icon = Icons.Filled.Refresh
        }
    }
    val busy = (s != null && !s.final) || waiting
    val bg = when {
        can -> lerp(C.ok.copy(alpha = 0.55f), C.ok, p)
        busy -> C.card2
        else -> C.card
    }
    val fg = when {
        can -> Color.White
        busy -> C.warn
        else -> C.muted
    }
    val shape = RoundedCornerShape(14.dp)
    Box(
        modifier
            .focusClick(shape, can) { StatusCheck.start() }
            .then(if (can) Modifier.border(2.dp, C.ok.copy(alpha = 0.35f + 0.65f * p), shape) else Modifier)
            .background(bg)
            .padding(horizontal = 18.dp, vertical = 13.dp),
        contentAlignment = Alignment.Center
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(icon, null, tint = fg, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
            Text(label, color = fg, fontWeight = FontWeight.Bold, fontSize = 14.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
    }
}

/** Bandeau de la bague : batterie, nom, MAC, firmware, heure de la batterie et état. Pas de bouton Scanner. */
@Composable
private fun RingHeader(isTv: Boolean, nowMs: Long, modifier: Modifier = Modifier.fillMaxWidth(), fill: Boolean = false) {
    val info by AppState.info.collectAsState()
    val ring by AppState.ring.collectAsState()
    val ev by StatusCheck.evidence.collectAsState()
    val st by StatusCheck.state.collectAsState()
    val sum = StatusCheck.summary(ring, ev, st, nowMs)

    // Panneau d'information (pas un bouton : ni focus ni clic), bord de la couleur de l'état
    Panel(modifier.border(1.dp, sum.color.copy(alpha = 0.45f), RoundedCornerShape(16.dp)), color = C.card2, padding = 12.dp) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = if (fill) Modifier.fillMaxHeight() else Modifier) {
            val label by AppState.ringLabel.collectAsState()
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        info.name.ifBlank { tr("home.no_ring") }, fontWeight = FontWeight.Bold, fontSize = if (isTv) 18.sp else 15.sp,
                        color = C.text, maxLines = 1
                    )
                    // Nom donné dans l'admin (base de données), ex. « (Mme Martin) »
                    if (label.isNotBlank() && info.name.isNotBlank() && !label.equals(info.name, ignoreCase = true)) {
                        Spacer(Modifier.width(8.dp))
                        Text("($label)", color = C.text.copy(alpha = 0.85f), fontSize = if (isTv) 15.sp else 13.sp, maxLines = 1)
                    }
                    if (info.charging) {
                        Spacer(Modifier.width(6.dp))
                        Icon(Icons.Filled.BatteryChargingFull, null, tint = C.ok, modifier = Modifier.size(15.dp))
                        Text(tr("home.charging"), color = C.ok, fontSize = 11.sp)
                    }
                }
                val parts = listOfNotNull(
                    info.mac.takeIf { it.isNotBlank() }, info.model.takeIf { it.isNotBlank() },
                    info.firmware.takeIf { it.isNotBlank() }?.let { "fw $it" }
                )
                // Toutes les infos, retour à la ligne si besoin (bandeau étroit TV : une info par ligne)
                if (parts.isEmpty()) {
                    Text(tr("home.press_scan"), color = C.muted, fontSize = if (isTv) 12.sp else 11.sp)
                } else if (fill) {
                    // MAC · modèle / firmware / batterie
                    val mm = listOfNotNull(info.mac.takeIf { it.isNotBlank() }, info.model.takeIf { it.isNotBlank() })
                    (listOf(mm.joinToString(" · ")) + (parts - mm.toSet())).filter { it.isNotBlank() }
                        .forEach { Text(it, color = C.muted, fontSize = 12.sp, lineHeight = 15.sp) }
                } else {
                    Text(parts.joinToString(" · "), color = C.muted, fontSize = if (isTv) 12.sp else 11.sp)
                }
                Spacer(Modifier.height(4.dp))
                // État : pastille colorée + détail (dessous si le bandeau est étroit)
                val pill: @Composable () -> Unit = {
                    Row(
                        Modifier.clip(RoundedCornerShape(50)).background(sum.color.copy(alpha = 0.18f))
                            .padding(horizontal = 10.dp, vertical = 3.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Box(Modifier.size(9.dp).clip(CircleShape).background(sum.color))
                        Spacer(Modifier.width(6.dp))
                        Text(sum.title, color = sum.color, fontWeight = FontWeight.Bold, fontSize = if (isTv) 13.sp else 12.sp)
                    }
                }
                if (fill) {
                    pill()
                    if (sum.detail != null) Text(sum.detail, color = C.muted, fontSize = 12.sp, modifier = Modifier.padding(top = 3.dp))
                } else {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        pill()
                        if (sum.detail != null) {
                            Spacer(Modifier.width(8.dp))
                            Text(sum.detail, color = C.muted, fontSize = if (isTv) 13.sp else 11.sp)
                        }
                    }
                }
                if (sum.progress != null) {
                    Spacer(Modifier.height(6.dp))
                    LinearProgressIndicator(
                        progress = { sum.progress.coerceIn(0f, 1f) },
                        color = sum.color, trackColor = C.line,
                        modifier = Modifier.fillMaxWidth().height(4.dp)
                    )
                }
            }
            // Logo « EHPAD de la Vie » à côté de la batterie
            Spacer(Modifier.width(12.dp))
            Column(
                Modifier.clip(RoundedCornerShape(14.dp)).background(Color.White)
                    .padding(horizontal = 10.dp, vertical = 4.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Image(painterResource(R.drawable.ehpad_logo), null, Modifier.size(if (isTv) 70.dp else 52.dp))
                Text("EHPAD de la Vie", color = Color(0xFF1E3A5F), fontWeight = FontWeight.Bold, fontSize = 11.sp, maxLines = 1)
            }
            if (info.mac.isNotBlank()) {
                Spacer(Modifier.width(12.dp))
                BatteryBadge(isTv, nowMs)
            }
        }
    }
}

/** Batterie dans le bandeau : logo selon le niveau, %, « il y a X min ». Toucher = relire la batterie. */
@Composable
private fun BatteryBadge(isTv: Boolean, nowMs: Long) {
    val info by AppState.info.collectAsState()
    val syncing by AppState.syncing.collectAsState()
    val b = info.battery
    val color = if (b != null && b < 20) C.err else C.ok
    val icon = when {
        info.charging -> Icons.Filled.BatteryChargingFull
        b == null -> Icons.Filled.BatteryUnknown
        b >= 90 -> Icons.Filled.BatteryFull
        b >= 60 -> Icons.Filled.Battery5Bar
        b >= 30 -> Icons.Filled.Battery3Bar
        else -> Icons.Filled.Battery1Bar
    }
    var focused by remember { mutableStateOf(false) }
    Column(
        Modifier
            .clip(RoundedCornerShape(14.dp))
            .border(2.dp, if (focused) C.text else color.copy(alpha = 0.7f), RoundedCornerShape(14.dp))
            .background(color.copy(alpha = if (focused) 0.22f else 0.10f))
            .onFocusChanged { focused = it.isFocused }
            .clickable { CommandProcessor.submit(Command(Cmd.BATTERY, null, Source.MANUAL)) }
            .padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Icon(icon, null, tint = color, modifier = Modifier.size(if (isTv) 32.dp else 22.dp))
        Text(b?.let { "$it %" } ?: "--", color = color, fontWeight = FontWeight.Bold, fontSize = if (isTv) 18.sp else 15.sp)
        Text(
            if (syncing == Cmd.BATTERY) "…" else info.batteryAtMs?.let { ago(it / 1000, nowMs) } ?: "",
            color = C.muted, fontSize = 11.sp, maxLines = 1
        )
    }
}

@Composable
private fun MetricCard(
    m: Metric,
    reading: Reading?,
    batteryText: String?,
    batteryDetail: String?,
    active: Boolean,
    activeStartMs: Long,
    activeDuration: Int,
    live: String?,
    syncing: Boolean,
    queued: Boolean,
    error: String?,
    enabled: Boolean,
    nowMs: Long,
    modifier: Modifier = Modifier,
    compact: Boolean = false,
    onClick: () -> Unit
) {
    val (main, detail) = if (batteryText != null) batteryText to batteryDetail
    else formatReading(m, reading)
    val shape = RoundedCornerShape(16.dp)
    val pulse = rememberInfiniteTransition(label = "pulse")
    val a by pulse.animateFloat(0.45f, 1f, infiniteRepeatable(tween(700), RepeatMode.Reverse), label = "a")

    Box(
        Modifier
            .then(modifier)
            .focusClick(shape, onClick = onClick)
            .background(C.card)
            .then(if (active) Modifier.border(1.5.dp, m.color, shape) else Modifier)
            .alpha(if (enabled || active) 1f else 0.45f)
            .padding(horizontal = 12.dp, vertical = if (compact) 8.dp else 12.dp)
    ) {
        Column(Modifier.fillMaxWidth()) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                IconBadge(m.icon, m.color)
                Spacer(Modifier.width(7.dp))
                Text(m.label, color = C.muted, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            Spacer(Modifier.height(if (compact) 5.dp else 8.dp))
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
                    Spacer(Modifier.height(if (compact) 5.dp else 8.dp))
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
                        detail != null && reading != null && reading.by.isNotEmpty() ->
                            "$detail · ${ago(reading.ts, nowMs)} · ${reading.label}"
                        detail != null && reading != null -> "$detail · ${ago(reading.ts, nowMs)}"
                        detail != null -> detail
                        reading != null -> "${ago(reading.ts, nowMs)} · ${reading.label}"
                        else -> if (m.cmd.measure) tr("home.tap_measure") else tr("home.tap_sync")
                    }
                    Text(
                        sub, color = if (error != null) C.err else C.muted, fontSize = 11.sp,
                        // 2 lignes : « il y a 49 min · 📱 actualisée par wissbra » en entier
                        maxLines = 2, overflow = TextOverflow.Ellipsis, lineHeight = 13.sp
                    )
                }
            }
        }
    }
}
