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
        require(mode in setOf("OFF","PAPER","LIVE") && revision>=0)
        require(control.length>=32 && control.none { it=='\r' || it=='\n' }) { "请输入独立操作令牌" }
        return request("trading-mode","POST",JSONObject().put("mode",mode).put("revision",revision).toString(),control)
    }
    suspend fun setConfig(config: JSONObject,control: String): String {
        require(control.length>=32 && control.none { it=='\r' || it=='\n' }) { "请输入独立操作令牌" }
        return request("paper-config","POST",config.toString(),control)
    }
    private suspend fun request(path: String,method: String,body: String?=null,control: String?=null): String = withContext(Dispatchers.IO) {
        require((method=="POST" && path in setOf("trading-mode","paper-config")) || method=="GET")
        if(method=="GET") {
        require(path in setOf("status", "metrics", "signals", "universe", "positions", "alerts", "reports", "fees","paper-config","demo") || Regex("reports/\\d{4}-\\d{2}-\\d{2}").matches(path))
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
    suspend fun demo() = JSONObject(api.get("demo"))
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
