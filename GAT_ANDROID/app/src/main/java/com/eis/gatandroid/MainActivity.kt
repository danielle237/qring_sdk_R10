package com.eis.gatandroid

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat

private val BG = Color(0xFF0A1220)
private val CARD = Color(0xFF111C2F)
private val LINE = Color(0xFF233553)
private val TX = Color(0xFFE6EDF7)
private val MUT = Color(0xFF8DA0BD)
private val BLUE = Color(0xFF38BDF8)
private val GREEN = Color(0xFF34D399)
private val ORANGE = Color(0xFFFBBF24)
private val RED = Color(0xFFF87171)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme(colorScheme = darkColorScheme(background = BG, surface = CARD, primary = BLUE)) {
                Box(Modifier.fillMaxSize().background(BG)) { Screen() }
            }
        }
    }
}

private fun permissions(): Array<String> {
    val l = mutableListOf<String>()
    if (Build.VERSION.SDK_INT >= 31) {
        l += Manifest.permission.BLUETOOTH_SCAN
        l += Manifest.permission.BLUETOOTH_CONNECT
    }
    l += Manifest.permission.ACCESS_FINE_LOCATION
    if (Build.VERSION.SDK_INT >= 33) l += Manifest.permission.POST_NOTIFICATIONS
    return l.toTypedArray()
}

@Composable
private fun Card(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Column(
        modifier.fillMaxWidth().padding(bottom = 10.dp)
            .background(CARD, RoundedCornerShape(12.dp))
            .border(1.dp, LINE, RoundedCornerShape(12.dp))
            .padding(12.dp)
    ) { content() }
}

@Composable
private fun Chip(text: String, color: Color) {
    Text(
        text, color = color, fontSize = 11.sp,
        modifier = Modifier.border(1.dp, color, RoundedCornerShape(99.dp)).padding(horizontal = 9.dp, vertical = 2.dp)
    )
}

