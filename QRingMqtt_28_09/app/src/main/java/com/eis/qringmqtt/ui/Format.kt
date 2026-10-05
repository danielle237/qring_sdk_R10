package com.eis.qringmqtt.ui

import com.eis.qringmqtt.data.tr
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** « à l'instant », « il y a 5 min », « il y a 2 h », « hier », « 12/09 ». */
fun ago(tsSec: Long, nowMs: Long = System.currentTimeMillis()): String {
    val d = nowMs / 1000 - tsSec
    return when {
        d < 60 -> tr("t.now")
        d < 3600 -> tr("t.min", d / 60)
        d < 86400 -> tr("t.h", d / 3600)
        d < 2 * 86400 -> tr("t.yesterday")
        else -> SimpleDateFormat("dd/MM", Locale.FRANCE).format(Date(tsSec * 1000))
    }
}

fun hhmm(tsSec: Long): String = SimpleDateFormat("HH:mm", Locale.FRANCE).format(Date(tsSec * 1000))
fun hhmmss(tsMs: Long): String = SimpleDateFormat("HH:mm:ss", Locale.FRANCE).format(Date(tsMs))
fun dayMonth(tsSec: Long): String = SimpleDateFormat("dd/MM", Locale.FRANCE).format(Date(tsSec * 1000))

/** 26 000 s → « 7 h 13 » */
fun duration(seconds: Int): String {
    val m = seconds / 60
    return if (m >= 60) "${m / 60} h ${"%02d".format(m % 60)}" else "$m min"
}

/** 6842 → « 6 842 » */
fun thousands(n: Int): String = "%,d".format(Locale.FRANCE, n).replace(' ', ' ').replace(' ', ' ')

/** Durées de sommeil : certaines bagues donnent des minutes, d'autres des secondes. */
fun sleepSeconds(v: Int): Int = if (v in 1..1440) v * 60 else v
