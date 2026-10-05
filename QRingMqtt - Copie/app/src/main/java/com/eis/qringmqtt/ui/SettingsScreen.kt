package com.eis.qringmqtt.ui

import android.content.Context
import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import com.eis.qringmqtt.BuildConfig
import com.eis.qringmqtt.ble.RingManager
import com.eis.qringmqtt.data.AppState
import com.eis.qringmqtt.data.Cmd
import com.eis.qringmqtt.data.Command
import com.eis.qringmqtt.data.I18n
import com.eis.qringmqtt.data.Lang
import com.eis.qringmqtt.data.Source
import com.eis.qringmqtt.data.tr
import com.eis.qringmqtt.mqtt.MqttManager
import com.eis.qringmqtt.mqtt.NetInfo
import com.eis.qringmqtt.service.CommandProcessor
import com.eis.qringmqtt.service.RingService

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun SettingsScreen(isTv: Boolean, onScan: () -> Unit) {
    val ctx = LocalContext.current
    val p = AppState.prefs
    val info by AppState.info.collectAsState()

    var host by remember { mutableStateOf(p.host) }
    var port by remember { mutableStateOf(p.port.toString()) }
    var user by remember { mutableStateOf(p.user) }
    var pass by remember { mutableStateOf(p.password) }
    var showPass by remember { mutableStateOf(false) }
    var prefix by remember { mutableStateOf(p.topicPrefix) }
    var gateway by remember { mutableStateOf(p.gatewayName) }
    var newPin by remember { mutableStateOf("") }
    var confirmUnbind by remember { mutableStateOf(false) }

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(if (isTv) 20.dp else 12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        // ---------------- Langue
        SectionTitle(tr("set.language"))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Lang.values().forEach { l ->
                Chip(l.label, I18n.lang == l) { AppState.setLang(l); PinLock.touch() }
            }
        }

        // ---------------- Bague
        SectionTitle(tr("set.ring"))
        Panel(Modifier.fillMaxWidth()) {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                InfoLine(tr("set.name"), info.name.ifBlank { "—" })
                InfoLine(tr("set.mac"), info.mac.ifBlank { "—" })
                InfoLine(tr("set.model"), info.model.ifBlank { "—" })
                InfoLine(tr("set.fw"), info.firmware.ifBlank { "—" })
                InfoLine(tr("set.hw"), info.hardware.ifBlank { "—" })
                InfoLine(tr("m.battery"), info.battery?.let { "$it %" + if (info.charging) " " + tr("set.charging") else "" } ?: "—")
                if (info.supports.isNotEmpty()) {
                    Text(tr("set.supports"), color = C.muted, fontSize = 11.sp)
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        METRICS.filter { it.cmd.measure }.forEach { m ->
                            val ok = !info.supportsKnown || m.key in info.supports
                            Text(m.label, fontSize = 11.sp, color = if (ok) C.ok else C.muted)
                        }
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 6.dp)) {
                    BigButton(tr("set.change"), Modifier.weight(1f), onClick = onScan)
                    BigButton(tr("btn.reconnect"), Modifier.weight(1f), color = C.card2, enabled = info.mac.isNotBlank()) {
                        RingManager.reconnectNow()
                    }
                }
                if (info.mac.isNotBlank()) {
                    BigButton(tr("set.unbind"), Modifier.fillMaxWidth(), color = C.err) { confirmUnbind = true }
                }
            }
        }

        // ---------------- Broker
        SectionTitle(tr("set.broker"))
        Panel(Modifier.fillMaxWidth()) {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Field(tr("set.host"), host) { host = it; PinLock.touch() }
                Field(tr("set.port"), port, KeyboardType.Number) { port = it.filter(Char::isDigit); PinLock.touch() }
                Field(tr("set.user"), user) { user = it; PinLock.touch() }
                OutlinedTextField(
                    value = pass, onValueChange = { pass = it; PinLock.touch() },
                    label = { Text(tr("set.pass")) }, singleLine = true,
                    visualTransformation = if (showPass) VisualTransformation.None else PasswordVisualTransformation(),
                    trailingIcon = {
                        IconButton(onClick = { showPass = !showPass }) {
                            Icon(if (showPass) Icons.Filled.VisibilityOff else Icons.Filled.Visibility, tr("set.show"), tint = C.muted)
                        }
                    },
                    colors = fieldColors(), modifier = Modifier.fillMaxWidth()
                )
                Field(tr("set.prefix"), prefix) { prefix = it; PinLock.touch() }
                Field(tr("set.gateway"), gateway) { gateway = it; PinLock.touch() }
                Text(tr("set.gw_topic", "$prefix/gateway/${NetInfo.topicSafe(gateway)}/cmd"), color = C.muted, fontSize = 11.sp)
                if (info.mac.isNotBlank()) {
                    Text(tr("set.topic", "$prefix/${MqttManager.macForTopic(info.mac)}/cmd"), color = C.muted, fontSize = 11.sp)
                }
                InfoLine("LAN", NetInfo.lanIp(ctx) ?: "—")
                InfoLine("WAN", NetInfo.wanIp ?: "—")
                BigButton(tr("set.save"), Modifier.fillMaxWidth()) {
                    p.host = host; p.port = port.toIntOrNull() ?: 1883; p.user = user; p.password = pass
                    p.topicPrefix = prefix; p.gatewayName = gateway
                    RingService.restartMqtt(ctx)
                    toast(ctx, tr("set.saved"))
                }
            }
        }

        // ---------------- Tâche de fond
        SectionTitle(tr("set.background"))
        Panel(Modifier.fillMaxWidth()) {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                val ok = Background.isIgnoringBattery(ctx)
                Text(if (ok) tr("set.batt_ok") else tr("set.batt_warn"), color = if (ok) C.ok else C.warn, fontSize = 13.sp)
                BigButton(tr("set.allow_bg"), Modifier.fillMaxWidth(), color = C.card2) { Background.requestIgnoreBattery(ctx) }
                if (Background.hasAutostartPage(ctx)) {
                    BigButton(tr("set.allow_autostart"), Modifier.fillMaxWidth(), color = C.card2) { Background.openAutostart(ctx) }
                }
            }
        }

        // ---------------- PIN
        SectionTitle(tr("set.pin"))
        Panel(Modifier.fillMaxWidth()) {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Field(tr("set.new_pin"), newPin, KeyboardType.NumberPassword) {
                    newPin = it.filter(Char::isDigit).take(8); PinLock.touch()
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    BigButton(tr("set.change_pin"), Modifier.weight(1f), enabled = newPin.length >= 4) {
                        p.setPin(newPin); newPin = ""; toast(ctx, tr("set.pin_changed"))
                    }
                    BigButton(tr("set.lock"), Modifier.weight(1f), color = C.card2) { PinLock.lock() }
                }
            }
        }
        Text("Gateway RHM v${BuildConfig.VERSION_NAME}", color = C.muted, fontSize = 11.sp, modifier = Modifier.padding(8.dp))
    }

    if (confirmUnbind) {
        UnbindDialog(info.name.ifBlank { info.mac }, onCancel = { confirmUnbind = false }) {
            confirmUnbind = false
            CommandProcessor.unbind(Command(Cmd.UNBIND, null, Source.MANUAL, viaGateway = true))
            toast(ctx, tr("set.unbound"))
        }
    }
}

