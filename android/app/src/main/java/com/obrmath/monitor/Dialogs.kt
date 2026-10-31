package com.obrmath.monitor

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import org.json.JSONObject

@Composable
internal fun SignalDetailDialog(
    signal: JSONObject,
    outcomes: List<JSONObject>,
    onDismiss: () -> Unit,
    onJumpToStock: (String) -> Unit
) {
    val p = LocalObrPalette.current
    val symbol = signal.optString("symbol", "UNKNOWN")
    val state = signal.optString("state", "OBSERVED")
    val kind = signal.optString("kind", "ORB")
    val reason = signal.optString("reason", "")
    val refPrice = signal.optString("reference_price", "—")
    val score = signal.optString("score", "—")
    val sourceMs = signal.optLong("source_ms", 0L)
    val isConfirmed = state == "CONFIRMED"

    val matchingOutcomes = outcomes.filter {
        it.optString("symbol") == symbol &&
            (it.optString("candidate_id") == signal.optString("candidate_id") || it.optString("candidate_id").isBlank())
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = p.surface,
        title = {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column {
                    Text(
                        text = "$symbol · 量化信号穿透审计",
                        color = p.textPrimary,
                        style = MaterialTheme.typography.titleLarge
                    )
                    Text(
                        text = "信号类型：$kind · 时间：${formatTimestampMs(sourceMs)}",
                        color = p.textMuted,
                        style = MaterialTheme.typography.bodySmall
                    )
                }
                StatusPill(
                    text = if (isConfirmed) "已确认 CONFIRMED" else "已拒绝 REJECTED",
                    tone = if (isConfirmed) BadgeTone.BULLISH else BadgeTone.WARNING
                )
            }
        },
        text = {
            LazyColumn(
                modifier = Modifier.heightIn(max = 440.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                item {
                    Surface(
                        shape = RoundedCornerShape(10.dp),
                        color = p.cardElevated,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Column(
                            modifier = Modifier.padding(12.dp),
                            verticalArrangement = Arrangement.spacedBy(6.dp)
                        ) {
                            Text(
                                text = "策略决策归因",
                                color = p.primaryAccent,
                                style = MaterialTheme.typography.labelLarge
                            )
                            Text(
                                text = translateSignalReason(reason),
                                color = p.textPrimary,
                                style = MaterialTheme.typography.bodyMedium,
                                fontWeight = FontWeight.SemiBold
                            )
                            Text(
                                text = "原始决策码：$reason",
                                color = p.textMuted,
                                style = MaterialTheme.typography.labelSmall
                            )
                        }
                    }
                }
                item {
                    Surface(
                        shape = RoundedCornerShape(10.dp),
                        color = p.cardContainer,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Column(
                            modifier = Modifier.padding(12.dp),
                            verticalArrangement = Arrangement.spacedBy(4.dp)
                        ) {
                            KeyValueMetricRow("信号触发参考价", if (refPrice != "—") "$$refPrice" else "—")
                            KeyValueMetricRow("综合量化评分 (Score)", score)
                            KeyValueMetricRow("策略版本", signal.optString("version", "closed-bar-momentum-v2"))
                            KeyValueMetricRow("幂等候选 ID", signal.optString("candidate_id", "—").take(18) + "…")
                            KeyValueMetricRow("数据来源", signal.optString("provenance", "LIVE_OBSERVATION"))
                        }
                    }
                }
                if (matchingOutcomes.isNotEmpty()) {
                    item {
                        Text(
                            text = "信号后多周期表现追踪 (Forward Attribution)",
                            color = p.textPrimary,
                            style = MaterialTheme.typography.titleSmall
                        )
                    }
                    items(matchingOutcomes) { out ->
                        val horizon = out.optString("horizon", out.optString("window", "追踪"))
                        val ret = out.optString("return_pct", out.optString("price", "—"))
                        Surface(
                            shape = RoundedCornerShape(8.dp),
                            color = p.cardElevated,
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(10.dp),
                                horizontalArrangement = Arrangement.SpaceBetween
                            ) {
                                Text(text = "窗口：$horizon", color = p.textSecondary, style = MaterialTheme.typography.bodySmall)
                                Text(
                                    text = "记录值：$ret",
                                    color = p.primaryAccent,
                                    fontFamily = FontFamily.Monospace,
                                    style = MaterialTheme.typography.labelMedium
                                )
                            }
                        }
                    }
                }
            }
        },
        confirmButton = {
            FilledTonalButton(onClick = { onJumpToStock(symbol) }) {
                Text("在股票池定位 $symbol")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("关闭")
            }
        }
    )
}

