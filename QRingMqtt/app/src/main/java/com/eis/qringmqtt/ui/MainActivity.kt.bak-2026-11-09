package com.eis.qringmqtt.ui

import android.app.UiModeManager
import android.content.Context
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Bluetooth
import androidx.compose.material.icons.filled.BluetoothDisabled
import androidx.compose.material.icons.filled.DirectionsWalk
import androidx.compose.material.icons.filled.HourglassTop
import androidx.compose.material.icons.filled.PanTool
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Verified
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.ShowChart
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.layout.ContentScale
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.eis.qringmqtt.R
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.eis.qringmqtt.ble.RingManager
import com.eis.qringmqtt.data.AppState
import com.eis.qringmqtt.data.BrokerConn
import com.eis.qringmqtt.data.Cmd
import com.eis.qringmqtt.data.Command
import com.eis.qringmqtt.data.I18n
import com.eis.qringmqtt.data.Lang
import com.eis.qringmqtt.data.RingConn
import com.eis.qringmqtt.data.Source
import com.eis.qringmqtt.data.tr
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.unit.LayoutDirection
import com.eis.qringmqtt.service.CommandProcessor
import com.eis.qringmqtt.service.RingService
import kotlinx.coroutines.delay

enum class Tab(private val k: String, val icon: ImageVector, val locked: Boolean) {
    HOME("home", Icons.Filled.Home, false),
    ACTIVITY("activity", Icons.Filled.DirectionsWalk, false),
    HISTORY("history", Icons.Filled.ShowChart, false),
    JOURNAL("journal", Icons.Filled.List, true),
    SCAN("scan", Icons.Filled.Bluetooth, true),
    SETTINGS("settings", Icons.Filled.Settings, true);

    val label: String get() = tr("tab.$k")
}

class MainActivity : ComponentActivity() {

    private val isTv: Boolean by lazy { detectTv(this) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            QRingTheme {
              // Arabe : écran de droite à gauche
              CompositionLocalProvider(
                  LocalLayoutDirection provides if (I18n.lang.rtl) LayoutDirection.Rtl else LayoutDirection.Ltr
              ) {
                Box(Modifier.fillMaxSize().background(C.bg)) {
                    var onboarding by remember {
                        mutableStateOf(!AppState.prefs.onboardingDone || !Background.hasBlePermissions(this@MainActivity))
                    }
                    if (onboarding) {
                        Onboarding(isTv) {
                            AppState.prefs.onboardingDone = true
                            onboarding = false
                            startServiceIfAllowed()
                        }
                    } else {
                        AppRoot(isTv)
                    }
                }
              }
            }
        }
    }

    override fun onStart() {
        super.onStart()
        startServiceIfAllowed()
        // La batterie est lue à chaque ouverture de l'app
        RingManager.requestBatteryOnOpen()
    }

    override fun onStop() {
        super.onStop()
        PinLock.lock()
    }

    private fun startServiceIfAllowed() {
        if (Background.hasBlePermissions(this)) RingService.start(applicationContext)
    }

    companion object {
        fun detectTv(ctx: Context): Boolean {
            val ui = ctx.getSystemService(Context.UI_MODE_SERVICE) as? UiModeManager
            return ui?.currentModeType == Configuration.UI_MODE_TYPE_TELEVISION ||
                    ctx.packageManager.hasSystemFeature(PackageManager.FEATURE_LEANBACK)
        }
    }
}

// ====================================================================== structure

