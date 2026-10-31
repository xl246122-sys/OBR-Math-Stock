package com.obrmath.monitor

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.math.BigDecimal
import java.math.RoundingMode
import java.net.URI
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import javax.net.ssl.HttpsURLConnection

internal const val DEFAULT_SERVER = "https://43.163.203.127"
internal const val APP_VERSION = "0.7.0"

internal fun validatedBase(raw: String): String {
    val uri = URI(raw.trim())
    require(
        uri.scheme == "https" &&
            !uri.host.isNullOrBlank() &&
            uri.rawUserInfo == null &&
            uri.rawQuery == null &&
            uri.rawFragment == null
    ) { "请输入有效的 HTTPS 服务地址，不含账号、参数或片段" }
    require(uri.rawPath.isNullOrEmpty() || uri.rawPath == "/") { "请输入服务根地址" }
    require(uri.port == -1 || uri.port in 1..65535) { "端口无效" }
    return uri.toASCIIString().trimEnd('/')
}

class MonitorApi(base: String, private val token: String) {
    private val base = validatedBase(base)

    init {
        require(token.isNotBlank() && token.none { it == '\r' || it == '\n' }) { "访问令牌无效" }
    }

    suspend fun get(path: String): String = request(path, "GET")

    suspend fun setMode(mode: String, revision: Int, control: String): String {
        require(mode in setOf("OFF", "PAPER", "LIVE", "BOTH", "PAPER_ON", "PAPER_OFF", "LIVE_ON", "LIVE_OFF") && revision >= 0)
        require(control.length >= 32 && control.none { it == '\r' || it == '\n' }) { "请输入独立操作令牌" }
        return request("trading-mode", "POST", JSONObject().put("mode", mode).put("revision", revision).toString(), control)
    }

    suspend fun setConfig(config: JSONObject, control: String): String {
        require(control.length >= 32 && control.none { it == '\r' || it == '\n' }) { "请输入独立操作令牌" }
        return request("paper-config", "POST", config.toString(), control)
    }

    suspend fun setLiveConfig(config: JSONObject, control: String): String {
        require(control.length >= 32 && control.none { it == '\r' || it == '\n' }) { "请输入独立操作令牌" }
        return request("live-config", "POST", config.toString(), control)
    }

    suspend fun triggerReview(periodType: String, control: String, force: Boolean = true): String {
        require(periodType in setOf("DAILY", "TRADING_5D", "MONTHLY", "QUARTERLY", "SEMIANNUAL")) { "复盘周期类型无效" }
        require(control.length >= 32 && control.none { it == '\r' || it == '\n' }) { "请输入独立操作令牌" }
        val payload = JSONObject().put("period_type", periodType).put("force", force)
        return request("evolution/review", "POST", payload.toString(), control)
    }

    suspend fun proposeVersion(versionId: String, parameters: JSONObject, notes: String, control: String): String {
        require(versionId.isNotBlank() && versionId.length <= 64) { "策略版本号无效" }
        require(control.length >= 32 && control.none { it == '\r' || it == '\n' }) { "请输入独立操作令牌" }
        val payload = JSONObject()
            .put("version_id", versionId.trim())
            .put("parameters", parameters)
            .put("notes", notes.take(500))
        return request("evolution/propose", "POST", payload.toString(), control)
    }

    suspend fun backtestVersion(versionId: String, splitRatio: Double, control: String): String {
        require(versionId.isNotBlank() && splitRatio in 0.40..0.90) { "回测参数无效" }
        require(control.length >= 32 && control.none { it == '\r' || it == '\n' }) { "请输入独立操作令牌" }
        val payload = JSONObject()
            .put("version_id", versionId.trim())
            .put("split_ratio", splitRatio)
        return request("evolution/backtest", "POST", payload.toString(), control)
    }

    suspend fun promoteVersion(versionId: String, control: String): String {
        require(versionId.isNotBlank()) { "策略版本号无效" }
        require(control.length >= 32 && control.none { it == '\r' || it == '\n' }) { "请输入独立操作令牌" }
        val payload = JSONObject().put("version_id", versionId.trim())
        return request("evolution/promote", "POST", payload.toString(), control)
    }