@Composable
internal fun ModeSwitchDialog(
    targetMode: String,
    revision: Int,
    onDismiss: () -> Unit,
    onConfirm: (String, Int, String) -> Unit
) {
    val p = LocalObrPalette.current
    var controlToken by remember { mutableStateOf("") }
    var showToken by remember { mutableStateOf(false) }

    val dialogTitle = when (targetMode) {
        "LIVE_ON", "LIVE", "BOTH" -> "开启实盘通道（模拟盘照样并行运行）"
        "LIVE_OFF" -> "关闭实盘通道（保留模拟盘状态）"
        "PAPER_ON", "PAPER" -> "开启模拟盘通道"
        "PAPER_OFF" -> "关闭模拟盘通道"
        else -> "切换双通道运行模式"
    }
    val dialogDesc = when (targetMode) {
        "LIVE_ON", "LIVE", "BOTH" ->
            "开启实盘通道后，模拟盘与实盘将共用同一套 ORB-Math 确认信号并行运行。实盘买入仅使用 MAIN 现货 USDC，卖出结算至 CARD 钱包，绝不自动划转。"
        "LIVE_OFF" ->
            "停止实盘新开仓（已有实盘持仓仍继续执行止盈/止损/收盘退出保护），模拟盘保持当前运行状态不变。"
        "PAPER_ON", "PAPER" ->
            "开启模拟盘自动新开仓，与实盘通道共用同一套策略确认信号，资金与订单完全隔离。"
        "PAPER_OFF" ->
            "停止模拟盘新开仓（已有模拟持仓继续风控退出保护），实盘通道状态保持不变。"
        else ->
            "停止新开仓，已有持仓继续退出保护。"
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = p.surface,
        title = {
            Text(dialogTitle, color = p.textPrimary, style = MaterialTheme.typography.titleLarge)
        },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(dialogDesc, color = p.textSecondary, style = MaterialTheme.typography.bodyMedium)
                OutlinedTextField(
                    value = controlToken,
                    onValueChange = { controlToken = it },
                    label = { Text("独立操作令牌 (≥32位)") },
                    singleLine = true,
                    visualTransformation = if (showToken) VisualTransformation.None else PasswordVisualTransformation(),
                    trailingIcon = {
                        TextButton(onClick = { showToken = !showToken }) {
                            Text(if (showToken) "隐藏" else "显示", style = MaterialTheme.typography.labelSmall)
                        }
                    },
                    modifier = Modifier.fillMaxWidth()
                )
            }
        },
        confirmButton = {
            Button(
                enabled = controlToken.trim().length >= 32,
                onClick = {
                    if (revision >= 0) onConfirm(targetMode, revision, controlToken.trim())
                }
            ) {
                Text("确认切换")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("取消") }
        }
    )
}

