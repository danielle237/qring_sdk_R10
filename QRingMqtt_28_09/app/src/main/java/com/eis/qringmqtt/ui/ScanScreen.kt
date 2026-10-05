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
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.eis.qringmqtt.ble.RingManager
import com.eis.qringmqtt.data.AppState
import com.eis.qringmqtt.data.ScannedRing
import com.eis.qringmqtt.data.tr

@Composable
fun ScanScreen(isTv: Boolean, onDone: () -> Unit) {
    val scanning by AppState.scanning.collectAsState()
    val results by AppState.scanResults.collectAsState()
    val current by AppState.info.collectAsState()

    DisposableEffect(Unit) {
        RingManager.startScan()
        onDispose { RingManager.stopScan() }
    }

    Column(Modifier.fillMaxSize().padding(if (isTv) 20.dp else 12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.focusClick(RoundedCornerShape(50), onClick = onDone).padding(8.dp)) {
                Icon(Icons.Filled.ArrowBack, tr("btn.back"), tint = C.text)
            }
            Spacer(Modifier.width(6.dp))
            Text(tr("scan.title"), color = C.text, fontSize = 20.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            Box(Modifier.focusClick(RoundedCornerShape(50)) { RingManager.startScan() }.padding(8.dp)) {
                Icon(Icons.Filled.Refresh, tr("btn.scan"), tint = C.accent)
            }
        }
        Panel(Modifier.fillMaxWidth().height(90.dp)) {
            Row(Modifier.fillMaxSize(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.Center) {
                if (scanning) {
                    CircularProgressIndicator(color = C.accent, strokeWidth = 3.dp, modifier = Modifier.size(26.dp))
                    Spacer(Modifier.width(12.dp))
                    Text(tr("scan.searching"), color = C.muted, fontSize = 13.sp)
                } else {
                    Text(
                        if (!RingManager.isBluetoothOn()) tr("scan.bt_off")
                        else tr("scan.found", results.size),
                        color = C.muted, fontSize = 13.sp
                    )
                }
            }
        }
        SectionTitle(tr("scan.nearby"))
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(results, key = { it.mac }) { r ->
                DeviceRow(r, r.mac == current.mac) {
                    RingManager.stopScan()
                    RingManager.bind(r.mac, r.name)
                    onDone()
                }
            }
        }
    }
}

@Composable
private fun DeviceRow(r: ScannedRing, isCurrent: Boolean, onClick: () -> Unit) {
    val shape = RoundedCornerShape(14.dp)
    Box(
        Modifier
            .fillMaxWidth()
            .focusClick(shape, onClick = onClick)
            .background(C.card)
            .then(if (isCurrent) Modifier.border(1.5.dp, C.accent, shape) else Modifier)
            .padding(12.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(r.name + if (isCurrent) "  " + tr("scan.current") else "", color = C.text, fontWeight = FontWeight.Bold, fontSize = 14.sp)
                Text(r.mac, color = C.muted, fontSize = 11.sp, fontFamily = FontFamily.Monospace)
            }
            SignalBars(r.rssi)
        }
    }
}

@Composable
private fun SignalBars(rssi: Int) {
    val level = when { rssi > -60 -> 4; rssi > -70 -> 3; rssi > -80 -> 2; else -> 1 }
    Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(2.dp)) {
        for (i in 1..4) {
            Box(
                Modifier.width(4.dp).height((4 + i * 4).dp)
                    .background(if (i <= level) C.ok else C.line, RoundedCornerShape(2.dp))
            )
        }
        Spacer(Modifier.width(6.dp))
        Text("$rssi dBm", color = C.muted, fontSize = 10.sp)
    }
}