    private suspend fun request(
        path: String,
        method: String,
        body: String? = null,
        control: String? = null
    ): String = withContext(Dispatchers.IO) {
        val allowedPosts = setOf(
            "trading-mode",
            "paper-config",
            "live-config",
            "evolution/review",
            "evolution/propose",
            "evolution/backtest",
            "evolution/promote"
        )
        require((method == "POST" && path in allowedPosts) || method == "GET")
        if (method == "GET") {
            val allowedGets = setOf(
                "status",
                "metrics",
                "signals",
                "outcomes",
                "universe",
                "positions",
                "alerts",
                "reports",
                "fees",
                "paper-config",
                "live-config",
                "demo",
                "evolution/ai-context",
                "evolution/reviews",
                "evolution/versions"
            )
            require(path in allowedGets || Regex("reports/\\d{4}-\\d{2}-\\d{2}").matches(path))
        }
        val connection = URI("$base/api/v1/$path").toURL().openConnection() as HttpsURLConnection
        connection.instanceFollowRedirects = false
        connection.connectTimeout = 10000
        connection.readTimeout = 10000
        connection.setRequestProperty("Authorization", "Bearer $token")
        connection.requestMethod = method
        try {
            if (body != null) {
                connection.setRequestProperty("X-OBR-Control-Token", control)
                connection.setRequestProperty("Content-Type", "application/json")
                connection.doOutput = true
                connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            }
            when (connection.responseCode) {
                200 -> connection.inputStream.use { stream ->
                    val output = java.io.ByteArrayOutputStream()
                    val buffer = ByteArray(8192)
                    while (true) {
                        val count = stream.read(buffer)
                        if (count < 0) break
                        output.write(buffer, 0, count)
                        require(output.size() <= 2_000_000) { "Response too large" }
                    }
                    val bytes = output.toByteArray()
                    require(bytes.size <= 2_000_000) { "响应超过客户端大小限制" }
                    bytes.toString(Charsets.UTF_8)
                }
                401 -> error("访问令牌无效，请重新连接")
                403 -> error("独立操作令牌无效，写操作已拦截")
                404 -> error("请求的目标对象或版本不存在")
                409 -> error("操作未满足前置风控条件：请确认通道开关、空仓状态或样本外验证条件后刷新重试。")
                503 -> error("服务或模式控制暂不可用，请刷新核对当前状态")
                else -> error("服务返回 HTTP ${connection.responseCode}")
            }
        } finally {
            connection.disconnect()
        }
    }
}

data class Dashboard(
    val status: JSONObject,
    val metrics: JSONObject,
    val signals: JSONArray,
    val universe: JSONObject,
    val positions: JSONObject,
    val alerts: JSONArray,
    val reports: JSONArray,
    val fees: JSONObject,
    val paperConfig: JSONObject,
    val outcomes: JSONArray = JSONArray()
)

class MonitorRepository(private val api: MonitorApi) {
    suspend fun setMode(mode: String, revision: Int, control: String) = JSONObject(api.setMode(mode, revision, control))
    suspend fun setConfig(config: JSONObject, control: String) = JSONObject(api.setConfig(config, control))
    suspend fun setLiveConfig(config: JSONObject, control: String) = JSONObject(api.setLiveConfig(config, control))
    suspend fun triggerReview(periodType: String, control: String) = JSONObject(api.triggerReview(periodType, control))
    suspend fun proposeVersion(versionId: String, parameters: JSONObject, notes: String, control: String) =
        JSONObject(api.proposeVersion(versionId, parameters, notes, control))
    suspend fun backtestVersion(versionId: String, splitRatio: Double, control: String) =
        JSONObject(api.backtestVersion(versionId, splitRatio, control))
    suspend fun promoteVersion(versionId: String, control: String) =
        JSONObject(api.promoteVersion(versionId, control))
    suspend fun demo() = JSONObject(api.get("demo"))
    suspend fun evolution() = JSONObject(api.get("evolution/ai-context"))
    suspend fun evolutionVersions() = JSONObject(api.get("evolution/versions"))