@Composable
private fun Screen() {
    val ctx = LocalContext.current
    val running by GatState.running.collectAsState()
    val udp by GatState.udp.collectAsState()
    val seen by GatState.seen.collectAsState()
    val gatt by GatState.gatt.collectAsState()
    val log by GatState.log.collectAsState()
    val obs by GatState.obsSent.collectAsState()
    val lastObs by GatState.lastScanOrder.collectAsState()

    var showSettings by remember { mutableStateOf(false) }
    var tick by remember { mutableStateOf(0) } // force la relecture des réglages
    val rings = remember(tick) { Prefs.rings }

    fun startService() {
        ContextCompat.startForegroundService(ctx, Intent(ctx, GatService::class.java))
    }

    val permLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        startService()
    }

    Column(
        Modifier.fillMaxSize().statusBarsPadding().verticalScroll(rememberScrollState()).padding(16.dp)
    ) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Text("GAT_ANDROID", color = TX, fontSize = 20.sp, fontWeight = FontWeight.Bold)
            Chip(if (running) "ACTIVE" else "ARRÊTÉE", if (running) GREEN else ORANGE)
        }
        Text(
            "${Prefs.gateway} · zone : ${Prefs.zone.ifBlank { "non définie" }}",
            color = MUT, fontSize = 12.sp, modifier = Modifier.padding(top = 4.dp, bottom = 12.dp)
        )

        Card {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("Présence (scan passif, sans GATT)", color = TX, fontWeight = FontWeight.SemiBold)
                Chip(if (PassiveScanner.isActive || running) "écoute" else "off", if (running) GREEN else MUT)
            }
            Text("UDP : $udp", color = MUT, fontSize = 12.sp)
            Text("OBS envoyées : $obs · dernier envoi : $lastObs", color = MUT, fontSize = 12.sp)
        }

        Card {
            Text("Bagues surveillées", color = TX, fontWeight = FontWeight.SemiBold)
            if (rings.isEmpty()) Text("Aucune. Touchez une bague proche ci-dessous pour l'ajouter.", color = MUT, fontSize = 12.sp)
            rings.forEach { mac ->
                val s = seen.firstOrNull { it.mac == mac }
                val age = s?.let { (System.currentTimeMillis() - it.lastMs) / 1000 }
                Row(Modifier.fillMaxWidth().padding(top = 6.dp), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                    Text("${s?.name ?: "—"}  $mac", color = TX, fontSize = 13.sp)
                    if (s != null && age != null && age <= 15) Chip("${s.rssi} dBm · ${age}s", GREEN)
                    else Chip("non détectée", RED)
                }
            }
            val nearby = seen.filter { it.mac !in rings }
            if (nearby.isNotEmpty()) {
                Text("Bagues proches (toucher pour surveiller)", color = MUT, fontSize = 12.sp, modifier = Modifier.padding(top = 10.dp))
                nearby.take(6).forEach { s ->
                    Row(
                        Modifier.fillMaxWidth().clickable { Prefs.rings = rings + s.mac; tick++ }.padding(top = 6.dp),
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        Text("${s.name ?: "?"}  ${s.mac}", color = TX, fontSize = 13.sp)
                        Chip("${s.rssi} dBm", ORANGE)
                    }
                }
            }
        }

        Card {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("Mesure GATT locale (HR)", color = TX, fontWeight = FontWeight.SemiBold)
                val c = when (gatt.state) {
                    "SUCCESS" -> GREEN
                    "PRÊT" -> BLUE
                    "OUT_OF_RANGE", "ERROR", "CONNECTED_NOT_WORN" -> RED
                    else -> ORANGE
                }
                Chip(gatt.state, c)
            }
            Text(gatt.value?.let { "$it bpm" } ?: "—", color = TX, fontSize = 28.sp, fontWeight = FontWeight.Bold)
            Text(
                "Batterie : ${gatt.battery?.let { "$it %" } ?: "—"}${if (gatt.charging == true) " · en charge" else ""}",
                color = MUT, fontSize = 12.sp
            )
            if (gatt.detail.isNotBlank()) Text(gatt.detail, color = MUT, fontSize = 12.sp)
            Text("Lancée uniquement sur ordre du broker / de la carte (commande UDP).", color = MUT, fontSize = 11.sp)
        }

        Card {
            Text("Journal", color = TX, fontWeight = FontWeight.SemiBold)
            log.take(12).forEach { Text(it, color = MUT, fontSize = 11.sp) }
            if (log.isEmpty()) Text("—", color = MUT, fontSize = 11.sp)
        }

        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { showSettings = true }, modifier = Modifier.weight(1f)) { Text("Réglages") }
            if (!running) {
                Button(
                    onClick = { permLauncher.launch(permissions()) },
                    modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.buttonColors(containerColor = BLUE, contentColor = Color(0xFF04202E))
                ) { Text("Démarrer") }
            } else {
                Button(
                    onClick = { ctx.startService(Intent(ctx, GatService::class.java).setAction(GatService.ACTION_STOP)) },
                    modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.buttonColors(containerColor = RED, contentColor = Color.Black)
                ) { Text("Arrêter") }
            }
        }
        Spacer(Modifier.height(8.dp))
        TextButton(onClick = {
            try {
                val pm = ctx.getSystemService(android.content.Context.POWER_SERVICE) as PowerManager
                if (!pm.isIgnoringBatteryOptimizations(ctx.packageName)) {
                    ctx.startActivity(
                        Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:${ctx.packageName}"))
                    )
                }
            } catch (_: Exception) {}
        }) { Text("Désactiver l'économie de batterie", color = MUT, fontSize = 12.sp) }
    }

    if (showSettings) {
        var gw by remember { mutableStateOf(Prefs.gateway) }
        var zone by remember { mutableStateOf(Prefs.zone) }
        var macs by remember { mutableStateOf(Prefs.rings.joinToString(", ")) }
        AlertDialog(
            onDismissRequest = { showSettings = false },
            title = { Text("Réglages gateway") },
            text = {
                Column {
                    OutlinedTextField(gw, { gw = it }, label = { Text("Nom de la gateway") }, singleLine = true)
                    OutlinedTextField(zone, { zone = it }, label = { Text("Zone (pièce)") }, singleLine = true)
                    OutlinedTextField(macs, { macs = it }, label = { Text("MAC des bagues (séparées par des virgules)") })
                    Text("Redémarrer la gateway après un changement de nom.", color = MUT, fontSize = 11.sp)
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    Prefs.gateway = gw
                    Prefs.zone = zone
                    Prefs.rings = macs.split(",", ";", " ").map { it.trim() }.filter { it.isNotEmpty() }
                    tick++
                    showSettings = false
                }) { Text("Enregistrer") }
            },
            dismissButton = { TextButton(onClick = { showSettings = false }) { Text("Annuler") } }
        )
    }
}
