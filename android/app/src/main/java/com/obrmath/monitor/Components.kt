package com.obrmath.monitor

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.json.JSONObject

enum class BadgeTone {
    BULLISH,
    BEARISH,
    WARNING,
    INFO,
    PAPER,
    NEUTRAL
}

@Composable
internal fun toneColors(tone: BadgeTone): Pair<Color, Color> {
    val p = LocalObrPalette.current
    return when (tone) {
        BadgeTone.BULLISH -> p.bullish to p.bullishContainer
        BadgeTone.BEARISH -> p.bearish to p.bearishContainer
        BadgeTone.WARNING -> p.warning to p.warningContainer
        BadgeTone.INFO -> p.primaryAccent to p.primaryContainer
        BadgeTone.PAPER -> p.paperChannel to p.paperContainer
        BadgeTone.NEUTRAL -> p.textSecondary to p.cardElevated
    }
}

@Composable
internal fun StatusPill(
    text: String,
    tone: BadgeTone = BadgeTone.NEUTRAL,
    showDot: Boolean = true,
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null
) {
    val (fg, bg) = toneColors(tone)
    val baseMod = modifier
        .clip(RoundedCornerShape(50))
        .background(bg)
        .border(1.dp, fg.copy(alpha = 0.35f), RoundedCornerShape(50))
        .let { if (onClick != null) it.clickable(onClick = onClick) else it }
        .padding(horizontal = 10.dp, vertical = 4.dp)

    Row(
        modifier = baseMod,
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(5.dp)
    ) {
        if (showDot) {
            Box(
                modifier = Modifier
                    .size(6.dp)
                    .clip(CircleShape)
                    .background(fg)
            )
        }
        Text(
            text = text,
            color = fg,
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.Bold,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )
    }
}

@Composable
internal fun KpiMetricCard(
    label: String,
    value: String,
    subtitle: String,
    tone: BadgeTone = BadgeTone.INFO,
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null
) {
    val p = LocalObrPalette.current
    val (accent, _) = toneColors(tone)
    Surface(
        modifier = modifier
            .clip(RoundedCornerShape(12.dp))
            .let { if (onClick != null) it.clickable(onClick = onClick) else it },
        shape = RoundedCornerShape(12.dp),
        color = p.cardContainer,
        border = BorderStroke(1.dp, p.borderSubtle)
    ) {
        Column {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(3.dp)
                    .background(accent)
            )
            Column(
                modifier = Modifier.padding(12.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                Text(
                    text = label,
                    color = p.textMuted,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Text(
                    text = value,
                    color = p.textPrimary,
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Bold,
                    fontSize = 18.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Text(
                    text = subtitle,
                    color = p.textSecondary,
                    style = MaterialTheme.typography.labelSmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
        }
    }
}

@Composable
internal fun TerminalSectionCard(
    title: String,
    subtitle: String? = null,
    badgeText: String? = null,
    badgeTone: BadgeTone = BadgeTone.INFO,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null,
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit
) {
    val p = LocalObrPalette.current
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(14.dp),
        color = p.cardContainer,
        border = BorderStroke(1.dp, p.borderSubtle)
    ) {
        Column(
            modifier = Modifier.padding(15.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        Text(
                            text = title,
                            color = p.textPrimary,
                            style = MaterialTheme.typography.titleMedium
                        )
                        if (!badgeText.isNullOrBlank()) {
                            StatusPill(text = badgeText, tone = badgeTone, showDot = true)
                        }
                    }
                    if (!subtitle.isNullOrBlank()) {
                        Spacer(Modifier.height(2.dp))
                        Text(
                            text = subtitle,
                            color = p.textMuted,
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                }
                if (actionLabel != null && onAction != null) {
                    FilledTonalButton(
                        onClick = onAction,
                        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                        modifier = Modifier.height(32.dp)
                    ) {
                        Text(actionLabel, style = MaterialTheme.typography.labelSmall)
                    }
                }
            }
            HorizontalDivider(color = p.borderSubtle.copy(alpha = 0.6f))
            content()
        }
    }
}

@Composable
internal fun SegmentedControlBar(
    options: List<Pair<String, String>>,
    selectedKey: String,
    onSelect: (String) -> Unit,
    modifier: Modifier = Modifier
) {
    val p = LocalObrPalette.current
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(10.dp),
        color = p.surface,
        border = BorderStroke(1.dp, p.borderSubtle)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(4.dp),
            horizontalArrangement = Arrangement.spacedBy(4.dp)
        ) {
            options.forEach { (key, label) ->
                val selected = key == selectedKey
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .clip(RoundedCornerShape(8.dp))
                        .background(if (selected) p.primaryContainer else Color.Transparent)
                        .border(
                            width = if (selected) 1.dp else 0.dp,
                            color = if (selected) p.primaryAccent.copy(alpha = 0.5f) else Color.Transparent,
                            shape = RoundedCornerShape(8.dp)
                        )
                        .clickable { onSelect(key) }
                        .padding(vertical = 8.dp, horizontal = 4.dp),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = label,
                        color = if (selected) p.primaryAccent else p.textMuted,
                        style = MaterialTheme.typography.labelLarge,
                        fontWeight = if (selected) FontWeight.Bold else FontWeight.Medium,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }
            }
        }
    }
}

