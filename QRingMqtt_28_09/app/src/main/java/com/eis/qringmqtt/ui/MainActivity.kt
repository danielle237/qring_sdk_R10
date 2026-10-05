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
import androidx.compose.foundation.background
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
import androidx.compose.material.icons.filled.DirectionsWalk
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
            Tab.HOME -> HomeScreen(isTv) { scan = true }
            Tab.ACTIVITY -> ActivityScreen(isTv)
            Tab.HISTORY -> HistoryScreen(isTv)
            Tab.JOURNAL -> PinGate(tr("log.title")) { JournalScreen(isTv) }
            Tab.SETTINGS -> PinGate(tr("set.title")) { SettingsScreen(isTv) { scan = true } }
        }
    }

    Box(Modifier.fillMaxSize()) {
        if (isTv) {
            Row(Modifier.fillMaxSize()) {
                SideNav(tab) { tab = it; scan = false }
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
    }
}

@Composable
private fun TopTitle(title: String) {
    Text(
        title, color = C.text, fontSize = 22.sp, fontWeight = FontWeight.Bold,
        modifier = Modifier.padding(start = 16.dp, top = 10.dp, bottom = 2.dp)
    )
}

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
private fun SideNav(tab: Tab, onSelect: (Tab) -> Unit) {
    val ring by AppState.ring.collectAsState()
    val broker by AppState.broker.collectAsState()
    val info by AppState.info.collectAsState()
    Column(
        Modifier.width(230.dp).fillMaxHeight().background(C.surface).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp)
    ) {
        Text("◎ QRing", color = C.text, fontSize = 20.sp, fontWeight = FontWeight.ExtraBold, modifier = Modifier.padding(bottom = 12.dp))
        Tab.values().forEach { t ->
            val sel = t == tab
            Row(
                Modifier
                    .fillMaxWidth()
                    .focusClick(RoundedCornerShape(12.dp)) { onSelect(t) }
                    .background(if (sel) C.card else Color.Transparent)
                    .padding(horizontal = 12.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Icon(t.icon, null, tint = if (sel) C.accent else C.muted, modifier = Modifier.size(20.dp))
                Spacer(Modifier.width(10.dp))
                Text(t.label, color = if (sel) C.text else C.muted, fontSize = 15.sp, modifier = Modifier.weight(1f))
                if (t.locked) Icon(Icons.Filled.Lock, null, tint = C.muted, modifier = Modifier.size(14.dp))
            }
        }
        Spacer(Modifier.weight(1f))
        StatusPill(
            tr("lbl.ring"), if (ring == RingConn.CONNECTED) "${info.name} · ${info.battery ?: "--"}%" else ring.label,
            if (ring == RingConn.CONNECTED) C.ok else if (ring == RingConn.CONNECTING) C.warn else C.err,
            Modifier.fillMaxWidth()
        )
        StatusPill(
            tr("lbl.broker"), broker.label,
            if (broker == BrokerConn.ONLINE) C.ok else if (broker == BrokerConn.CONNECTING) C.warn else C.err,
            Modifier.fillMaxWidth()
        )
    }
}

// ====================================================================== TV : mesure plein écran

@Composable
private fun MeasureOverlay() {
    val active by AppState.active.collectAsState()
    var hiddenFor by remember { mutableLongStateOf(0L) }
    val a = active ?: return
    if (hiddenFor == a.startedAtMs) return

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
    val r = res ?: return
    if (active != null || closedAt == r.atMs) return
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