    suspend fun load(): Dashboard {
        val status = JSONObject(api.get("status"))
        val metrics = JSONObject(api.get("metrics"))
        val signals = JSONArray(api.get("signals"))
        val universe = JSONObject(api.get("universe"))
        val positions = JSONObject(api.get("positions"))
        val alerts = JSONArray(api.get("alerts"))
        val reports = JSONArray(api.get("reports"))
        val fees = JSONObject(api.get("fees"))
        val paperCfg = JSONObject(api.get("paper-config"))
        val outcomes = try {
            JSONArray(api.get("outcomes"))
        } catch (_: Exception) {
            JSONArray()
        }
        return Dashboard(
            status = status,
            metrics = metrics,
            signals = signals,
            universe = universe,
            positions = positions,
            alerts = alerts,
            reports = reports,
            fees = fees,
            paperConfig = paperCfg,
            outcomes = outcomes
        )
    }

    suspend fun report(day: String) = api.get("reports/$day")
}

internal fun JSONArray.objects(): List<JSONObject> = (0 until length()).mapNotNull { optJSONObject(it) }
internal fun JSONArray.strings(): List<String> = (0 until length()).map { optString(it) }
internal fun feeChangeId(fees: JSONObject): String? = fees.optJSONObject("change")?.optString("id")?.takeIf { it.isNotBlank() }

internal fun feeSummary(fees: JSONObject): String {
    val change = fees.optJSONObject("change") ?: return "暂无手续费变更"
    return "官方来源：${fees.optString("source")}\n变更类型：${change.optString("kind")}\n原规则：\n${change.optJSONObject("before")?.toString(2)}\n新规则：\n${change.optJSONObject("after")?.toString(2)}"
}

internal fun feedHealthSummary(status: JSONObject): String {
    val feeds = status.optJSONArray("feeds")?.objects() ?: return "暂无通道状态"
    if (feeds.isEmpty()) return "暂无通道状态"
    return feeds.joinToString("\n") { f ->
        val role = f.optString("role").ifBlank { "generic" }
        val conn = if (f.optBoolean("connected")) "已连接" else "重连中"
        val gap = if (f.optBoolean("data_gap")) "缺口锁定(待连续性恢复)" else "连续正常"
        "$role：$conn · $gap（重连 ${f.optInt("reconnects")} 次 / 丢弃 ${f.optInt("dropped")}）"
    }
}

internal fun liveLedgerSummary(modes: JSONObject?): String {
    val ledger = modes?.optJSONObject("live_ledger")
        ?: return "实盘独立账本未初始化（与模拟盘资金完全隔离）"
    val reconciled = if (ledger.optBoolean("reconciled")) "已完成启动对账" else "未完成对账（禁止实盘开仓）"
    val extCount = ledger.optJSONObject("external_positions")?.length() ?: 0
    return "账本空间：${ledger.optString("account_namespace")}\n" +
        "对账状态：$reconciled\n" +
        "MAIN 现货可用 USDC：$${ledger.optString("main_usdc_free", "0")}（预占 $${ledger.optString("main_usdc_reserved", "0")}）\n" +
        "CARD 卖出结算累计：$${ledger.optString("card_settlement_usdc", "0")}（不自动划转回现货）\n" +
        "手工既有仓位隔离数：$extCount 个标的（策略不接管）"
}

internal fun liveConfigSummary(modes: JSONObject?): String {
    val cfg = modes?.optJSONObject("live_config")?.optJSONObject("configuration")
        ?: modes?.optJSONObject("live_ledger")?.optJSONObject("configuration")
        ?: return "暂未读取实盘仓位参数"
    return "实盘配置资金：$${cfg.optString("allocated_usdc")} USDC · 单笔上限 $${cfg.optString("per_order_budget")}\n" +
        "同时持仓上限：${cfg.optInt("max_positions")} 笔 · 每日标的上限：${cfg.optInt("max_daily_symbols")} 个\n" +
        "总敞口上限：$${cfg.optString("max_exposure")} · 日亏损熔断：$${cfg.optString("max_daily_loss")}\n" +
        "止盈比例：${cfg.optString("take_profit_pct", "0.0175")} · 止损比例：${cfg.optString("stop_loss_pct", "0.0080")}\n" +
        "钱包路径：${cfg.optString("buy_wallet", "MAIN")}/${cfg.optString("quote_asset", "USDC")} 买入 -> ${cfg.optString("sell_settlement_wallet", "CARD")} 卖出结算"
}

