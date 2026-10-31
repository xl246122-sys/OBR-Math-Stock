package com.obrmath.monitor

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.Canvas
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.coroutines.delay
import org.json.JSONObject

class MainActivity: ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MaterialTheme { MonitorScreen() } }
    }
}

@Composable private fun Record(title: String, body: String) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp),verticalArrangement=Arrangement.spacedBy(6.dp)) {
            Text(title,style=MaterialTheme.typography.titleMedium)
            Text(body,style=MaterialTheme.typography.bodyMedium)
        }
    }
}

@Composable private fun MonitorScreen(vm: MonitorViewModel=viewModel()) {
    val state by vm.state.collectAsStateWithLifecycle()
    var base by remember { mutableStateOf(DEFAULT_SERVER) }
    var token by remember { mutableStateOf("") }
    var page by remember { mutableStateOf("概览") }
    var search by remember { mutableStateOf("") }
    var notificationDenied by remember { mutableStateOf(false) }
    var requestedMode by remember { mutableStateOf<String?>(null) }
    var controlToken by remember { mutableStateOf("") }
    var editingBudget by remember { mutableStateOf(false) }
    var editingLiveBudget by remember { mutableStateOf(false) }
    val lifecycle=LocalLifecycleOwner.current.lifecycle
    val permission=rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        notificationDenied=!granted
        if(granted) vm.background(true)
    }
    LaunchedEffect(lifecycle,state.connected) {
        if(!state.connected) { requestedMode=null;controlToken="";editingBudget=false;editingLiveBudget=false }
        if(state.connected) token=""
        if(state.connected) lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            while(true) { delay(15000);vm.refresh() }
        }
    }
    Surface(Modifier.fillMaxSize()) {
        Column(Modifier.safeDrawingPadding().padding(horizontal=16.dp)) {
            Text("OBR Math",style=MaterialTheme.typography.headlineMedium,modifier=Modifier.padding(top=16.dp))
            Text("原生监控 · 模拟盘与实盘双通道共用信号")
            if(state.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            if(state.error.isNotEmpty()) Text(state.error,color=MaterialTheme.colorScheme.error)
            if(!state.connected) {
                OutlinedTextField(base,{base=it},label={Text("服务器 HTTPS 地址")},singleLine=true,modifier=Modifier.fillMaxWidth())
                OutlinedTextField(token,{token=it},label={Text("监控访问令牌")},visualTransformation=PasswordVisualTransformation(),singleLine=true,modifier=Modifier.fillMaxWidth())
                Button(onClick={vm.connect(base,token.trim())},enabled=!state.busy && token.isNotBlank()) { Text("连接") }
                Text("默认仅在内存保留令牌。连接成功后可开启加密保存与后台提醒。")
            } else {
                val pages=listOf("概览","信号","股票池","持仓","进化","回放","手续费","日报","告警","设置")
                ScrollableTabRow(selectedTabIndex=pages.indexOf(page),edgePadding=0.dp) {
                    pages.forEach { name -> Tab(selected=page==name,onClick={page=name;if(name=="进化") vm.loadEvolution()},text={Text(name)}) }
                }
                Row { TextButton(onClick=vm::refresh,enabled=!state.busy) { Text("刷新") }
                    TextButton(onClick=vm::disconnect) { Text("断开并清除后台凭据") } }
                val d=state.dashboard
                LazyColumn(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(10.dp),contentPadding=PaddingValues(bottom=24.dp)) {
                    if(d!=null) when(page) {
                        "概览" -> {
                            item { Record("运行状态","${d.status.optString("health")} · ${d.status.optString("mode")}\n行情：${d.status.optString("market_connection")}\n市场：${d.status.optString("market_phase")}") }
                            item { Record("双模块共用信号",sharedSignalSummary(d.status.optJSONObject("trading_modes"))) }
                            item { Record("股票观察","候选 ${d.status.optInt("candidate_count")} · 重点 ${d.status.optInt("focus_count")}") }
                            item { Record("行情通道与连续性",feedHealthSummary(d.status)) }
                            item { Record("待满足条件",d.status.optJSONArray("blockers")?.strings()?.joinToString("\n") ?: "暂无") }
                            item { val m=d.metrics.optJSONObject("latest");Record("性能指标","处理 P95：${m?.optJSONObject("processing")?.opt("p95_ms") ?: "未测得"} ms\n内存：${m?.opt("rss_bytes") ?: "未测得"} bytes") }
                        }
                        "信号" -> {
                            if(d.signals.length()==0) item { Text("暂无研究信号") }
                            items(d.signals.objects()) { row -> Record(row.optString("symbol"),"${row.optString("kind")} · ${row.optString("state")}\n${row.optString("reason")}") }
                        }
                        "股票池" -> {
                            item {
                                val ver=d.universe.optJSONObject("instrument_verification")
                                Record("权威资产元数据状态","状态：${d.universe.optString("metadata_status")}\n已核验 US STOCK/ETF：${ver?.optInt("verified_count") ?: 0} · 待核验：${ver?.optInt("unverified_count") ?: d.universe.optJSONArray("symbols")?.length() ?: 0}")
                            }
                            item { OutlinedTextField(search,{search=it},label={Text("搜索股票代码")},modifier=Modifier.fillMaxWidth()) }
                            items(d.universe.optJSONArray("symbols")?.strings()?.filter { it.contains(search,true) } ?: emptyList()) { symbol ->
                                Record(symbol,d.universe.optJSONObject("rules")?.optJSONObject(symbol)?.optString("tradability") ?: "待核验")
                            }
                        }
                        "持仓" -> {
                            item { Record("实盘仓位配置（自定义参数）",liveConfigSummary(d.status.optJSONObject("trading_modes"))) }
                            item { Record("实盘独立账本（MAIN/USDC -> CARD）",liveLedgerSummary(d.status.optJSONObject("trading_modes"))) }
                            item { val c=d.positions.optJSONObject("configuration");Record("模拟预算","初始资金 $${c?.optString("initial_cash")} · 单笔上限 $${c?.optString("per_order_budget")}\n同时持仓上限 ${c?.optInt("max_positions")} 笔") }
                            item { Text(if(d.positions.optBoolean("enabled")) "模拟账户已建立 · 仅模拟成交" else "等待模拟账户核验：${d.positions.optString("reason")}") }
                            item { Record("开仓状态",d.positions.optJSONArray("entry_blockers")?.strings()?.joinToString("\n")?.ifEmpty { "请查看首页市场时段与运行状态" } ?: "等待状态") }
                            if(d.positions.optBoolean("enabled")) item { Record("模拟资金","可用 $${d.positions.optString("cash")} · 当日已实现盈亏 $${d.positions.optString("realized_pnl")}\n日亏损熔断：${if(d.positions.optBoolean("daily_halted")) "已触发" else "未触发"}") }
                            items(d.positions.optJSONArray("alerts")?.strings() ?: emptyList()) { alert -> Record("持仓风控",alert) }
                            val positions=d.positions.optJSONArray("positions")?.objects() ?: emptyList()
                            if(positions.isEmpty()) item { Text("暂无持仓") }
                            items(positions) { row -> Record(row.optString("symbol"),"数量 ${row.optString("quantity")} · 成本 ${row.optString("cost")}") }
                            item { Text("最近模拟订单") }
                            items((d.positions.optJSONArray("orders")?.objects() ?: emptyList()).takeLast(30).reversed()) { row -> Record("${row.optString("symbol")} · ${row.optString("side")}","${row.optString("state")} · ${row.optString("reason")}\n数量 ${row.optString("quantity")} · 已成交 ${row.optString("filled")} · 限价 ${row.optString("limit")}") }
                            item { Text("最近模拟成交") }
                            items((d.positions.optJSONArray("fills")?.objects() ?: emptyList()).takeLast(30).reversed()) { row -> Record("${row.optString("symbol")} · ${row.optString("side")}","数量 ${row.optString("quantity")} · 价格 ${row.optString("price")} · 费用 ${row.optString("fee")}") }
                        }
                        "进化" -> {
                            item {
                                val act=state.evolution?.optJSONObject("active_strategy")
                                val verId=act?.optString("version_id") ?: d.status.optString("active_strategy_version","closed-bar-momentum-v2")
                                Record("自我进化与自动复盘引擎","当前稳定版本：$verId\n闭环流程：模拟/实盘记录 -> 5周期自动复盘 -> 外部 AI (Codex/Antigravity) 诊断优化 -> 历史回测+样本外验证 -> 安全晋升迭代")
                            }
                            item { Button(onClick=vm::loadEvolution,enabled=!state.busy) { Text("刷新全周期自动复盘与 AI 诊断") } }
                            val latest=state.evolution?.optJSONObject("latest_reviews_by_period")
                            if(latest!=null) {
                                listOf("DAILY" to "每日复盘","TRADING_5D" to "每5个交易日复盘","MONTHLY" to "每月复盘","QUARTERLY" to "每季度复盘","SEMIANNUAL" to "每半年复盘").forEach { (k,title) ->
                                    item { Record(title,evolutionPeriodSummary(latest.optJSONObject(k))) }
                                }
                            }
                            val versions=state.evolution?.optJSONArray("strategy_versions")?.objects() ?: emptyList()
                            if(versions.isNotEmpty()) {
                                item { Text("策略与数学模型版本库（未通过样本外验证禁止覆盖稳定版）",style=MaterialTheme.typography.titleMedium) }
                                items(versions) { v ->
                                    val ev=v.optJSONObject("validation_evidence")
                                    Record("${v.optString("version_id")} · ${v.optString("status")}",
                                        "说明：${v.optString("notes")}\n样本外验证通过：${ev?.optBoolean("passed_validation")==true} · 样本外净收益：$${ev?.optString("out_of_sample_net_pnl","0")}")
                                }
                            }
                        }
                        "手续费" -> {
                            item { Record("官方费用核查",when(d.fees.optString("status")) { "CURRENT_PUBLIC_SCHEDULE" -> "公开规则已核查";"STALE" -> "核查已过期，等待更新";else -> "尚无有效核查记录" }) }
                            item { Text("来源：${d.fees.optString("source")}\n官方核查每天北京时间09:00；账户适用费率仍待确认。") }
                            items(d.fees.optJSONObject("observation")?.optJSONObject("terms")?.optJSONArray("rules")?.objects() ?: emptyList()) { row -> Record(row.optString("id"),row.toString(2)) }
                        }
                        "回放" -> {
                            item { Text("合成样例回放",style=MaterialTheme.typography.titleMedium) }
                            item { Text("使用固定合成行情与假设费用，演示开仓、止盈、止损和日亏损熔断。与线上账户完全隔离，不代表实际收益。") }
                            item { Button(onClick=vm::demo) { Text("查看交易流程样例") } }
                            items(state.demo?.optJSONArray("scenarios")?.objects() ?: emptyList()) { scenario ->
                                val account=scenario.optJSONObject("account")
                                Column(verticalArrangement=Arrangement.spacedBy(8.dp)) {
                                    Record(when(scenario.optString("scenario")) { "TAKE_PROFIT" -> "止盈退出";"STOP_LOSS" -> "止损退出";else -> "日亏损熔断" },
                                        "合成模拟 · 可用资金 $${account?.optString("cash")}\n已实现盈亏 $${account?.optString("realized_pnl")}")
                                    EquityChart(scenario.optJSONArray("equity_curve")?.objects() ?: emptyList())
                                    (account?.optJSONArray("fills")?.objects() ?: emptyList()).forEach { fill ->
                                        Text("${fill.optString("side")} ${fill.optString("symbol")} · 数量 ${fill.optString("quantity")} · 价格 ${fill.optString("price")} · 费用 ${fill.optString("fee")}")
                                    }
                                }
                            }
                        }
                        "日报" -> {
                            if(d.reports.length()==0) item { Text("暂无日报") }
                            items(d.reports.objects()) { row -> TextButton(onClick={vm.report(row.getString("date"))}) { Text(row.optString("date")) } }
                            item { Text(state.report) }
                        }
                        "告警" -> {
                            if(d.alerts.length()==0) item { Text("暂无告警") }
                            items(d.alerts.objects()) { row -> Record(row.optString("code"),row.optJSONObject("detail")?.toString(2) ?: "") }
                        }
                        "设置" -> {
                            item {
                                val modes=d.status.optJSONObject("trading_modes")
                                Text("交易模式（双通道独立开关 · 共用同一信号）",style=MaterialTheme.typography.titleMedium)
                                Text("实盘与模拟盘可同时开启（模拟盘照样跑）；2 个模块共用 1 套确认信号，账本与持仓完全隔离。")
                                Row(verticalAlignment=androidx.compose.ui.Alignment.CenterVertically) {
                                    Text("模拟盘（照样独立运行）",Modifier.weight(1f))
                                    Switch(checked=modes?.optBoolean("paper_enabled")==true,
                                        enabled=!state.busy && modes?.optBoolean("control_configured")==true,
                                        onCheckedChange={ requestedMode=if(it) "PAPER_ON" else "PAPER_OFF" })
                                }
                                Row(verticalAlignment=androidx.compose.ui.Alignment.CenterVertically) {
                                    Text("实盘（真实资金 · MAIN/USDC -> CARD）",Modifier.weight(1f))
                                    Switch(checked=modes?.optBoolean("live_enabled")==true,
                                        enabled=!state.busy && modes?.optBoolean("live_available")==true && modes.optBoolean("control_configured"),
                                        onCheckedChange={ requestedMode=if(it) "LIVE_ON" else "LIVE_OFF" })
                                }
                                if(modes==null) Text("当前服务器尚未提供模式控制，请先升级服务。")
                                else {
                                    val scope=modes.optJSONObject("live_scope")
                                    if(scope!=null) {
                                        Text("实盘范围：美国上市股票和 ETF；禁止代币化及其他产品。")
                                        Text("买入：${scope.optString("buy_wallet")} 现货钱包 / ${scope.optString("quote_asset")}\n卖出结算：${scope.optString("sell_settlement_wallet")}；不自动划转。")
                                    }
                                    if(!modes.optBoolean("control_configured")) Text("服务器尚未配置独立操作令牌；监控令牌不能切换模式。")
                                    val liveBlockers=modes.optJSONArray("live_blockers")?.strings() ?: emptyList()
                                    if(liveBlockers.isNotEmpty()) Text("实盘对账与核验提示：\n${liveBlockers.joinToString("\n")}")
                                }
                            }
                            item {
                                val modes=d.status.optJSONObject("trading_modes")
                                Record("当前实盘仓位参数",liveConfigSummary(modes))
                                Button(onClick={editingLiveBudget=true},enabled=!state.busy && modes?.optBoolean("control_configured")==true) { Text("编辑实盘仓位与风控参数") }
                                Text("无实盘持仓或未完成挂单时，可随时自定义并保存实盘仓位与止盈止损参数（模拟盘照样运行）。")
                            }
                            item {
                                Button(onClick={editingBudget=true},enabled=!state.busy && d.status.optJSONObject("trading_modes")?.optBoolean("control_configured")==true) { Text("编辑模拟预算与风险限额") }
                                Text("保存模拟预算前请先关闭【模拟盘】开关，等待模拟持仓与订单结束。")
                            }
                            item { Text("后台手续费提醒") }
                            item { Switch(checked=state.background,onCheckedChange={ enabled ->
                                if(enabled && Build.VERSION.SDK_INT>=33) permission.launch(Manifest.permission.POST_NOTIFICATIONS)
                                else vm.background(enabled)
                            }) }
                            item { Text("开启后使用 Android Keystore 加密保存令牌，并约每15分钟检查服务器已有变更。系统省电限制可能延迟提醒；不是每15分钟重新抓取币安。关闭或断开连接会删除保存的凭据。") }
                            if(notificationDenied) item { Text("通知权限未授予，后台提醒未开启；可在系统设置中授权。") }
                            item { Text("当前服务：${state.base}") }
                        }
                    }
                }
            }
        }
    }
    if(editingLiveBudget && state.connected && state.dashboard!=null) {
        val liveCfgObj=state.dashboard!!.status.optJSONObject("trading_modes")?.optJSONObject("live_config") ?: JSONObject()
        LiveBudgetEditor(liveCfgObj,onDismiss={editingLiveBudget=false},onSave={config,control ->
            vm.saveLiveConfig(config,control);editingLiveBudget=false
        })
    } else if(editingBudget && state.connected && state.dashboard!=null) {
        BudgetEditor(state.dashboard!!.paperConfig,onDismiss={editingBudget=false},onSave={config,control ->
            vm.saveConfig(config,control);editingBudget=false
        })
    } else if(requestedMode!=null && state.connected) {
        val target=requestedMode!!
        val dialogTitle=when(target) {
            "LIVE_ON","LIVE","BOTH" -> "开启实盘通道（模拟盘照样跑）"
            "LIVE_OFF" -> "关闭实盘通道（保留模拟盘状态）"
            "PAPER_ON","PAPER" -> "开启模拟盘通道"
            "PAPER_OFF" -> "关闭模拟盘通道"
            else -> "切换交易通道模式"
        }
        val dialogDesc=when(target) {
            "LIVE_ON","LIVE","BOTH" -> "开启实盘通道后，模拟盘与实盘将共用同一套确认信号并行运行（MAIN/USDC 买入 -> CARD 结算，不自动划转）。"
            "LIVE_OFF" -> "停止实盘新开仓（已有实盘持仓继续退出保护），模拟盘保持当前运行状态不变。"
            "PAPER_ON","PAPER" -> "开启模拟盘新开仓，与实盘通道共用同一套策略确认信号。"
            "PAPER_OFF" -> "停止模拟盘新开仓（已有模拟持仓继续退出保护），实盘通道状态保持不变。"
            else -> "停止新开仓，已有持仓继续退出保护。"
        }
        AlertDialog(onDismissRequest={requestedMode=null;controlToken=""},
            title={Text(dialogTitle)},
            text={ Column {
                Text(dialogDesc)
                OutlinedTextField(controlToken,{controlToken=it},label={Text("独立操作令牌")},singleLine=true,visualTransformation=PasswordVisualTransformation())
            } },
            confirmButton={TextButton(enabled=controlToken.length>=32,onClick={
                val revision=state.dashboard?.status?.optJSONObject("trading_modes")?.optInt("revision",-1) ?: -1
                if(revision>=0) vm.changeMode(target,revision,controlToken)
                requestedMode=null;controlToken=""
            }) { Text("确认") }},
            dismissButton={TextButton(onClick={requestedMode=null;controlToken=""}) { Text("取消") }})
    } else if(state.pendingChange!=null && state.dashboard!=null) {
        AlertDialog(onDismissRequest={},title={Text("币安美股手续费变更")},
            text={ LazyColumn(Modifier.heightIn(max=420.dp)) { item { Text(feeSummary(state.dashboard!!.fees)) } } },
            confirmButton={TextButton(onClick=vm::acknowledge) { Text("我已知悉") }})
    }
}

