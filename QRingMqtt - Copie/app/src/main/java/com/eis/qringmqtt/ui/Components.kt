package com.eis.qringmqtt.ui

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * Élément cliquable au doigt ET à la télécommande :
 * quand il a le focus (flèches), il est entouré de blanc et légèrement agrandi.
 */
@Composable
fun Modifier.focusClick(
    shape: Shape = RoundedCornerShape(16.dp),
    enabled: Boolean = true,
    onClick: () -> Unit
): Modifier {
    val source = remember { MutableInteractionSource() }
    val focused by source.collectIsFocusedAsState()
    val s by animateFloatAsState(if (focused) 1.05f else 1f, label = "focusScale")
    return this
        .scale(s)
        .border(if (focused) BorderStroke(3.dp, Color.White) else BorderStroke(0.dp, Color.Transparent), shape)
        .clip(shape)
        .clickable(interactionSource = source, indication = null, enabled = enabled, onClick = onClick)
}

@Composable
fun Panel(
    modifier: Modifier = Modifier,
    color: Color = C.card,
    padding: Dp = 12.dp,
    content: @Composable () -> Unit
) {
    Box(
        modifier
            .clip(RoundedCornerShape(16.dp))
            .background(color)
            .padding(padding)
    ) { content() }
}

@Composable
fun Dot(color: Color, size: Dp = 9.dp) {
    Box(
        Modifier
            .size(size + 6.dp)
            .clip(CircleShape)
            .background(color.copy(alpha = 0.2f)),
        contentAlignment = Alignment.Center
    ) { Box(Modifier.size(size).clip(CircleShape).background(color)) }
}