internal fun sharedSignalSummary(modes: JSONObject?): String {
    if (modes == null) return "等待通道模式状态"
    val paperOn = if (modes.optBoolean("paper_enabled")) "运行中" else "已关闭"
    val liveOn = if (modes.optBoolean("live_enabled")) "运行中" else "已关闭"
    val sigCount = modes.optJSONObject("live_ledger")?.optInt("received_signals_count", 0) ?: 0
    return "模拟盘通道：$paperOn · 实盘通道：$liveOn\n" +
        "信号共享：2 个模块共用 1 套 ORB-Math 确认信号（互不抢占、账本完全隔离）\n" +
        "实盘通道累计接收共享信号：$sigCount 次"
}

internal fun evolutionPeriodSummary(review: JSONObject?): String {
    if (review == null) return "暂无该周期复盘数据"
    val p = review.optJSONObject("paper_performance")
    val l = review.optJSONObject("live_performance")
    val s = review.optJSONObject("signal_diagnostics")
    val suggs = review.optJSONArray("optimization_suggestions")?.objects() ?: emptyList()
    val firstSugg = suggs.firstOrNull()?.optString("rationale") ?: "保持当前稳定基线"
    return "周期：${review.optString("period_label")} (${review.optString("period_key")})\n" +
        "模拟盘：平仓 ${p?.optInt("closed_trades_count", 0)} 笔 · 胜率 ${p?.optString("win_rate", "0")} · 盈亏比 ${p?.optString("profit_loss_ratio", "0")} · 净收益 $${p?.optString("net_pnl", "0")} · 最大回撤 $${p?.optString("max_drawdown", "0")}\n" +
        "实盘：平仓 ${l?.optInt("closed_trades_count", 0)} 笔 · 胜率 ${l?.optString("win_rate", "0")} · 盈亏比 ${l?.optString("profit_loss_ratio", "0")} · 净收益 $${l?.optString("net_pnl", "0")}\n" +
        "信号质量：候选 ${s?.optInt("total_candidates", 0)} · 假突破 ${s?.optInt("erroneous_signals_count", 0)} · 错失机会 ${s?.optInt("missed_opportunities_count", 0)}\n" +
        "优化建议：$firstSugg"
}

// ============================================================================
// Quantitative Financial Analyst Domain Translators & Formatters
// ============================================================================

data class BlockerDiagnostic(
    val code: String,
    val title: String,
    val explanation: String,
    val actionHint: String,
    val severity: String // "CRITICAL", "WARNING", "INFO"
)