@Composable
internal fun FilterChipRow(
    options: List<Pair<String, String>>,
    selectedKey: String,
    onSelect: (String) -> Unit
) {
    val p = LocalObrPalette.current
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        options.forEach { (key, label) ->
            val selected = key == selectedKey
            FilterChip(
                selected = selected,
                onClick = { onSelect(key) },
                label = {
                    Text(
                        text = label,
                        style = MaterialTheme.typography.labelSmall,
                        fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal
                    )
                },
                colors = FilterChipDefaults.filterChipColors(
                    selectedContainerColor = p.primaryContainer,
                    selectedLabelColor = p.primaryAccent
                )
            )
        }
    }
}

@Composable
internal fun RiskGaugeBar(
    label: String,
    valueText: String,
    progress: Float,
    tone: BadgeTone = BadgeTone.INFO
) {
    val p = LocalObrPalette.current
    val (fg, _) = toneColors(tone)
    val clamped = progress.coerceIn(0f, 1f)
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(text = label, color = p.textSecondary, style = MaterialTheme.typography.bodySmall)
            Text(
                text = valueText,
                color = p.textPrimary,
                fontFamily = FontFamily.Monospace,
                style = MaterialTheme.typography.labelMedium
            )
        }
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(6.dp)
                .clip(RoundedCornerShape(4.dp))
                .background(p.cardElevated)
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth(clamped)
                    .fillMaxHeight()
                    .clip(RoundedCornerShape(4.dp))
                    .background(fg)
            )
        }
    }
}

@Composable
internal fun KeyValueMetricRow(
    label: String,
    value: String,
    valueColor: Color? = null,
    monospace: Boolean = true
) {
    val p = LocalObrPalette.current
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 2.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text = label,
            color = p.textMuted,
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.weight(1f)
        )
        Text(
            text = value,
            color = valueColor ?: p.textPrimary,
            style = if (monospace) MaterialTheme.typography.labelMedium else MaterialTheme.typography.bodySmall,
            fontWeight = FontWeight.SemiBold
        )
    }
}

@Composable
internal fun DualChannelControlStrip(
    modes: JSONObject?,
    busy: Boolean,
    onRequestModeChange: (String) -> Unit,
    onJumpTrading: () -> Unit
) {
    val p = LocalObrPalette.current
    val paperOn = modes?.optBoolean("paper_enabled") == true
    val liveOn = modes?.optBoolean("live_enabled") == true
    val liveAvail = modes?.optBoolean("live_available") == true
    val controlOk = modes?.optBoolean("control_configured") == true
    val sharedCount = modes?.optJSONObject("live_ledger")?.optInt("received_signals_count", 0) ?: 0

    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        color = p.cardElevated,
        border = BorderStroke(1.dp, p.borderSubtle)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.weight(1f)
            ) {
                StatusPill(
                    text = if (paperOn) "模拟盘: 开启" else "模拟盘: 关闭",
                    tone = if (paperOn) BadgeTone.PAPER else BadgeTone.NEUTRAL,
                    onClick = if (!busy && controlOk) {
                        { onRequestModeChange(if (paperOn) "PAPER_OFF" else "PAPER_ON") }
                    } else null
                )
                StatusPill(
                    text = if (liveOn) "实盘: 开启" else "实盘: 关闭",
                    tone = if (liveOn) BadgeTone.BULLISH else BadgeTone.NEUTRAL,
                    onClick = if (!busy && controlOk && liveAvail) {
                        { onRequestModeChange(if (liveOn) "LIVE_OFF" else "LIVE_ON") }
                    } else {
                        { onJumpTrading() }
                    }
                )
            }
            Text(
                text = "双通道共享信号 · $sharedCount",
                color = p.textMuted,
                style = MaterialTheme.typography.labelSmall,
                modifier = Modifier.clickable { onJumpTrading() }
            )
        }
    }
}