@Composable private fun EquityChart(points: List<JSONObject>) {
    val values=points.map { it.optString("equity").toDoubleOrNull() }.filterNotNull().filter { it.isFinite() }
    if(values.size<2) return
    val low=values.min();val high=values.max();val span=(high-low).coerceAtLeast(0.01)
    Text("样例权益变化（按盘口估值） $${"%.2f".format(low)} — $${"%.2f".format(high)}")
    Canvas(Modifier.fillMaxWidth().height(120.dp)) {
        values.zipWithNext().forEachIndexed { i,(a,b) ->
            drawLine(Color(0xff3c68b4),Offset(size.width*i/(values.size-1),size.height*(1-((a-low)/span).toFloat())),
                Offset(size.width*(i+1)/(values.size-1),size.height*(1-((b-low)/span).toFloat())),strokeWidth=4f)
        }
    }
}

@Composable private fun BudgetEditor(saved: JSONObject,onDismiss: () -> Unit,onSave: (JSONObject,String) -> Unit) {
    val labels=listOf("initial_cash" to "初始模拟资金（美元）","per_order_budget" to "单笔含费上限（美元）",
        "max_positions" to "同时持仓数（1–5）","max_daily_loss" to "日亏损上限（美元）",
        "max_exposure" to "总敞口上限（美元）","max_daily_symbols" to "每日标的数（1–5）")
    val values=remember { mutableStateMapOf<String,String>().apply { labels.forEach { (key,_) -> put(key,saved.optJSONObject("configuration")?.optString(key) ?: "") } } }
    var secret by remember { mutableStateOf("") };var error by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest=onDismiss,title={Text("模拟预算与风险限额")},text={
        LazyColumn(Modifier.heightIn(max=440.dp),verticalArrangement=Arrangement.spacedBy(6.dp)) {
            items(labels) { (key,label) -> OutlinedTextField(values[key] ?: "",{values[key]=it},label={Text(label)},singleLine=true,
                enabled=key!="initial_cash" || !saved.optBoolean("initial_cash_locked")) }
            item { OutlinedTextField(secret,{secret=it},label={Text("独立操作令牌")},singleLine=true,visualTransformation=PasswordVisualTransformation()) }
            item { if(error.isNotBlank()) Text(error,color=MaterialTheme.colorScheme.error) }
        }
    },confirmButton={TextButton(enabled=secret.length>=32,onClick={
        val payload=JSONObject().put("revision",saved.optInt("revision"))
        var valid=true
        labels.forEach { (key,_) ->
            val value=values[key]?.trim() ?: ""
            if(key in setOf("max_positions","max_daily_symbols")) {
                val parsed=value.toIntOrNull();if(parsed==null || parsed !in 1..5) valid=false else payload.put(key,parsed)
            } else {
                val parsed=value.toBigDecimalOrNull();if(parsed==null || parsed.signum()<=0 || value.length>24) valid=false else payload.put(key,value)
            }
        }
        if(valid) { onSave(payload,secret);secret="" } else error="请输入正数金额，数量须为 1 至 5 的整数。"
    }) { Text("保存") }},dismissButton={TextButton(onClick=onDismiss) { Text("取消") }})
}