internal fun diagnoseBlocker(code: String): BlockerDiagnostic = when (code) {
    "PAPER_VERIFICATION_REQUIRED" -> BlockerDiagnostic(
        code = code,
        title = "模拟盘开仓核验文件待完备",
        explanation = "系统遵循 Fail-Closed 机构风控原则，需核实有效期内 (≤26h) 的 paper-verification.json 证据。",
        actionHint = "核实官方手续费指纹与量能标的清单后自动放行。",
        severity = "WARNING"
    )
    "FEES_NOT_VERIFIED", "LIVE_FEES_NOT_VERIFIED" -> BlockerDiagnostic(
        code = code,
        title = "账户适用手续费率尚未核实",
        explanation = "公开费率表不等于账户实际适用费率；未确认真实比例费率与最低收费前禁止自动建仓。",
        actionHint = "前往「风控与设置 -> 官方手续费」查看最新核查状态。",
        severity = "WARNING"
    )
    "VOLUME_NOT_VERIFIED" -> BlockerDiagnostic(
        code = code,
        title = "焦点标的量能单位与单调性待核验",
        explanation = "部分重点订阅标的尚未通过实时 K 线量能单调递增与价格 Tick 核验。",
        actionHint = "等待开市真实 K 线采样完成量能核验。",
        severity = "WARNING"
    )
    "HISTORICAL_VOLUME_COLD_START" -> BlockerDiagnostic(
        code = code,
        title = "历史同进度成交量样本冷启动积累中",
        explanation = "ORB 相对成交量 (RVOL) 要求至少 10 个历史交易日同一时间进度的真实成交量基准。",
        actionHint = "系统正自动记录盘中 K 线，满足 10 日样本后自动解除。",
        severity = "INFO"
    )
    "EXCHANGE_RULES_UNVERIFIED_OR_STALE" -> BlockerDiagnostic(
        code = code,
        title = "交易所规则未核验或超过 20 分钟未刷新",
        explanation = "需通过只读 API Key 定期同步 exchangeInfo 以确认最小变动价位、数量步长与可交易状态。",
        actionHint = "检查服务器 BINANCE_API_KEY 只读权限与网络连接。",
        severity = "WARNING"
    )
    "MARKET_DATA_GAP" -> BlockerDiagnostic(
        code = code,
        title = "行情连续性存在缺口锁定",
        explanation = "WebSocket 出现断流或队列溢出后已触发防污染锁定，防止使用残缺 K 线计算突破区间。",
        actionHint = "系统在连续收到无缺口闭合 K 线后会自动恢复连续性状态。",
        severity = "CRITICAL"
    )
    "PAPER_MODE_OFF" -> BlockerDiagnostic(
        code = code,
        title = "模拟盘通道开关当前已关闭",
        explanation = "用户已将模拟盘通道设为关闭状态，停止新开仓，但已有持仓仍受止盈止损保护。",
        actionHint = "可在顶部双通道快捷栏或「风控与设置」中一键开启模拟盘。",
        severity = "INFO"
    )
    "DAILY_LOSS_LIMIT" -> BlockerDiagnostic(
        code = code,
        title = "已触发当日最大亏损熔断",
        explanation = "当日已实现亏损达到风控阈值，系统已自动熔断并禁止今日新增开仓。",
        actionHint = "保持空仓复盘，次一交易日开盘前自动重置日内熔断状态。",
        severity = "CRITICAL"
    )
    "MARKET_DISCONNECTED" -> BlockerDiagnostic(
        code = code,
        title = "行情 WebSocket 通道重连中",
        explanation = "至少一路行情或状态流尚未完全建立连接。",
        actionHint = "检查「总览 -> 行情通道矩阵」查看具体重连通道。",
        severity = "CRITICAL"
    )
    "LIVE_ACCOUNT_NOT_RECONCILED" -> BlockerDiagnostic(
        code = code,
        title = "实盘独立账本尚未完成启动对账",
        explanation = "实盘通道要求对 MAIN 现货 USDC 余额、既有手工持仓及未结订单完成严格对账。",
        actionHint = "确认实盘执行器与只读对账完成后再开启实盘通道。",
        severity = "WARNING"
    )
    "LIVE_INSTRUMENT_METADATA_NOT_VERIFIED" -> BlockerDiagnostic(
        code = code,
        title = "美国上市股票/ETF 权威元数据待全量核验",
        explanation = "实盘严格限制仅交易正规 US STOCK / ETF，禁止代币化股票或其他衍生品。",
        actionHint = "前往「行情与信号 -> 股票池」查看元数据核验覆盖率。",
        severity = "WARNING"
    )
    "DISK_LOW" -> BlockerDiagnostic(
        code = code,
        title = "服务器可用磁盘空间低于 25%",
        explanation = "为保障 SQLite WAL 审计落盘安全，低磁盘空间下自动停止新开仓。",
        actionHint = "清理服务器历史备份或扩容存储。",
        severity = "CRITICAL"
    )
    "PROCESSING_LATENCY_HIGH" -> BlockerDiagnostic(
        code = code,
        title = "内部处理延迟 P95 超过 100ms 阈值",
        explanation = "高延迟可能导致盘口报价滑点扩大，系统自动暂停新开仓以保护执行质量。",
        actionHint = "检查服务器 CPU 负载与 SQLite 写入队列。",
        severity = "CRITICAL"
    )
    else -> BlockerDiagnostic(
        code = code,
        title = "风控前置条件：$code",
        explanation = "系统检测到未满足的运行或风控约束 ($code)，当前保持观察保护模式。",
        actionHint = "请核查系统告警与通道状态。",
        severity = if (code.contains("FAIL") || code.contains("CRITICAL")) "CRITICAL" else "WARNING"
    )
}