@Composable
internal fun WalletFlowArchitectureCard(
    modes: JSONObject?,
    onEditLiveConfig: () -> Unit,
    onToggleLive: () -> Unit
) {
    val p = LocalObrPalette.current
    val ledger = modes?.optJSONObject("live_ledger")
    val reconciled = ledger?.optBoolean("reconciled") == true
    val mainFree = ledger?.optString("main_usdc_free", "0.00") ?: "0.00"
    val mainRes = ledger?.optString("main_usdc_reserved", "0.00") ?: "0.00"
    val cardSettle = ledger?.optString("card_settlement_usdc", "0.00") ?: "0.00"
    val extCount = ledger?.optJSONObject("external_positions")?.length() ?: 0
    val liveOn = modes?.optBoolean("live_enabled") == true

    TerminalSectionCard(
        title = "实盘独立账本与资金流路由",
        subtitle = "账本空间：${ledger?.optString("account_namespace") ?: "LIVE_EQUITY_MAIN_USDC_CARD"} · 与模拟盘完全物理隔离",
        badgeText = if (reconciled) "已对账" else "待对账",
        badgeTone = if (reconciled) BadgeTone.BULLISH else BadgeTone.WARNING,
        actionLabel = "配置实盘参数",
        onAction = onEditLiveConfig
    ) {
        // Visual 3-stage wallet routing diagram
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(10.dp))
                .background(p.cardElevated)
                .border(1.dp, p.borderSubtle, RoundedCornerShape(10.dp))
                .padding(10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Column(
                modifier = Modifier.weight(1f),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                StatusPill("1. MAIN 现货", BadgeTone.INFO, showDot = false)
                Spacer(Modifier.height(4.dp))
                Text(
                    text = formatUsd(mainFree),
                    color = p.textPrimary,
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Bold,
                    fontSize = 14.sp
                )
                Text("USDC 买入支付", color = p.textMuted, fontSize = 10.sp)
            }
            Text("──▶", color = p.primaryAccent, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold)
            Column(
                modifier = Modifier.weight(1f),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                StatusPill("2. 美股/ETF", if (liveOn) BadgeTone.BULLISH else BadgeTone.NEUTRAL, showDot = true)
                Spacer(Modifier.height(4.dp))
                Text(
                    text = "预占 ${formatUsd(mainRes)}",
                    color = p.textPrimary,
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Bold,
                    fontSize = 13.sp
                )
                Text("禁止代币化/衍生品", color = p.textMuted, fontSize = 10.sp)
            }
            Text("──▶", color = p.bullish, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold)
            Column(
                modifier = Modifier.weight(1f),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                StatusPill("3. CARD 钱包", BadgeTone.BULLISH, showDot = false)
                Spacer(Modifier.height(4.dp))
                Text(
                    text = formatUsd(cardSettle),
                    color = p.bullish,
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Bold,
                    fontSize = 14.sp
                )
                Text("卖出结算(不划转)", color = p.textMuted, fontSize = 10.sp)
            }
        }

        KeyValueMetricRow(
            label = "对账安全门控",
            value = if (reconciled) "已完成启动对账 (允许执行)" else "未完成对账 (禁止实盘自动开仓)",
            valueColor = if (reconciled) p.bullish else p.warning,
            monospace = false
        )
        KeyValueMetricRow(
            label = "手工既有持仓隔离",
            value = "$extCount 个标的 (策略绝不接管或平仓)"
        )
        KeyValueMetricRow(
            label = "实盘共享信号累计接收",
            value = "${ledger?.optInt("received_signals_count", 0) ?: 0} 次"
        )
    }
}