@Composable
internal fun BudgetEditor(
    saved: JSONObject,
    onDismiss: () -> Unit,
    onSave: (JSONObject, String) -> Unit
) {
    val p = LocalObrPalette.current
    val labels = listOf(
        "initial_cash" to "初始模拟资金（美元 USD）",
        "per_order_budget" to "单笔含费上限（美元 USD）",
        "max_positions" to "同时持仓数上限（1–5 笔）",
        "max_daily_loss" to "当日亏损熔断上限（美元 USD）",
        "max_exposure" to "总敞口上限（美元 USD）",
        "max_daily_symbols" to "每日交易标的数上限（1–5 个）"
    )
    val values = remember {
        mutableStateMapOf<String, String>().apply {
            labels.forEach { (key, _) ->
                put(key, saved.optJSONObject("configuration")?.optString(key) ?: "")
            }
        }
    }
    var secret by remember { mutableStateOf("") }
    var error by remember { mutableStateOf("") }
    val cashLocked = saved.optBoolean("initial_cash_locked")

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = p.surface,
        title = {
            Column {
                Text("模拟盘预算与风险限额配置", color = p.textPrimary, style = MaterialTheme.typography.titleLarge)
                Text(
                    text = if (cashLocked) "账户已建立，初始资金已锁定；保存前需关闭模拟盘并确保空仓。" else "保存前请先关闭模拟盘开关。",
                    color = p.textMuted,
                    style = MaterialTheme.typography.bodySmall
                )
            }
        },
        text = {
            LazyColumn(
                modifier = Modifier.heightIn(max = 440.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                items(labels) { (key, label) ->
                    OutlinedTextField(
                        value = values[key] ?: "",
                        onValueChange = { values[key] = it },
                        label = { Text(label) },
                        singleLine = true,
                        enabled = key != "initial_cash" || !cashLocked,
                        modifier = Modifier.fillMaxWidth()
                    )
                }
                item {
                    OutlinedTextField(
                        value = secret,
                        onValueChange = { secret = it },
                        label = { Text("独立操作令牌 (≥32位)") },
                        singleLine = true,
                        visualTransformation = PasswordVisualTransformation(),
                        modifier = Modifier.fillMaxWidth()
                    )
                }
                if (error.isNotBlank()) {
                    item {
                        Text(error, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        },
        confirmButton = {
            Button(
                enabled = secret.trim().length >= 32,
                onClick = {
                    val payload = JSONObject().put("revision", saved.optInt("revision"))
                    var valid = true
                    labels.forEach { (key, _) ->
                        val value = values[key]?.trim() ?: ""
                        if (key in setOf("max_positions", "max_daily_symbols")) {
                            val parsed = value.toIntOrNull()
                            if (parsed == null || parsed !in 1..5) valid = false else payload.put(key, parsed)
                        } else {
                            val parsed = value.toBigDecimalOrNull()
                            if (parsed == null || parsed.signum() <= 0 || value.length > 24) valid = false else payload.put(key, value)
                        }
                    }
                    if (valid) {
                        onSave(payload, secret.trim())
                        secret = ""
                    } else {
                        error = "请输入正数金额，持仓与标的数须为 1 至 5 的整数。"
                    }
                }
            ) {
                Text("原子保存")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("取消") }
        }
    )
}

@Composable
internal fun LiveBudgetEditor(
    saved: JSONObject,
    onDismiss: () -> Unit,
    onSave: (JSONObject, String) -> Unit
) {
    val p = LocalObrPalette.current
    val defaults = mapOf(
        "allocated_usdc" to "600",
        "per_order_budget" to "300",
        "max_positions" to "2",
        "max_daily_loss" to "30",
        "max_exposure" to "600",
        "max_daily_symbols" to "5",
        "take_profit_pct" to "0.0175",
        "stop_loss_pct" to "0.0080"
    )
    val labels = listOf(
        "allocated_usdc" to "实盘分配资金（MAIN 现货 USDC）",
        "per_order_budget" to "单笔含费上限（USDC）",
        "max_positions" to "同时持仓数上限（1–5 笔）",
        "max_daily_loss" to "日亏损熔断上限（USDC）",
        "max_exposure" to "总敞口上限（USDC）",
        "max_daily_symbols" to "每日标的数上限（1–5 个）",
        "take_profit_pct" to "净止盈比例（如 0.0175 为 +1.75%）",
        "stop_loss_pct" to "净止损触发比例（如 0.0080 为 -0.80%）"
    )
    val cfg = saved.optJSONObject("configuration")
    val values = remember {
        mutableStateMapOf<String, String>().apply {
            labels.forEach { (key, _) ->
                put(key, cfg?.optString(key)?.ifBlank { defaults[key] ?: "" } ?: defaults[key] ?: "")
            }
        }
    }
    var secret by remember { mutableStateOf("") }
    var error by remember { mutableStateOf("") }

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = p.surface,
        title = {
            Column {
                Text("实盘仓位与风控参数配置", color = p.textPrimary, style = MaterialTheme.typography.titleLarge)
                Text(
                    text = "MAIN 现货 USDC 买入 -> CARD 卖出结算（不自动划转）；与模拟盘共用同一确认信号。",
                    color = p.textMuted,
                    style = MaterialTheme.typography.bodySmall
                )
            }
        },
        text = {
            LazyColumn(
                modifier = Modifier.heightIn(max = 450.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                items(labels) { (key, label) ->
                    OutlinedTextField(
                        value = values[key] ?: "",
                        onValueChange = { values[key] = it },
                        label = { Text(label) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                }
                item {
                    OutlinedTextField(
                        value = secret,
                        onValueChange = { secret = it },
                        label = { Text("独立操作令牌 (≥32位)") },
                        singleLine = true,
                        visualTransformation = PasswordVisualTransformation(),
                        modifier = Modifier.fillMaxWidth()
                    )
                }
                if (error.isNotBlank()) {
                    item {
                        Text(error, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        },
        confirmButton = {
            Button(
                enabled = secret.trim().length >= 32,
                onClick = {
                    val payload = JSONObject().put("revision", saved.optInt("revision", 0))
                    var valid = true
                    labels.forEach { (key, _) ->
                        val value = values[key]?.trim() ?: ""
                        if (key in setOf("max_positions", "max_daily_symbols")) {
                            val parsed = value.toIntOrNull()
                            if (parsed == null || parsed !in 1..5) valid = false else payload.put(key, parsed)
                        } else {
                            val parsed = value.toBigDecimalOrNull()
                            if (parsed == null || parsed.signum() <= 0 || value.length > 24) valid = false else payload.put(key, value)
                        }
                    }
                    if (valid) {
                        onSave(payload, secret.trim())
                        secret = ""
                    } else {
                        error = "请输入有效的正数金额/比例，持仓与标的数须为 1 至 5 的整数。"
                    }
                }
            ) {
                Text("保存实盘参数")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("取消") }
        }
    )
}

@Composable
internal fun StrategyLabDialog(
    activeParams: JSONObject?,
    onDismiss: () -> Unit,
    onSubmit: (String, JSONObject, String, Double, String) -> Unit
) {
    val p = LocalObrPalette.current
    var versionId by remember { mutableStateOf("candidate-v" + (System.currentTimeMillis() % 10000)) }
    var minRvol by remember { mutableStateOf(activeParams?.optString("min_rvol", "1.5") ?: "1.5") }
    var maxChase by remember { mutableStateOf(activeParams?.optString("max_chase", "0.015") ?: "0.015") }
    var maxSpread by remember { mutableStateOf(activeParams?.optString("max_spread", "0.0035") ?: "0.0035") }
    var maxConsolidation by remember { mutableStateOf(activeParams?.optString("max_consolidation", "0.008") ?: "0.008") }
    var splitRatio by remember { mutableStateOf("0.70") }
    var notes by remember { mutableStateOf("基于 5 周期复盘诊断的候选参数调优实验") }
    var controlToken by remember { mutableStateOf("") }
    var error by remember { mutableStateOf("") }

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = p.surface,
        title = {
            Column {
                Text("候选策略提案与样本外回测实验室", color = p.textPrimary, style = MaterialTheme.typography.titleLarge)
                Text(
                    text = "提交候选参数后将自动执行 Walk-Forward 样本内/样本外 (OOS) 验证门控；未通过验证绝不覆盖线上稳定版。",
                    color = p.textMuted,
                    style = MaterialTheme.typography.bodySmall
                )
            }
        },
        text = {
            LazyColumn(
                modifier = Modifier.heightIn(max = 440.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                item {
                    OutlinedTextField(
                        value = versionId,
                        onValueChange = { versionId = it },
                        label = { Text("候选策略版本号 (version_id)") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                }
                item {
                    OutlinedTextField(
                        value = minRvol,
                        onValueChange = { minRvol = it },
                        label = { Text("最小相对成交量倍数 (min_rvol)") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                }
                item {
                    OutlinedTextField(
                        value = maxChase,
                        onValueChange = { maxChase = it },
                        label = { Text("最大突破追高容忍度 (max_chase)") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                }
                item {
                    OutlinedTextField(
                        value = maxSpread,
                        onValueChange = { maxSpread = it },
                        label = { Text("最大允许盘口点差 (max_spread)") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                }
                item {
                    OutlinedTextField(
                        value = maxConsolidation,
                        onValueChange = { maxConsolidation = it },
                        label = { Text("趋势延续整理带宽上限 (max_consolidation)") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                }
                item {
                    OutlinedTextField(
                        value = splitRatio,
                        onValueChange = { splitRatio = it },
                        label = { Text("样本内切分比例 (0.40–0.90，默认 0.70 即 70%样本内/30%样本外)") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                }
                item {
                    OutlinedTextField(
                        value = notes,
                        onValueChange = { notes = it },
                        label = { Text("调优研究备注 (notes)") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                }
                item {
                    OutlinedTextField(
                        value = controlToken,
                        onValueChange = { controlToken = it },
                        label = { Text("独立操作令牌 (≥32位)") },
                        singleLine = true,
                        visualTransformation = PasswordVisualTransformation(),
                        modifier = Modifier.fillMaxWidth()
                    )
                }
                if (error.isNotBlank()) {
                    item {
                        Text(error, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        },
        confirmButton = {
            Button(
                enabled = controlToken.trim().length >= 32 && versionId.isNotBlank(),
                onClick = {
                    val ratio = splitRatio.toDoubleOrNull()
                    if (ratio == null || ratio !in 0.40..0.90) {
                        error = "切分比例须在 0.40 至 0.90 之间"
                        return@Button
                    }
                    val params = JSONObject()
                        .put("min_rvol", minRvol.trim())
                        .put("max_chase", maxChase.trim())
                        .put("max_spread", maxSpread.trim())
                        .put("max_consolidation", maxConsolidation.trim())
                    onSubmit(versionId.trim(), params, notes.trim(), ratio, controlToken.trim())
                }
            ) {
                Text("提案并运行样本外验证")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("取消") }
        }
    )
}

@Composable
internal fun ControlTokenPromptDialog(
    title: String,
    description: String,
    confirmLabel: String,
    onDismiss: () -> Unit,
    onConfirm: (String) -> Unit
) {
    val p = LocalObrPalette.current
    var token by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = p.surface,
        title = { Text(title, color = p.textPrimary, style = MaterialTheme.typography.titleLarge) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(description, color = p.textSecondary, style = MaterialTheme.typography.bodyMedium)
                OutlinedTextField(
                    value = token,
                    onValueChange = { token = it },
                    label = { Text("独立操作令牌 (≥32位)") },
                    singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
                    modifier = Modifier.fillMaxWidth()
                )
            }
        },
        confirmButton = {
            Button(
                enabled = token.trim().length >= 32,
                onClick = { onConfirm(token.trim()) }
            ) {
                Text(confirmLabel)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("取消") }
        }
    )
}