@Composable private fun LiveBudgetEditor(saved: JSONObject,onDismiss: () -> Unit,onSave: (JSONObject,String) -> Unit) {
    val defaults=mapOf("allocated_usdc" to "600","per_order_budget" to "300","max_positions" to "2",
        "max_daily_loss" to "30","max_exposure" to "600","max_daily_symbols" to "5",
        "take_profit_pct" to "0.0175","stop_loss_pct" to "0.0080")
    val labels=listOf("allocated_usdc" to "实盘分配资金（MAIN 现货 USDC）",
        "per_order_budget" to "单笔含费上限（USDC）",
        "max_positions" to "同时持仓数（1–5）",
        "max_daily_loss" to "日亏损熔断上限（USDC）",
        "max_exposure" to "总敞口上限（USDC）",
        "max_daily_symbols" to "每日标的数上限（1–5）",
        "take_profit_pct" to "止盈比例（如 0.0175 为 1.75%）",
        "stop_loss_pct" to "止损比例（如 0.0080 为 0.80%）")
    val cfg=saved.optJSONObject("configuration")
    val values=remember { mutableStateMapOf<String,String>().apply {
        labels.forEach { (key,_) -> put(key,cfg?.optString(key)?.ifBlank { defaults[key] ?: "" } ?: defaults[key] ?: "") }
    } }
    var secret by remember { mutableStateOf("") };var error by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest=onDismiss,title={Text("实盘仓位与风控参数配置")},text={
        LazyColumn(Modifier.heightIn(max=460.dp),verticalArrangement=Arrangement.spacedBy(6.dp)) {
            item { Text("买入使用 MAIN 现货 USDC，卖出结算至 CARD 钱包；与模拟盘共用同一确认信号。") }
            items(labels) { (key,label) -> OutlinedTextField(values[key] ?: "",{values[key]=it},label={Text(label)},singleLine=true) }
            item { OutlinedTextField(secret,{secret=it},label={Text("独立操作令牌")},singleLine=true,visualTransformation=PasswordVisualTransformation()) }
            item { if(error.isNotBlank()) Text(error,color=MaterialTheme.colorScheme.error) }
        }
    },confirmButton={TextButton(enabled=secret.length>=32,onClick={
        val payload=JSONObject().put("revision",saved.optInt("revision",0))
        var valid=true
        labels.forEach { (key,_) ->
            val value=values[key]?.trim() ?: ""
            if(key in setOf("max_positions","max_daily_symbols")) {
                val parsed=value.toIntOrNull();if(parsed==null || parsed !in 1..5) valid=false else payload.put(key,parsed)
            } else {
                val parsed=value.toBigDecimalOrNull();if(parsed==null || parsed.signum()<=0 || value.length>24) valid=false else payload.put(key,value)
            }
        }
        if(valid) { onSave(payload,secret);secret="" } else error="请输入有效的正数金额/比例，持仓与标的数须为 1 至 5 的整数。"
    }) { Text("保存") }},dismissButton={TextButton(onClick=onDismiss) { Text("取消") }})
}
