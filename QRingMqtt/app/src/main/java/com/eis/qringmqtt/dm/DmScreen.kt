package com.eis.qringmqtt.dm

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.eis.qringmqtt.data.AppState
import com.eis.qringmqtt.data.Cmd
import com.eis.qringmqtt.data.Command
import com.eis.qringmqtt.data.Source
import com.eis.qringmqtt.service.CommandProcessor
import com.eis.qringmqtt.data.BrokerConn
import com.eis.qringmqtt.data.Reading
import com.eis.qringmqtt.data.RingConn
import com.eis.qringmqtt.data.tr
import kotlinx.coroutines.delay
import java.util.Locale

private val BG = Color(0xFF070D1C)
private val CARD = Color(0xFF111A30)
private val TXT = Color(0xFFF4F6FC)
private val MUTED = Color(0xFF9AA3BF)
private val OK = Color(0xFF3ECF8E)
private val WARN = Color(0xFFFFB547)
private val ERR = Color(0xFFFF6B6B)

private data class Vital(val type: String, val title: String, val icon: String, val unit: String, val tint: Color)

private val VITALS = listOf(
    Vital("hr", "dm.hr_t", "♥", "bpm", Color(0xFFFF5D73)),
    Vital("spo2", "dm.spo2", "💧", "%", Color(0xFF29B6F6)),
    Vital("hrv", "dm.hrv", "∿", "ms", Color(0xFF2EE59D)),
    Vital("temp", "dm.temp_t", "🌡", "°C", Color(0xFFFFA726)),
)

private fun ago(ts: Long, nowMs: Long): String {
    val s = (nowMs / 1000 - ts).coerceAtLeast(0)
    return when {
        s < 60 -> tr("dm.ago_now")
        s < 3600 -> tr("dm.ago_min", s / 60)
        s < 86400 -> tr("dm.ago_h", s / 3600)
        else -> tr("dm.ago_d", s / 86400)
    }
}

private fun valueText(v: Vital, r: Reading?): String {
    if (r == null) return "—"
    return when (v.type) {
        "temp" -> r.values.optDouble("value").takeIf { !it.isNaN() && it > 0 }?.let { String.format(Locale.ROOT, "%.1f", it) } ?: "—"
        else -> r.values.optInt("value").takeIf { it > 0 }?.toString() ?: "—"
    }
}

/**
 * Écran DM passif (maquettes du 10/11) : une ligne d'identité en haut (client · gateway · bague)
 * et 4 grandes tuiles lumineuses (fréquence cardiaque, SpO₂, HRV, température) avec la dernière
 * valeur réelle et son âge, ou « — ». Toucher une tuile lance cette mesure.
 * Appui long (≈ 1 s) sur la ligne du haut : réglages techniques (PIN si activé).
 */
