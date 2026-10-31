package com.obrmath.monitor

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.URI
import javax.net.ssl.HttpsURLConnection

internal const val DEFAULT_SERVER = "https://43.163.203.127"

internal fun validatedBase(raw: String): String {
    val uri = URI(raw.trim())
    require(uri.scheme == "https" && !uri.host.isNullOrBlank() && uri.rawUserInfo == null && uri.rawQuery == null && uri.rawFragment == null) { "请输入有效的 HTTPS 服务地址，不含账号、参数或片段" }
    require(uri.rawPath.isNullOrEmpty() || uri.rawPath == "/") { "请输入服务根地址" }
    require(uri.port == -1 || uri.port in 1..65535) { "端口无效" }
    return uri.toASCIIString().trimEnd('/')
}

class MonitorApi(base: String, private val token: String) {
    private val base = validatedBase(base)
    init { require(token.isNotBlank() && token.none { it == '\r' || it == '\n' }) { "访问令牌无效" } }
    suspend fun get(path: String): String = request(path,"GET")
    suspend fun setMode(mode: String,revision: Int,control: String): String {
        require(mode in setOf("OFF","PAPER","LIVE","BOTH","PAPER_ON","PAPER_OFF","LIVE_ON","LIVE_OFF") && revision>=0)
        require(control.length>=32 && control.none { it=='\r' || it=='\n' }) { "请输入独立操作令牌" }
        return request("trading-mode","POST",JSONObject().put("mode",mode).put("revision",revision).toString(),control)
    }
    suspend fun setConfig(config: JSONObject,control: String): String {
        require(control.length>=32 && control.none { it=='\r' || it=='\n' }) { "请输入独立操作令牌" }
        return request("paper-config","POST",config.toString(),control)
    }
    suspend fun setLiveConfig(config: JSONObject,control: String): String {
        require(control.length>=32 && control.none { it=='\r' || it=='\n' }) { "请输入独立操作令牌" }
        return request("live-config","POST",config.toString(),control)
    }
    private suspend fun request(path: String,method: String,body: String?=null,control: String?=null): String = withContext(Dispatchers.IO) {
        require((method=="POST" && path in setOf("trading-mode","paper-config","live-config","evolution/review")) || method=="GET")
        if(method=="GET") {
        require(path in setOf("status", "metrics", "signals", "universe", "positions", "alerts", "reports", "fees","paper-config","live-config","demo","evolution/ai-context","evolution/reviews","evolution/versions") || Regex("reports/\\d{4}-\\d{2}-\\d{2}").matches(path))
        }
        val connection = URI("$base/api/v1/$path").toURL().openConnection() as HttpsURLConnection
        connection.instanceFollowRedirects = false
        connection.connectTimeout = 10000
        connection.readTimeout = 10000
        connection.setRequestProperty("Authorization", "Bearer $token")
        connection.requestMethod=method
        try {
            if(body!=null) {
                connection.setRequestProperty("X-OBR-Control-Token",control)
                connection.setRequestProperty("Content-Type","application/json")
                connection.doOutput=true
                connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            }
            when (connection.responseCode) {
                200 -> connection.inputStream.use { stream ->
                    val output = java.io.ByteArrayOutputStream()
                    val buffer = ByteArray(8192)
                    while (true) { val count=stream.read(buffer); if(count<0) break; output.write(buffer,0,count); require(output.size()<=2_000_000) { "Response too large" } }
                    val bytes = output.toByteArray()
                    require(bytes.size <= 2_000_000) { "响应超过客户端大小限制" }
                    bytes.toString(Charsets.UTF_8)
                }
                401 -> error("访问令牌无效，请重新连接")
                403 -> error("操作令牌无效，模式未切换")
                409 -> error("操作未满足条件：请先关闭模式、确认无持仓/未完成订单并刷新。已建立账户不能更改初始资金。")
                503 -> error("模式控制未配置或操作失败，请刷新核对当前状态")
                else -> error("服务返回 HTTP ${connection.responseCode}")
            }
        } finally { connection.disconnect() }
    }
}

data class Dashboard(
    val status: JSONObject, val metrics: JSONObject, val signals: JSONArray,
    val universe: JSONObject, val positions: JSONObject, val alerts: JSONArray,
    val reports: JSONArray, val fees: JSONObject, val paperConfig: JSONObject
)
class MonitorRepository(private val api: MonitorApi) {
    suspend fun setMode(mode: String,revision: Int,control: String) = JSONObject(api.setMode(mode,revision,control))
    suspend fun setConfig(config: JSONObject,control: String) = JSONObject(api.setConfig(config,control))
    suspend fun setLiveConfig(config: JSONObject,control: String) = JSONObject(api.setLiveConfig(config,control))
    suspend fun demo() = JSONObject(api.get("demo"))
    suspend fun evolution() = JSONObject(api.get("evolution/ai-context"))
    suspend fun load() = Dashboard(JSONObject(api.get("status")), JSONObject(api.get("metrics")),
        JSONArray(api.get("signals")), JSONObject(api.get("universe")), JSONObject(api.get("positions")),
        JSONArray(api.get("alerts")), JSONArray(api.get("reports")), JSONObject(api.get("fees")),JSONObject(api.get("paper-config")))
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
