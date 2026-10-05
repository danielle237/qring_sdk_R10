package com.eis.qringmqtt.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/** Couleurs de l'application (thème sombre, lisible sur TV). */
object C {
    val bg = Color(0xFF0F1320)
    val surface = Color(0xFF151A29)
    val card = Color(0xFF1E2438)
    val card2 = Color(0xFF252C45)
    val line = Color(0xFF2A3150)
    val text = Color(0xFFEEF1FA)
    val muted = Color(0xFF8B93B0)
    val accent = Color(0xFF6C8CFF)
    val ok = Color(0xFF3ECF8E)
    val warn = Color(0xFFFFB547)
    val err = Color(0xFFFF6B6B)

    val hr = Color(0xFFFF5D73)
    val spo2 = Color(0xFF4FC3F7)
    val temp = Color(0xFFFFA04D)
    val bp = Color(0xFFB18CFF)
    val hrv = Color(0xFF3ECF8E)
    val stress = Color(0xFFFFD23F)
    val steps = Color(0xFF3ECF8E)
    val sleep = Color(0xFF8FA3FF)
    val deep = Color(0xFF5B6CFF)
    val light = Color(0xFF8FA3FF)
    val rem = Color(0xFFC38BFF)
    val awake = Color(0xFFFFB547)
}

@Composable
fun QRingTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = C.accent,
            onPrimary = Color.White,
            background = C.bg,
            onBackground = C.text,
            surface = C.surface,
            onSurface = C.text,
            surfaceVariant = C.card,
            onSurfaceVariant = C.muted,
            error = C.err,
            outline = C.line
        ),
        content = content
    )
}