@Composable
fun StatusPill(title: String, value: String, color: Color, modifier: Modifier = Modifier) {
    Panel(modifier) {
        Column {
            Text(title, color = C.muted, fontSize = 11.sp)
            Spacer(Modifier.height(3.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Dot(color)
                Spacer(Modifier.width(6.dp))
                Text(value, color = C.text, fontWeight = FontWeight.SemiBold, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

@Composable
fun IconBadge(icon: ImageVector, color: Color, size: Dp = 24.dp) {
    Box(
        Modifier.size(size).clip(RoundedCornerShape(7.dp)).background(color.copy(alpha = 0.18f)),
        contentAlignment = Alignment.Center
    ) { Icon(icon, null, tint = color, modifier = Modifier.size(size * 0.62f)) }
}

@Composable
fun SectionTitle(text: String, modifier: Modifier = Modifier) {
    Text(
        text.uppercase(), color = C.muted, fontSize = 11.sp, letterSpacing = 1.sp,
        modifier = modifier.padding(start = 4.dp, top = 6.dp, bottom = 4.dp)
    )
}

@Composable
fun BigButton(
    text: String,
    modifier: Modifier = Modifier,
    color: Color = C.accent,
    enabled: Boolean = true,
    icon: ImageVector? = null,
    onClick: () -> Unit
) {
    Box(
        modifier
            .focusClick(RoundedCornerShape(14.dp), enabled, onClick)
            .background(if (enabled) color else C.card2)
            .padding(horizontal = 18.dp, vertical = 13.dp),
        contentAlignment = Alignment.Center
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (icon != null) {
                Icon(icon, null, tint = Color.White, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(8.dp))
            }
            Text(text, color = if (enabled) Color.White else C.muted, fontWeight = FontWeight.Bold, fontSize = 14.sp)
        }
    }
}

@Composable
fun Chip(text: String, selected: Boolean, onClick: () -> Unit) {
    Box(
        Modifier
            .focusClick(RoundedCornerShape(50), onClick = onClick)
            .background(if (selected) C.accent else C.card)
            .padding(horizontal = 12.dp, vertical = 6.dp)
    ) {
        Text(text, color = if (selected) Color.White else C.muted, fontSize = 12.sp)
    }
}

/** Anneau de progression (batterie, objectif de pas, mesure en cours). */
@Composable
fun RingProgress(
    fraction: Float,
    color: Color,
    modifier: Modifier = Modifier,
    stroke: Dp = 6.dp,
    content: @Composable () -> Unit = {}
) {
    Box(modifier, contentAlignment = Alignment.Center) {
        Canvas(Modifier.matchParentSize()) {
            val sw = stroke.toPx()
            val d = size.minDimension - sw
            val tl = Offset((size.width - d) / 2, (size.height - d) / 2)
            drawArc(C.line, 0f, 360f, false, tl, Size(d, d), style = Stroke(sw))
            drawArc(color, -90f, 360f * fraction.coerceIn(0f, 1f), false, tl, Size(d, d), style = Stroke(sw, cap = StrokeCap.Round))
        }
        content()
    }
}

/** Courbe simple. Points = (x, y) déjà triés par x. */
@Composable
fun LineChart(
    points: List<Pair<Float, Float>>,
    color: Color,
    modifier: Modifier = Modifier,
    minY: Float? = null,
    maxY: Float? = null
) {
    Canvas(modifier) {
        // grille
        for (i in 0..3) {
            val y = size.height * i / 3f
            drawLine(C.line, Offset(0f, y), Offset(size.width, y), 1f)
        }
        if (points.isEmpty()) return@Canvas
        val xs = points.map { it.first }
        val ys = points.map { it.second }
        val x0 = xs.min(); val x1 = xs.max().let { if (it == x0) x0 + 1 else it }
        var y0 = minY ?: ys.min(); var y1 = maxY ?: ys.max()
        if (y1 - y0 < 1f) { y0 -= 1f; y1 += 1f }
        val pad = (y1 - y0) * 0.1f
        y0 -= pad; y1 += pad
        fun px(x: Float) = (x - x0) / (x1 - x0) * size.width
        fun py(y: Float) = size.height - (y - y0) / (y1 - y0) * size.height
        if (points.size == 1) {
            drawCircle(color, 6f, Offset(size.width / 2, py(points[0].second)))
            return@Canvas
        }
        val line = Path()
        val fill = Path()
        points.forEachIndexed { i, (x, y) ->
            if (i == 0) { line.moveTo(px(x), py(y)); fill.moveTo(px(x), size.height); fill.lineTo(px(x), py(y)) }
            else { line.lineTo(px(x), py(y)); fill.lineTo(px(x), py(y)) }
        }
        fill.lineTo(px(points.last().first), size.height)
        fill.close()
        drawPath(fill, color.copy(alpha = 0.13f))
        drawPath(line, color, style = Stroke(width = 5f, cap = StrokeCap.Round))
        points.takeLast(1).forEach { (x, y) -> drawCircle(color, 7f, Offset(px(x), py(y))) }
    }
}

/** Barres (ex. pas par heure). */
@Composable
fun BarChart(values: List<Int>, color: Color, modifier: Modifier = Modifier) {
    Canvas(modifier) {
        if (values.isEmpty()) return@Canvas
        val max = (values.maxOrNull() ?: 1).coerceAtLeast(1).toFloat()
        val slot = size.width / values.size
        val w = slot * 0.7f
        values.forEachIndexed { i, v ->
            val h = (v / max * size.height).coerceAtLeast(3f)
            drawRoundRect(
                color = if (v > 0) color else C.line,
                topLeft = Offset(i * slot + (slot - w) / 2, size.height - h),
                size = Size(w, h),
                cornerRadius = CornerRadius(3f, 3f)
            )
        }
    }
}

/** Barre segmentée (phases de sommeil, sédentarité). */
@Composable
fun SegmentBar(segments: List<Pair<Float, Color>>, modifier: Modifier = Modifier) {
    Canvas(modifier) {
        val total = segments.sumOf { it.first.toDouble() }.toFloat()
        if (total <= 0f) return@Canvas
        var x = 0f
        segments.forEach { (w, col) ->
            val ww = w / total * size.width
            drawRect(col, Offset(x, 0f), Size(ww, size.height))
            x += ww
        }
    }
}

@Composable
fun Legend(items: List<Pair<String, Color>>) {
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        items.forEach { (t, col) ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(9.dp).clip(RoundedCornerShape(2.dp)).background(col))
                Spacer(Modifier.width(4.dp))
                Text(t, color = C.muted, fontSize = 11.sp)
            }
        }
    }
}