@Composable
fun AppRoot(isTv: Boolean) {
    var tab by remember { mutableStateOf(Tab.HOME) }
    var scan by remember { mutableStateOf(false) }

    BackHandler(enabled = scan || tab != Tab.HOME) {
        if (scan) scan = false else tab = Tab.HOME
    }

    val content: @Composable () -> Unit = {
        if (scan) {
            ScanScreen(isTv) { scan = false }
        } else when (tab) {
            Tab.HOME -> HomeScreen(isTv)
            Tab.ACTIVITY -> ActivityScreen(isTv)
            Tab.HISTORY -> HistoryScreen(isTv)
            Tab.JOURNAL -> PinGate(tr("log.title")) { JournalScreen(isTv) }
            Tab.SCAN -> PinGate(tr("scan.title")) { ScanScreen(isTv) { tab = Tab.HOME } }
            Tab.SETTINGS -> PinGate(tr("set.title")) { SettingsScreen(isTv) { scan = true } }
        }
    }

    Box(Modifier.fillMaxSize()) {
        if (isTv) {
            Row(Modifier.fillMaxSize()) {
                SideNav(tab, onStatus = { tab = Tab.HOME; scan = false; StatusCheck.start() }) { tab = it; scan = false }
                Box(Modifier.weight(1f).fillMaxHeight()) { content() }
            }
        } else {
            Column(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding()) {
                TopTitle(if (scan) tr("tab.scan") else tab.label)
                Box(Modifier.weight(1f).fillMaxWidth()) { content() }
                BottomNav(tab) { tab = it; scan = false }
            }
        }
        if (isTv) {
            MeasureOverlay()
            ResultOverlay()
        }
        // Bague éloignée / retirée / reconnectée (TV et téléphone, au-dessus de tous les écrans)
        RingPopups(isTv)
    }
}

