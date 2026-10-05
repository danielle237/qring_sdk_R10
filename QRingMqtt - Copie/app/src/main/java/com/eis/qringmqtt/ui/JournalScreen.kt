package com.eis.qringmqtt.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.eis.qringmqtt.data.AppState
import com.eis.qringmqtt.data.LogEntry
import com.eis.qringmqtt.data.tr

@Composable
fun JournalScreen(isTv: Boolean) {
    val log by AppState.log.collectAsState()
    val pending by AppState.pendingPublish.collectAsState()
    var filter by remember { mutableIntStateOf(0) }
    val shown = when (filter) {
        1 -> log.filter { it.kind == LogEntry.Kind.IN }
        2 -> log.filter { it.kind == LogEntry.Kind.OUT || it.kind == LogEntry.Kind.MEASURING || it.kind == LogEntry.Kind.STATUS }
        3 -> log.filter { it.kind == LogEntry.Kind.ERROR }
        else -> log
    }
    Column(Modifier.fillMaxSize().padding(if (isTv) 20.dp else 12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
            Chip(tr("log.all"), filter == 0) { filter = 0 }
            Chip(tr("log.cmds"), filter == 1) { filter = 1 }
            Chip(tr("log.results"), filter == 2) { filter = 2 }
            Chip(tr("log.errors"), filter == 3) { filter = 3 }
            Spacer(Modifier.weight(1f))
            Chip(tr("log.clear"), false) { AppState.clearLog() }
        }
        Panel(Modifier.fillMaxWidth(), padding = 10.dp) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(tr("log.pending"), color = C.muted, fontSize = 12.sp)
                Text("$pending", color = if (pending > 0) C.warn else C.text, fontWeight = FontWeight.Bold, fontSize = 13.sp)
            }
        }
        if (shown.isEmpty()) {
            Text(tr("log.empty"), color = C.muted, fontSize = 12.sp, modifier = Modifier.padding(16.dp))
        }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            items(shown) { e -> LogRow(e) }
        }
    }
}

@Composable
private fun LogRow(e: LogEntry) {
    val col = when (e.kind) {
        LogEntry.Kind.IN -> C.accent
        LogEntry.Kind.OUT, LogEntry.Kind.STATUS -> C.ok
        LogEntry.Kind.MEASURING -> C.warn
        LogEntry.Kind.ERROR -> C.err
        LogEntry.Kind.INFO -> C.muted
    }
    Panel(Modifier.fillMaxWidth(), padding = 10.dp) {
        Column {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier.clip(RoundedCornerShape(6.dp)).background(col.copy(alpha = 0.16f))
                        .padding(horizontal = 7.dp, vertical = 2.dp)
                ) { Text(e.kind.label, color = col, fontSize = 10.sp, fontWeight = FontWeight.Bold) }
                Text(hhmmss(e.ts), color = C.muted, fontSize = 10.sp)
            }
            Spacer(Modifier.height(4.dp))
            Text(e.topic, color = C.muted, fontSize = 10.sp, fontFamily = FontFamily.Monospace)
            Text(e.payload, color = C.text.copy(alpha = 0.85f), fontSize = 11.sp, fontFamily = FontFamily.Monospace, maxLines = 6)
        }
    }
}