/** Confirmation « Dissocier la bague ? » — le focus est sur Annuler (sécurité télécommande). */
@Composable
private fun UnbindDialog(name: String, onCancel: () -> Unit, onConfirm: () -> Unit) {
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { try { focus.requestFocus() } catch (_: Exception) {} }
    Dialog(onDismissRequest = onCancel) {
        Box(
            Modifier.widthIn(max = 420.dp).background(C.surface, RoundedCornerShape(20.dp)).padding(20.dp)
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(tr("set.unbind_q", name), color = C.text, fontSize = 18.sp, fontWeight = FontWeight.Bold)
                Text(tr("set.unbind_text"), color = C.muted, fontSize = 13.sp)
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                    BigButton(tr("btn.cancel"), Modifier.weight(1f).focusRequester(focus), color = C.card2, onClick = onCancel)
                    BigButton(tr("btn.unbind"), Modifier.weight(1f), color = C.err, onClick = onConfirm)
                }
            }
        }
    }
}

@Composable
private fun Field(label: String, value: String, type: KeyboardType = KeyboardType.Text, onChange: (String) -> Unit) {
    OutlinedTextField(
        value = value, onValueChange = onChange, label = { Text(label) }, singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = type),
        visualTransformation = if (type == KeyboardType.NumberPassword) PasswordVisualTransformation() else VisualTransformation.None,
        colors = fieldColors(), modifier = Modifier.fillMaxWidth()
    )
}

@Composable
private fun fieldColors() = OutlinedTextFieldDefaults.colors(
    focusedBorderColor = C.accent, unfocusedBorderColor = C.line,
    focusedTextColor = C.text, unfocusedTextColor = C.text,
    focusedLabelColor = C.accent, unfocusedLabelColor = C.muted, cursorColor = C.accent
)

@Composable
private fun InfoLine(k: String, v: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(k, color = C.muted, fontSize = 12.sp)
        Text(v, color = C.text, fontSize = 13.sp, fontWeight = FontWeight.Medium)
    }
}

private fun toast(ctx: Context, s: String) = Toast.makeText(ctx, s, Toast.LENGTH_SHORT).show()