internal fun translateSignalReason(reason: String): String = when (reason.uppercase(Locale.US)) {
    "CONFIRMED", "ORB_BREAKOUT_CONFIRMED" -> "开盘区间突破确认：闭合 5m K 线突破 ORB 上轨，RVOL、动量与盘口价差全部达标"
    "CONTINUATION_CONFIRMED", "TREND_CONTINUATION_CONFIRMED" -> "盘中趋势延续确认：缩量窄幅整理后放量二次突破，多周期动量共振"
    "RVOL_BELOW_THRESHOLD", "LOW_RVOL" -> "相对成交量 (RVOL) 不足：当前同进度累计量未达历史 10 日均值倍数要求"
    "SPREAD_TOO_WIDE", "WIDE_SPREAD" -> "盘口买卖价差过大：当前 Ask-Bid 点差超出最大冲击成本阈值"
    "CHASE_TOO_HIGH", "EXTENDED_FROM_ORB" -> "突破追高幅度过大：收盘价偏离突破基准位过远，盈亏比不具优势"
    "MOMENTUM_NEGATIVE", "WEAK_MOMENTUM" -> "短周期动量未共振：1m / 3m / 5m 价格动量未全部转正或缺失"
    "VOLUME_UNVERIFIED" -> "成交量未通过核验：该标的量能证据尚未确认或存在单调性异常"
    "NOT_TRADABLE", "TRADING_HALTED" -> "标的当前不可买入：平台交易方向受限、停牌或规则未核验"
    "CONSOLIDATION_TOO_WIDE" -> "盘中整理区间过宽：回撤波动超出趋势延续模型的紧凑度要求"
    "INSUFFICIENT_HISTORY", "COLD_START" -> "历史同进度样本不足：未满 10 个有效历史交易日样本"
    "OUTSIDE_ENTRY_WINDOW", "NEAR_CLOSE" -> "非策略开仓时间窗：处于收盘前 20 分钟禁入期或开盘观察期"
    "DATA_GAP", "INCOMPLETE_SESSION" -> "日内行情存在缺口：当前交易日 K 线序列不完整，跳过信号评估"
    else -> reason
}

internal fun translateMarketPhase(phase: String): String = when (phase.uppercase(Locale.US)) {
    "RTH_OPEN" -> "美股盘中交易 (RTH Open)"
    "RTH_CLOSED" -> "盘后/非交易时段 (RTH Closed)"
    "CLOSED", "WEEKEND", "HOLIDAY" -> "美股休市 (Closed)"
    "PRE_MARKET" -> "美股盘前 (Pre-Market)"
    "AFTER_HOURS" -> "美股盘后 (After-Hours)"
    else -> phase.ifBlank { "未知时段" }
}

internal fun translateHealth(health: String): String = when (health.uppercase(Locale.US)) {
    "HEALTHY" -> "健康运行 (HEALTHY)"
    "DEGRADED" -> "受限观察 (DEGRADED)"
    "CRITICAL" -> "严重告警 (CRITICAL)"
    else -> health.ifBlank { "未知" }
}

internal fun translateMode(mode: String): String = when (mode.uppercase(Locale.US)) {
    "PAPER_ACTIVE" -> "模拟交易激活 (PAPER_ACTIVE)"
    "LIVE_ACTIVE" -> "实盘交易激活 (LIVE_ACTIVE)"
    "WATCH_ONLY" -> "只读观察保护 (WATCH_ONLY)"
    else -> mode.ifBlank { "观察模式" }
}

internal fun formatTimestampMs(ms: Long): String {
    if (ms <= 0L) return "—"
    return try {
        val sdf = SimpleDateFormat("MM-dd HH:mm:ss", Locale.US)
        sdf.timeZone = TimeZone.getDefault()
        sdf.format(Date(ms))
    } catch (_: Exception) {
        ms.toString()
    }
}

internal fun formatPct(raw: String?, multiplyBy100: Boolean = true): String {
    if (raw.isNullOrBlank()) return "0.00%"
    return try {
        val bd = BigDecimal(raw.trim())
        val pct = if (multiplyBy100) bd.multiply(BigDecimal(100)) else bd
        "${pct.setScale(2, RoundingMode.HALF_UP)}%"
    } catch (_: Exception) {
        raw
    }
}

internal fun formatUsd(raw: String?): String {
    if (raw.isNullOrBlank()) return "$0.00"
    return try {
        val bd = BigDecimal(raw.trim())
        val sign = if (bd.signum() < 0) "-" else ""
        "$sign$${bd.abs().setScale(2, RoundingMode.HALF_UP)}"
    } catch (_: Exception) {
        "$$raw"
    }
}