@Composable
private fun TopTitle(title: String) {
    val broker by AppState.broker.collectAsState()
    Row(
        Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 10.dp, bottom = 2.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Image(painterResource(R.drawable.rhm_logo), null, Modifier.size(28.dp).clip(RoundedCornerShape(7.dp)))
        Spacer(Modifier.width(10.dp))
        Text(title, color = C.text, fontSize = 22.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
        Dot(brokerColor(broker), 7.dp)
        Spacer(Modifier.width(4.dp))
        Text("MQTT", color = C.muted, fontSize = 11.sp)
    }
}

private fun brokerColor(b: BrokerConn): Color =
    if (b == BrokerConn.ONLINE) C.ok else if (b == BrokerConn.CONNECTING) C.warn else C.err

@Composable
private fun BottomNav(tab: Tab, onSelect: (Tab) -> Unit) {
    Row(
        Modifier.fillMaxWidth().background(C.surface).padding(vertical = 6.dp),
        horizontalArrangement = Arrangement.SpaceAround
    ) {
        Tab.values().forEach { t ->
            val sel = t == tab
            Column(
                Modifier.focusClick(RoundedCornerShape(12.dp)) { onSelect(t) }.padding(horizontal = 8.dp, vertical = 4.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Box {
                    Icon(t.icon, t.label, tint = if (sel) C.accent else C.muted, modifier = Modifier.size(22.dp))
                    if (t.locked) Icon(
                        Icons.Filled.Lock, null, tint = C.muted,
                        modifier = Modifier.size(10.dp).align(Alignment.BottomEnd)
                    )
                }
                Text(t.label, color = if (sel) C.accent else C.muted, fontSize = 10.sp)
            }
        }
    }
}

@Composable
private fun SideNav(tab: Tab, onStatus: () -> Unit, onSelect: (Tab) -> Unit) {
    val ring by AppState.ring.collectAsState()
    val broker by AppState.broker.collectAsState()
    val info by AppState.info.collectAsState()
    val ev by StatusCheck.evidence.collectAsState()
    val st by StatusCheck.state.collectAsState()
    val cooldown by StatusCheck.cooldownUntil.collectAsState()
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) { while (true) { now = System.currentTimeMillis(); delay(1000) } }
    val sum = StatusCheck.summary(ring, ev, st, now)

    Column(
        Modifier.width(240.dp).fillMaxHeight().background(C.surface).padding(horizontal = 14.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(3.dp)
    ) {
        // Logo + nom
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(bottom = 6.dp)) {
            Image(painterResource(R.drawable.rhm_logo), null, Modifier.size(38.dp).clip(RoundedCornerShape(9.dp)))
            Spacer(Modifier.width(10.dp))
            Text("GATEWAY RHM", color = C.text, fontSize = 18.sp, fontWeight = FontWeight.ExtraBold, maxLines = 1)
        }
        Tab.values().forEach { t ->
            NavRow(t.icon, t.label, t == tab, t.locked) { onSelect(t) }
            // « État bague » juste après Accueil : lance la vérification (clignote quand c'est possible)
            if (t == Tab.HOME) StatusNavRow(ring, st, cooldown, now, onStatus)
        }
        Spacer(Modifier.weight(1f))
        // Carte « Bague » : portée / retirée / hors portée / non vérifiée
        Panel(Modifier.fillMaxWidth(), padding = 10.dp) {
            Column {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Dot(sum.color)
                    Spacer(Modifier.width(6.dp))
                    Text(sum.title, color = C.text, fontWeight = FontWeight.Bold, fontSize = 14.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                if (info.name.isNotBlank()) {
                    Text(info.name, color = C.muted, fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 2.dp))
                }
                sidebarDetail(sum, ev)?.let { Text(it, color = C.muted, fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis) }
                // Force du signal de la bague connectée
                val rssi by com.eis.qringmqtt.ble.RssiReader.rssi.collectAsState()
                if (ring == RingConn.CONNECTED && rssi != null) {
                    Text("📶 $rssi dBm", color = C.muted, fontSize = 11.sp, maxLines = 1)
                }
            }
        }
        Panel(Modifier.fillMaxWidth(), padding = 10.dp) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Dot(brokerColor(broker))
                Spacer(Modifier.width(6.dp))
                Text(tr("lbl.broker_line", broker.label), color = C.text, fontWeight = FontWeight.SemiBold, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

/** Détail court de la carte « Bague » du menu : « vérifiée 14:41 », « depuis 14:45 »… */
private fun sidebarDetail(sum: StatusCheck.Summary, ev: StatusCheck.Evidence): String? {
    // Heure seule aujourd'hui, sinon date + heure
    fun hm(ms: Long): String {
        val t = hhmmss(ms).substring(0, 5)
        val d = java.text.SimpleDateFormat("dd/MM", java.util.Locale.FRANCE)
        val now = System.currentTimeMillis()
        return if (d.format(java.util.Date(ms)) == d.format(java.util.Date(now))) t else "${d.format(java.util.Date(ms))} $t"
    }
    return when (sum.look) {
        StatusCheck.Look.WORN -> ev.wornAtMs?.let { tr("rs.checked_at", hm(it)) }
        StatusCheck.Look.REMOVED -> ev.removedAtMs?.let { tr("rs.removed_at", hm(it)) }
        StatusCheck.Look.OUT -> ev.lostAtMs?.let { tr("rs.since", hm(it)) }
        else -> null
    }
}

@Composable
private fun NavRow(icon: ImageVector, label: String, selected: Boolean, locked: Boolean, onClick: () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .focusClick(RoundedCornerShape(12.dp), onClick = onClick)
            .background(if (selected) C.card else Color.Transparent)
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(icon, null, tint = if (selected) C.accent else if (icon == Icons.Filled.Bluetooth) Color(0xFF4A8CFF) else C.muted, modifier = Modifier.size(20.dp))
        Spacer(Modifier.width(10.dp))
        Text(label, color = if (selected) C.text else C.muted, fontSize = 15.sp, modifier = Modifier.weight(1f))
        if (locked) Icon(Icons.Filled.Lock, null, tint = C.muted, modifier = Modifier.size(14.dp))
    }
}

/** « État bague » du menu : clignote quand il est cliquable, sinon « … » ou le compte à rebours. */
@Composable
private fun StatusNavRow(ring: RingConn, st: StatusCheck.State?, cooldown: Long, now: Long, onClick: () -> Unit) {
    val can = StatusCheck.canStart(ring, st, cooldown, now)
    val shape = RoundedCornerShape(12.dp)
    // Pendant la vérification « … », pendant l'attente le compte à rebours
    val tag = when {
        st != null && !st.final -> "…"
        else -> null
    }
    Row(
        Modifier
            .fillMaxWidth()
            .focusClick(shape, can, onClick)
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(Icons.Filled.Verified, null, tint = if (can) C.ok else C.muted, modifier = Modifier.size(20.dp))
        Spacer(Modifier.width(10.dp))
        Text(tr("tab.status"), color = C.muted, fontSize = 15.sp, modifier = Modifier.weight(1f))
        if (tag != null) Text(tag, color = C.muted, fontSize = 11.sp, fontWeight = FontWeight.Bold)
    }
}

// ====================================================================== popups de la bague

/**
 * 1) « Votre bague s'est éloignée » : rouge clignotant, OK ; se ferme quand la bague revient.
 * 2) « Oups, la bague n'est pas portée » : jaune, Réessayer / Fermer ; 30 s.
 * 3) « Content de vous revoir ! » : vert, Oui, vérifier / Plus tard ; 30 s.
 */
@Composable
private fun RingPopups(isTv: Boolean) {
    val pop by StatusCheck.popup.collectAsState()
    val p = pop ?: return
    // Un popup « éloignée » se ferme tout seul quand la bague revient (StatusCheck le remplace)
    val color = when (p.kind) {
        StatusCheck.PopupKind.OUT -> C.err
        StatusCheck.PopupKind.REMOVED -> C.warn
        StatusCheck.PopupKind.RECONNECTED -> C.ok
        StatusCheck.PopupKind.RECENT, StatusCheck.PopupKind.BUSY -> C.accent
    }
    val blink = blinkPhase(p.kind == StatusCheck.PopupKind.OUT)
    val focus = remember { FocusRequester() }
    LaunchedEffect(p.atMs) { delay(150); try { focus.requestFocus() } catch (_: Exception) {} }

    Dialog(
        onDismissRequest = { StatusCheck.dismissPopup() },
        properties = DialogProperties(usePlatformDefaultWidth = false)
    ) {
        CompositionLocalProvider(
            LocalLayoutDirection provides if (I18n.lang.rtl) LayoutDirection.Rtl else LayoutDirection.Ltr
        ) {
            val shape = RoundedCornerShape(20.dp)
            Column(
                Modifier
                    .widthIn(max = if (isTv) 460.dp else 340.dp)
                    .padding(16.dp)
                    .clip(shape)
                    .background(
                        if (p.kind == StatusCheck.PopupKind.OUT) lerp(C.card, Color(0xFF3A1A20), blink) else C.card
                    )
                    .border(2.dp, if (p.kind == StatusCheck.PopupKind.OUT) color.copy(alpha = 0.35f + 0.65f * blink) else color, shape)
                    .padding(horizontal = 22.dp, vertical = 20.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                val icon = when (p.kind) {
                    StatusCheck.PopupKind.OUT -> Icons.Filled.BluetoothDisabled
                    StatusCheck.PopupKind.REMOVED -> Icons.Filled.PanTool
                    StatusCheck.PopupKind.RECONNECTED -> Icons.Filled.Verified
                    StatusCheck.PopupKind.RECENT -> Icons.Filled.Verified
                    StatusCheck.PopupKind.BUSY -> Icons.Filled.HourglassTop
                }
                Box(
                    Modifier.size(if (isTv) 64.dp else 54.dp).clip(CircleShape).background(color.copy(alpha = 0.16f)),
                    contentAlignment = Alignment.Center
                ) { Icon(icon, null, tint = color, modifier = Modifier.size(if (isTv) 36.dp else 30.dp)) }

                val title: String
                val text: String
                val question: String?
                when (p.kind) {
                    StatusCheck.PopupKind.OUT -> {
                        title = tr("pop.out_title")
                        text = tr(if (isTv) "pop.out_text_tv" else "pop.out_text_phone")
                        question = null
                    }
                    StatusCheck.PopupKind.REMOVED -> {
                        title = tr("pop.removed_title")
                        text = tr("pop.removed_text")
                        question = tr("pop.removed_q")
                    }
                    StatusCheck.PopupKind.RECONNECTED -> {
                        title = tr("pop.back_title")
                        text = tr("pop.back_text")
                        question = tr("pop.back_q")
                    }
                    StatusCheck.PopupKind.RECENT -> {
                        title = tr("pop.recent_title")
                        text = p.text ?: ""
                        question = tr("pop.recent_text")
                    }
                    StatusCheck.PopupKind.BUSY -> {
                        title = tr("pop.busy_title")
                        text = tr("pop.busy_text", p.text ?: "")
                        question = null
                    }
                }
                Text(title, color = color, fontSize = if (isTv) 24.sp else 20.sp, fontWeight = FontWeight.ExtraBold, textAlign = TextAlign.Center)
                Text(text, color = C.muted, fontSize = if (isTv) 15.sp else 13.sp, textAlign = TextAlign.Center)
                if (question != null) {
                    Text(question, color = C.text, fontSize = if (isTv) 16.sp else 14.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center)
                }
                Spacer(Modifier.height(4.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    when (p.kind) {
                        StatusCheck.PopupKind.OUT ->
                            PopupButton(tr("pop.ok"), C.err, Modifier.focusRequester(focus)) { StatusCheck.dismissPopup() }
                        StatusCheck.PopupKind.RECENT, StatusCheck.PopupKind.BUSY ->
                            PopupButton(tr("pop.ok"), C.accent, Modifier.focusRequester(focus)) { StatusCheck.dismissPopup() }
                        StatusCheck.PopupKind.REMOVED -> {
                            PopupButton("↻ " + tr("pop.retry"), C.accent, Modifier.focusRequester(focus)) {
                                StatusCheck.dismissPopup()
                                if (p.fromCheck || p.cmd == null) StatusCheck.start(force = true)
                                else CommandProcessor.submit(Command(p.cmd, null, Source.MANUAL))
                            }
                            PopupButton(tr("btn.close"), C.card2) { StatusCheck.dismissPopup() }
                        }
                        StatusCheck.PopupKind.RECONNECTED -> {
                            PopupButton("✓ " + tr("pop.back_yes"), C.ok, Modifier.focusRequester(focus)) {
                                StatusCheck.dismissPopup()
                                StatusCheck.start(force = true)
                            }
                            PopupButton(tr("btn.later"), C.card2) { StatusCheck.dismissPopup() }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun PopupButton(text: String, color: Color, modifier: Modifier = Modifier, onClick: () -> Unit) {
    Box(
        modifier
            .focusClick(RoundedCornerShape(14.dp), onClick = onClick)
            .background(color)
            .padding(horizontal = 22.dp, vertical = 12.dp)
    ) { Text(text, color = Color.White, fontWeight = FontWeight.Bold, fontSize = 15.sp) }
}

// ====================================================================== TV : mesure plein écran

@Composable
private fun MeasureOverlay() {
    val active by AppState.active.collectAsState()
    val check by StatusCheck.state.collectAsState()
    var hiddenFor by remember { mutableLongStateOf(0L) }
    val a = active ?: return
    if (hiddenFor == a.startedAtMs) return
    // Mesure lancée par « État bague » : suivie dans le bandeau, pas en plein écran
    val c = check
    if (c != null && !c.final && !c.followed && c.cmd == a.cmd) return

    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(a.startedAtMs) { while (true) { now = System.currentTimeMillis(); delay(500) } }
    val elapsed = ((now - a.startedAtMs) / 1000).toInt()
    val focus = remember { FocusRequester() }
    LaunchedEffect(a.startedAtMs) { delay(100); try { focus.requestFocus() } catch (_: Exception) {} }
    val color = METRICS.firstOrNull { it.cmd == a.cmd }?.color ?: C.spo2

    Box(Modifier.fillMaxSize().background(C.bg.copy(alpha = 0.97f)), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Text(
                if (a.source.json == "mqtt") tr("tv.server") else tr("tv.measuring"),
                color = C.muted, fontSize = 16.sp
            )
            RingProgress(elapsed / a.cmd.durationSec.toFloat(), color, Modifier.size(220.dp), 14.dp) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(a.liveText ?: a.cmd.label, color = color, fontSize = if (a.liveText != null) 44.sp else 26.sp,
                        fontWeight = FontWeight.ExtraBold, textAlign = TextAlign.Center)
                    Text("$elapsed s / ${a.cmd.durationSec} s", color = C.muted, fontSize = 14.sp)
                }
            }
            Text(tr("tv.hold"), color = C.text, fontSize = 24.sp, fontWeight = FontWeight.Bold)
            Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                Box(
                    Modifier.focusRequester(focus)
                        .focusClick(RoundedCornerShape(14.dp)) { CommandProcessor.cancelCurrent() }
                        .background(C.card).padding(horizontal = 28.dp, vertical = 12.dp)
                ) { Text(tr("btn.cancel"), color = C.text, fontWeight = FontWeight.Bold, fontSize = 16.sp) }
                Box(
                    Modifier.focusClick(RoundedCornerShape(14.dp)) { hiddenFor = a.startedAtMs }
                        .background(C.card).padding(horizontal = 28.dp, vertical = 12.dp)
                ) { Text(tr("btn.hide"), color = C.text, fontWeight = FontWeight.Bold, fontSize = 16.sp) }
            }
        }
    }
}

// ====================================================================== TV : résultat en grand

/**
 * Après une mesure (réussie ou non), le résultat reste affiché 20 s :
 * valeur, ou « Veuillez porter la bague », avec Relancer / Fermer (télécommande).
 */
@Composable
private fun ResultOverlay() {
    val res by AppState.lastResult.collectAsState()
    val active by AppState.active.collectAsState()
    var closedAt by remember { mutableLongStateOf(0L) }
    val check by StatusCheck.state.collectAsState()
    val r = res ?: return
    if (active != null || closedAt == r.atMs) return
    // Retirée / hors portée : affichés par les popups
    if (r.error == com.eis.qringmqtt.data.Err.RING_REMOVED || r.error == com.eis.qringmqtt.data.Err.RING_DISCONNECTED) return
    // Résultat de la vérification « État bague » : affiché dans le bandeau
    if (StatusCheck.isCheckResult(check, r.cmd, r.atMs)) return
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(r.atMs) { while (true) { now = System.currentTimeMillis(); delay(1000) } }
    if (now - r.atMs > 20_000) return

    val m = METRICS.firstOrNull { it.cmd == r.cmd }
    val color = when {
        !r.ok && r.error == "ring_removed" -> C.warn
        !r.ok -> C.err
        else -> m?.color ?: C.ok
    }
    val focus = remember { FocusRequester() }
    LaunchedEffect(r.atMs) { delay(100); try { focus.requestFocus() } catch (_: Exception) {} }

    Box(Modifier.fillMaxSize().background(C.bg.copy(alpha = 0.97f)), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Text("${tr("tv.result")} · ${r.cmd.label}", color = C.muted, fontSize = 18.sp)
            if (r.ok && r.values != null) {
                val main = if (r.cmd == Cmd.ALL) {
                    listOfNotNull(
                        r.values.optInt("hr").takeIf { it > 0 }?.let { "♥ $it" },
                        r.values.optInt("spo2").takeIf { it > 0 }?.let { "SpO2 $it %" },
                        r.values.optDouble("temp", 0.0).takeIf { it > 0 }?.let { "%.1f °C".format(it) }
                    ).joinToString("   ")
                } else if (m != null) {
                    "${formatReading(m, com.eis.qringmqtt.data.Reading(m.key, r.values, 0, Source.AUTO)).first} ${m.unit}"
                } else ""
                Text(main, color = color, fontSize = 64.sp, fontWeight = FontWeight.ExtraBold, textAlign = TextAlign.Center)
            } else {
                Text("⚠", color = color, fontSize = 64.sp)
                Text(
                    com.eis.qringmqtt.data.Err.label(r.error ?: ""), color = color,
                    fontSize = 30.sp, fontWeight = FontWeight.ExtraBold, textAlign = TextAlign.Center
                )
                if (r.error == "ring_removed") {
                    Text(tr("home.wear_text"), color = C.text, fontSize = 22.sp, textAlign = TextAlign.Center)
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                Box(
                    Modifier.focusRequester(focus)
                        .focusClick(RoundedCornerShape(14.dp)) {
                            closedAt = r.atMs
                            CommandProcessor.submit(Command(r.cmd, null, Source.MANUAL))
                        }
                        .background(C.accent).padding(horizontal = 28.dp, vertical = 12.dp)
                ) { Text(tr("btn.retry"), color = Color.White, fontWeight = FontWeight.Bold, fontSize = 16.sp) }
                Box(
                    Modifier.focusClick(RoundedCornerShape(14.dp)) { closedAt = r.atMs }
                        .background(C.card).padding(horizontal = 28.dp, vertical = 12.dp)
                ) { Text(tr("btn.close"), color = C.text, fontWeight = FontWeight.Bold, fontSize = 16.sp) }
            }
        }
    }
}

// ====================================================================== premier lancement

@Composable
private fun Onboarding(isTv: Boolean, onDone: () -> Unit) {
    val ctx = LocalContext.current
    var refresh by remember { mutableStateOf(0) }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { refresh++ }
    // Revenir des réglages Android met à jour l'affichage
    LaunchedEffect(Unit) { while (true) { delay(1500); refresh++ } }

    val perms = remember(refresh) { Background.hasBlePermissions(ctx) }
    val battery = remember(refresh) { Background.isIgnoringBattery(ctx) }
    val autostart = remember { Background.hasAutostartPage(ctx) }

    Box(Modifier.fillMaxSize().padding(24.dp), contentAlignment = Alignment.Center) {
        Column(
            Modifier.widthIn(max = 560.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            Text(tr("ob.welcome"), color = C.text, fontSize = 26.sp, fontWeight = FontWeight.ExtraBold)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Lang.values().forEach { l -> Chip(l.label, I18n.lang == l) { AppState.setLang(l) } }
            }
            Text(tr("ob.text"), color = C.muted, fontSize = 14.sp)
            Step(1, tr("ob.s1"), tr("ob.s1t"), perms) {
                launcher.launch(Background.runtimePermissions())
            }
            Step(2, tr("ob.s2"), tr("ob.s2t"), battery) {
                Background.requestIgnoreBattery(ctx)
            }
            if (autostart) {
                Step(3, tr("ob.s3"), tr("ob.s3t"), null) {
                    Background.openAutostart(ctx)
                }
            }
            Spacer(Modifier.height(4.dp))
            BigButton(tr("ob.continue"), Modifier.fillMaxWidth(), enabled = perms, onClick = onDone)
            if (!perms) Text(tr("ob.required"), color = C.warn, fontSize = 12.sp)
        }
    }
}

@Composable
private fun Step(n: Int, title: String, text: String, done: Boolean?, onClick: () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .focusClick(RoundedCornerShape(16.dp), onClick = onClick)
            .background(C.card)
            .padding(14.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box(
            Modifier.size(34.dp).clip(RoundedCornerShape(50))
                .background(if (done == true) C.ok else C.accent.copy(alpha = 0.25f)),
            contentAlignment = Alignment.Center
        ) { Text(if (done == true) "✓" else "$n", color = Color.White, fontWeight = FontWeight.Bold) }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(title, color = C.text, fontWeight = FontWeight.Bold, fontSize = 15.sp)
            Text(text, color = C.muted, fontSize = 12.sp)
        }
        Text(if (done == true) "OK" else tr("ob.allow"), color = if (done == true) C.ok else C.accent, fontWeight = FontWeight.Bold, fontSize = 13.sp)
    }
}
