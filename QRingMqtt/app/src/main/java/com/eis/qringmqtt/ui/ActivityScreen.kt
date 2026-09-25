package com.eis.qringmqtt.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.eis.qringmqtt.data.AppState
import com.eis.qringmqtt.data.Cmd
import com.eis.qringmqtt.data.Command
import com.eis.qringmqtt.data.RingConn
import com.eis.qringmqtt.data.Source
import com.eis.qringmqtt.data.tr
import com.eis.qringmqtt.service.CommandProcessor
import org.json.JSONObject

private const val STEP_GOAL = 10_000

@Composable
fun ActivityScreen(isTv: Boolean) {
    val readings by AppState.readings.collectAsState()
    val ring by AppState.ring.collectAsState()
    val syncing by AppState.syncing.collectAsState()
    val info by AppState.info.collectAsState()
    val mine = readings.filter { it.ringMac == info.mac }
    val steps = mine.lastOrNull { it.type == "steps" }?.values
    val sleep = mine.lastOrNull { it.type == "sleep" }?.values
    val sed = mine.lastOrNull { it.type == "sedentary" }?.values
    val work = mine.lastOrNull { it.type == "workouts" }?.values

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(if (isTv) 20.dp else 12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        BigButton(
            if (syncing != null) tr("act.syncing", syncing?.label) else tr("act.sync"),
            Modifier.fillMaxWidth(),
            enabled = ring == RingConn.CONNECTED && syncing == null,
            icon = Icons.Filled.Sync
        ) {
            listOf(Cmd.STEPS, Cmd.SLEEP, Cmd.SEDENTARY, Cmd.WORKOUTS).forEach {
                CommandProcessor.submit(Command(it, null, Source.MANUAL))
            }
        }

        // ---- Pas
        Panel(Modifier.fillMaxWidth()) {
            Column {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    val n = steps?.optInt("steps") ?: 0
                    RingProgress(n / STEP_GOAL.toFloat(), C.steps, Modifier.size(92.dp), 8.dp) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Text(thousands(n), color = C.text, fontWeight = FontWeight.ExtraBold, fontSize = 17.sp)
                            Text(tr("act.goal", thousands(STEP_GOAL)), color = C.muted, fontSize = 9.sp)
                        }
                    }
                    Spacer(Modifier.width(16.dp))
                    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Stat(tr("act.distance"), steps?.let { "%.1f km".format(it.optInt("distance") / 1000.0) } ?: "--")
                        Stat(tr("act.calories"), steps?.let { "${it.optInt("calories")} kcal" } ?: "--")
                        Stat(tr("act.active"), steps?.optInt("activeSeconds")?.takeIf { it > 0 }?.let { duration(it) } ?: "--")
                    }
                }
                val hourly = steps?.optJSONArray("hourly")
                if (hourly != null && hourly.length() > 0) {
                    Spacer(Modifier.height(12.dp))
                    Text(tr("act.per_hour"), color = C.text, fontWeight = FontWeight.SemiBold, fontSize = 12.sp)
                    Spacer(Modifier.height(6.dp))
                    BarChart((0 until hourly.length()).map { hourly.optInt(it) }, C.steps, Modifier.fillMaxWidth().height(60.dp))
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        listOf("0h", "6h", "12h", "18h", "24h").forEach { Text(it, color = C.muted, fontSize = 9.sp) }
                    }
                }
            }
        }

        // ---- Sommeil
        Panel(Modifier.fillMaxWidth()) {
            Column {
                val total = sleep?.let { sleepSeconds(it.optInt("totalSeconds")) } ?: 0
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("${tr("m.sleep")} · ${if (total > 0) duration(total) else "--"}", color = C.text, fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                    sleepRange(sleep)?.let { Text(it, color = C.muted, fontSize = 11.sp) }
                }
                Spacer(Modifier.height(8.dp))
                val segs = sleepSegments(sleep)
                if (segs.isNotEmpty()) {
                    SegmentBar(segs, Modifier.fillMaxWidth().height(18.dp))
                    Spacer(Modifier.height(8.dp))
                }
                if (sleep != null) {
                    Legend(
                        listOf(
                            "${tr("act.deep")} ${duration(sleepSeconds(sleep.optInt("deepSeconds")))}" to C.deep,
                            "${tr("act.light")} ${duration(sleepSeconds(sleep.optInt("lightSeconds")))}" to C.light,
                            "${tr("act.rem")} ${duration(sleepSeconds(sleep.optInt("remSeconds")))}" to C.rem,
                            "${tr("act.awake")} ${duration(sleepSeconds(sleep.optInt("awakeSeconds")))}" to C.awake
                        )
                    )
                } else Text(tr("act.no_data"), color = C.muted, fontSize = 12.sp)
            }
        }

        // ---- Sédentarité
        Panel(Modifier.fillMaxWidth()) {
            Column {
                Text(tr("m.sedentary"), color = C.text, fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                Spacer(Modifier.height(6.dp))
                if (sed != null) {
                    Row(horizontalArrangement = Arrangement.spacedBy(18.dp)) {
                        Stat(tr("act.still"), duration(sed.optInt("stillMinutes") * 60))
                        Stat(tr("act.alerts"), duration(sed.optInt("sedentaryMinutes") * 60))
                        Stat(tr("act.moving"), duration(sed.optInt("movingMinutes") * 60))
                    }
                } else Text(tr("gen.no_data"), color = C.muted, fontSize = 12.sp)
            }
        }

        // ---- Entraînements
        Panel(Modifier.fillMaxWidth()) {
            Column {
                Text(tr("m.workouts"), color = C.text, fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                Spacer(Modifier.height(6.dp))
                val arr = work?.optJSONArray("workouts")
                if (arr == null || arr.length() == 0) {
                    Text(tr("act.no_workouts"), color = C.muted, fontSize = 12.sp)
                } else {
                    for (i in 0 until arr.length()) {
                        val w = arr.getJSONObject(i)
                        Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text(
                                "${tr("act.session")} · ${duration(w.optInt("durationSeconds"))}" +
                                        (w.optInt("distance").takeIf { it > 0 }?.let { " · %.1f km".format(it / 1000.0) } ?: "") +
                                        (w.optInt("hrAvg").takeIf { it > 0 }?.let { " · ♥ $it" } ?: ""),
                                color = C.text, fontSize = 13.sp
                            )
                            Text(w.optString("startText"), color = C.muted, fontSize = 11.sp)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun Stat(label: String, value: String, color: Color = C.text) {
    Column {
        Text(label, color = C.muted, fontSize = 10.sp)
        Text(value, color = color, fontWeight = FontWeight.Bold, fontSize = 15.sp)
    }
}

private fun sleepRange(s: JSONObject?): String? {
    if (s == null) return null
    val st = s.optLong("start"); val en = s.optLong("end")
    fun fmt(v: Long): String = when {
        v > 1_000_000_000_000L -> hhmm(v / 1000)      // millisecondes
        v > 1_000_000_000L -> hhmm(v)                 // secondes
        v in 0..1440 -> "%02d:%02d".format(v / 60, v % 60) // minutes depuis minuit
        else -> "?"
    }
    return if (st > 0 && en > 0) "${fmt(st)} → ${fmt(en)}" else null
}

private fun sleepSegments(s: JSONObject?): List<Pair<Float, Color>> {
    if (s == null) return emptyList()
    fun col(t: String) = when (t) { "deep" -> C.deep; "light" -> C.light; "rem" -> C.rem; "awake" -> C.awake; else -> C.line }
    s.optJSONArray("sequence")?.let { seq ->
        return (0 until seq.length()).map { seq.getJSONObject(it) }.map { it.optInt("minutes").toFloat() to col(it.optString("type")) }
    }
    s.optJSONArray("phases")?.let { ph ->
        return (0 until ph.length()).map { ph.getJSONObject(it) }
            .map { (it.optLong("end") - it.optLong("start")).coerceAtLeast(0).toFloat() to col(it.optString("type")) }
    }
    return emptyList()
}