@Composable
internal fun BlockerDiagnosticCard(diagnostic: BlockerDiagnostic) {
    val p = LocalObrPalette.current
    val tone = when (diagnostic.severity) {
        "CRITICAL" -> BadgeTone.BEARISH
        "WARNING" -> BadgeTone.WARNING
        else -> BadgeTone.INFO
    }
    val (accent, container) = toneColors(tone)
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(10.dp),
        color = p.cardElevated,
        border = BorderStroke(1.dp, accent.copy(alpha = 0.4f))
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = diagnostic.title,
                    color = p.textPrimary,
                    style = MaterialTheme.typography.titleSmall,
                    modifier = Modifier.weight(1f)
                )
                StatusPill(text = diagnostic.code, tone = tone, showDot = false)
            }
            Text(
                text = diagnostic.explanation,
                color = p.textSecondary,
                style = MaterialTheme.typography.bodySmall
            )
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(6.dp))
                    .background(container.copy(alpha = 0.5f))
                    .padding(horizontal = 8.dp, vertical = 4.dp)
            ) {
                Text(
                    text = "建议动作：${diagnostic.actionHint}",
                    color = accent,
                    style = MaterialTheme.typography.labelSmall,
                    fontFamily = FontFamily.Default
                )
            }
        }
    }
}

@Composable
internal fun EnhancedEquityChart(
    points: List<JSONObject>,
    scenarioType: String = "TAKE_PROFIT"
) {
    val p = LocalObrPalette.current
    val values = points.mapNotNull { it.optString("equity").toDoubleOrNull() }.filter { it.isFinite() }
    if (values.size < 2) return

    val startVal = values.first()
    val endVal = values.last()
    val low = values.min()
    val high = values.max()
    val span = (high - low).coerceAtLeast(0.01)
    val isProfit = endVal >= startVal
    val lineColor = when {
        scenarioType == "TAKE_PROFIT" || isProfit -> p.bullish
        scenarioType == "STOP_LOSS" -> p.warning
        else -> p.bearish
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(10.dp))
            .background(p.cardElevated)
            .border(1.dp, p.borderSubtle, RoundedCornerShape(10.dp))
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = "盘口估值权益曲线",
                color = p.textSecondary,
                style = MaterialTheme.typography.labelLarge
            )
            Text(
                text = "区间 $${"%.2f".format(low)} — $${"%.2f".format(high)}",
                color = p.textMuted,
                style = MaterialTheme.typography.labelSmall
            )
        }

        Canvas(
            modifier = Modifier
                .fillMaxWidth()
                .height(130.dp)
        ) {
            val w = size.width
            val h = size.height
            val gridColor = p.borderSubtle.copy(alpha = 0.5f)

            // Draw 3 horizontal reference grid lines
            listOf(0.15f, 0.5f, 0.85f).forEach { ratio ->
                drawLine(
                    color = gridColor,
                    start = Offset(0f, h * ratio),
                    end = Offset(w, h * ratio),
                    strokeWidth = 1f
                )
            }

            // Build line and fill path
            val linePath = Path()
            val fillPath = Path()
            val coords = values.mapIndexed { idx, v ->
                val x = w * idx / (values.size - 1)
                val y = (h * 0.1f) + (h * 0.8f) * (1f - ((v - low) / span).toFloat())
                Offset(x, y)
            }

            coords.forEachIndexed { idx, pt ->
                if (idx == 0) {
                    linePath.moveTo(pt.x, pt.y)
                    fillPath.moveTo(pt.x, h)
                    fillPath.lineTo(pt.x, pt.y)
                } else {
                    linePath.lineTo(pt.x, pt.y)
                    fillPath.lineTo(pt.x, pt.y)
                }
            }
            fillPath.lineTo(coords.last().x, h)
            fillPath.close()

            drawPath(
                path = fillPath,
                brush = Brush.verticalGradient(
                    colors = listOf(lineColor.copy(alpha = 0.28f), lineColor.copy(alpha = 0.02f))
                )
            )
            drawPath(
                path = linePath,
                color = lineColor,
                style = Stroke(width = 5f, cap = StrokeCap.Round)
            )

            // Draw start and end markers
            drawCircle(color = p.textMuted, radius = 5f, center = coords.first())
            drawCircle(color = lineColor, radius = 7f, center = coords.last())
        }

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Text(
                text = "起点 $${"%.2f".format(startVal)}",
                color = p.textMuted,
                style = MaterialTheme.typography.labelSmall
            )
            val delta = endVal - startVal
            val sign = if (delta >= 0) "+" else ""
            Text(
                text = "终点 $${"%.2f".format(endVal)} ($sign$${"%.2f".format(delta)})",
                color = lineColor,
                style = MaterialTheme.typography.labelSmall,
                fontWeight = FontWeight.Bold
            )
        }
    }
}