@Composable
fun DmScreen(onTech: () -> Unit, onNoRing: () -> Unit = {}) {
    val ctx = LocalContext.current
    val round = DmMode.round(ctx)
    val broker by AppState.broker.collectAsState()
    val ring by AppState.ring.collectAsState()
    val info by AppState.info.collectAsState()
    val readings by AppState.readings.collectAsState()
    val active by AppState.active.collectAsState()
    val errors by AppState.errors.collectAsState()
    val sizesTick by DmMode.sizesTick.collectAsState()
    @Suppress("UNUSED_VARIABLE") val sizesVersion = sizesTick   // relu → redessin quand l'admin change les tailles
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) { while (true) { delay(15_000); now = System.currentTimeMillis() } }

    val mac = AppState.prefs.ringMac
    val latest = remember(readings, mac) {
        readings.filter { mac != null && it.ringMac.equals(mac, true) }
            .groupBy { it.type }.mapValues { it.value.maxByOrNull { r -> r.ts } }
    }
    // APK RHM V0.1 : client, site et gateway = identité fixe de l'APK
    val rhm = com.eis.qringmqtt.mqtt.RhmIdentity.RHM_ONLY
    val client = if (rhm) "${com.eis.qringmqtt.mqtt.RhmIdentity.CLIENT_CODE}  ·  Site : ${com.eis.qringmqtt.mqtt.RhmIdentity.SITE_CODE}"
        else AppState.prefs.clientName.ifBlank { "—" }
    val gw = if (rhm) com.eis.qringmqtt.mqtt.RhmIdentity.GATEWAY_ID else AppState.prefs.gatewayName
    val ringName = if (mac == null) tr("dm.no_ring") else info.name.ifBlank { mac }
    val shortRing = Regex("R\\d{2,3}_[0-9A-Fa-f]{4}").find(ringName)?.value ?: ringName
    // « Bague : R12 connectée » / « Bague : R12 déconnectée » (dans la 1ʳᵉ ligne qui défile)
    val model = com.eis.qringmqtt.ble.RingManager.modelLabel().ifBlank { shortRing }
    val ringState = if (mac == null) "${tr("dm.ring")} ${tr("dm.no_ring")}"
        else "${tr("dm.ring")} " + tr(if (ring == RingConn.CONNECTED) "dm.ring_on" else "dm.ring_off", model)
    // Mesure en cours : quelles tuiles sont concernées (ALL = les 4)
    val running: Set<String> = active?.cmd?.key?.let { k -> if (k == "all") VITALS.map { it.type }.toSet() else setOf(k) } ?: emptySet()
    // Deux petits points : broker MQTT, bague (détectée / hors portée)
    val mqttColor = when (broker) { BrokerConn.ONLINE -> OK; BrokerConn.CONNECTING -> WARN; else -> ERR }
    val ringColor = when {
        mac == null -> MUTED
        active != null || ring == RingConn.CONNECTED || ring == RingConn.IDLE -> OK
        ring == RingConn.BLUETOOTH_OFF -> ERR
        else -> WARN
    }

    BoxWithConstraints(Modifier.fillMaxSize().background(BG)) {
        val side = if (maxWidth < maxHeight) maxWidth else maxHeight
        val k = (side.value / 384f).coerceIn(0.6f, 2.2f)
        fun s(v: Float): TextUnit = (v * k).sp
        fun d(v: Float): Dp = (v * k).dp

        if (round) {
            // ---------------- DM80 (466 × 466 px ≈ 384 dp) : grille 2 × 2 qui épouse le cercle
            Column(
                Modifier.fillMaxSize().padding(horizontal = side * 0.075f, vertical = side * 0.08f),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center
            ) {
                Header("$client  ·  $gw  ·  $ringState", mqttColor, ringColor, s(17f) * DmMode.size("header"), d(7f), 1, onTech)
                Spacer(Modifier.height(d(6f)))
                val big = d(70f); val small = d(16f)
                Grid(latest, running, errors.keys, now, k, onNoRing, compact = true, gap = d(5f),
                    shapes = listOf(
                        RoundedCornerShape(topStart = big, topEnd = small, bottomEnd = small, bottomStart = small),
                        RoundedCornerShape(topStart = small, topEnd = big, bottomEnd = small, bottomStart = small),
                        RoundedCornerShape(topStart = small, topEnd = small, bottomEnd = small, bottomStart = big),
                        RoundedCornerShape(topStart = small, topEnd = small, bottomEnd = big, bottomStart = small),
                    ),
                    glowLeft = listOf(true, false, true, false),
                    modifier = Modifier.fillMaxWidth().height(side * 0.72f))
            }
        } else {
            // ---------------- DM100 (480 × 640 px ≈ 390 × 520 dp, vertical) : ligne d'identité + 2 × 2
            // Toute la surface est utilisée : marges de 4 dp, la grille prend tout le reste
            Column(Modifier.fillMaxSize().padding(4.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Header("GATEWAY RHM  ·  ${tr("dm.client")} $client  ·  ${tr("dm.gateway")} $gw — ${DmMode.label(ctx)}  ·  $ringState",
                    mqttColor, ringColor, 18.sp * DmMode.size("header"), 8.dp, 1, onTech)
                val r = RoundedCornerShape(16.dp)
                Grid(latest, running, errors.keys, now, k, onNoRing, compact = false, gap = 5.dp,
                    shapes = listOf(r, r, r, r), glowLeft = listOf(true, true, true, true),
                    modifier = Modifier.fillMaxWidth().weight(1f))
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun Header(text: String, mqtt: Color, ring: Color, size: TextUnit, dot: Dp, lines: Int, onTech: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().combinedClickable(onClick = {}, onLongClick = onTech),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center
    ) {
        Box(Modifier.size(dot).clip(CircleShape).background(mqtt))
        Spacer(Modifier.width(dot * 0.6f))
        Box(Modifier.size(dot).clip(CircleShape).background(ring))
        Spacer(Modifier.width(dot * 1.4f))
        // Première ligne qui défile (marquee) si elle est plus longue que l'écran
        Text(text, color = TXT, fontSize = size, fontWeight = FontWeight.SemiBold, maxLines = 1,
            modifier = Modifier.weight(1f, fill = false).basicMarquee(iterations = Int.MAX_VALUE, velocity = 40.dp))
    }
}

@Composable
private fun Grid(latest: Map<String, Reading?>, running: Set<String>, errs: Set<String>, now: Long, k: Float, onNoRing: () -> Unit,
                 compact: Boolean, gap: Dp, shapes: List<Shape>, glowLeft: List<Boolean>, modifier: Modifier) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(gap)) {
        for (row in 0..1) {
            Row(Modifier.fillMaxWidth().weight(1f), horizontalArrangement = Arrangement.spacedBy(gap)) {
                for (col in 0..1) {
                    val i = row * 2 + col
                    val v = VITALS[i]
                    Tile(v, latest[v.type], v.type in running, v.type in errs, now, k, onNoRing, compact, shapes[i], glowLeft[i],
                        // DM80 : contenu décalé vers l'intérieur du cercle (pas sous les coins arrondis)
                        inner = if (compact) Pair(col == 0, row == 0) else null,
                        modifier = Modifier.weight(1f).fillMaxHeight())
                }
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun Tile(v: Vital, r: Reading?, running: Boolean, failed: Boolean, now: Long, k: Float, onNoRing: () -> Unit, compact: Boolean,
                 shape: Shape, glowLeft: Boolean, inner: Pair<Boolean, Boolean>?, modifier: Modifier) {
    val value = valueText(v, r)
    val padStart = if (inner != null && inner.first) (20f * k).dp else 10.dp
    val padEnd = if (inner != null && !inner.first) (20f * k).dp else 10.dp
    val padTop = if (inner != null && inner.second) (16f * k).dp else 6.dp
    val padBottom = if (inner != null && !inner.second) (16f * k).dp else 6.dp
    BoxWithConstraints(
        modifier.clip(shape).background(CARD)
            // Lueur colorée dans le coin bas (comme les maquettes)
            .drawBehind {
                drawRect(Brush.radialGradient(
                    colors = listOf(v.tint.copy(alpha = 0.38f), Color.Transparent),
                    center = Offset(if (glowLeft) 0f else size.width, size.height),
                    radius = size.maxDimension * 0.85f
                ))
            }
            .border(1.dp, v.tint.copy(alpha = 0.35f), shape)
            // Tuile cliquable : lance cette mesure (connexion à la demande, puis bague lâchée)
            // APK RHM V0.1 : aucun bouton de mesure (tuiles non cliquables)
            .clickable(enabled = !running && !com.eis.qringmqtt.mqtt.RhmIdentity.RHM_ONLY) {
                // Pas de bague affectée : popup « choisir une bague » au lieu de lancer la mesure
                if (AppState.prefs.ringMac == null) onNoRing()
                else Cmd.from(v.type)?.let { CommandProcessor.submit(Command(it, null, Source.MANUAL)) }
            }
            .padding(start = padStart, end = padEnd, top = padTop, bottom = padBottom)
    ) {
        // Textes à l'échelle de la TUILE (plus la tuile est grande, plus les chiffres sont gros)
        val t = minOf(maxHeight.value / 140f, maxWidth.value / 210f).coerceIn(0.6f, 3f)
        fun s(x: Float): TextUnit = (x * t).sp
        fun d(x: Float): Dp = (x * t).dp
        Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.SpaceEvenly) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(d(if (compact) 34f else 38f)).clip(RoundedCornerShape(d(8f)))
                    .background(v.tint.copy(alpha = 0.22f)), contentAlignment = Alignment.Center) {
                    Text(v.icon, color = v.tint, fontSize = s(if (compact) 19f else 20f))
                }
                Spacer(Modifier.width(d(8f)))
                Text(tr(v.title), color = TXT, fontSize = s(if (compact) 22f else 24f) * DmMode.size("title"), fontWeight = FontWeight.Bold,
                    maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            Row(verticalAlignment = Alignment.Bottom) {
                Text(value, color = if (value == "—") MUTED else TXT, fontSize = s(if (compact) 58f else 66f) * DmMode.size("value"),
                    fontWeight = FontWeight.ExtraBold, maxLines = 1)
                if (value != "—") Text(" ${v.unit}", color = TXT, fontSize = s(if (compact) 24f else 26f) * DmMode.size("unit"), maxLines = 1,
                    modifier = Modifier.padding(bottom = d(if (compact) 8f else 8f)))
            }
            Text(
                when {
                    running -> tr("dm.running")
                    failed -> tr("dm.last_failed")
                    r != null -> tr("dm.last_sync") + " " + ago(r.ts, now)
                    else -> tr("dm.no_value")
                },
                color = when { running -> v.tint; failed -> WARN; else -> MUTED },
                fontSize = s(if (compact) 15f else 16f) * DmMode.size("status"), maxLines = 1,
                // Ligne d'état (synchro, en cours, échec) : défile si elle est plus longue que la tuile
                modifier = Modifier.basicMarquee(iterations = Int.MAX_VALUE, velocity = 30.dp)
            )
        }
    }
}
