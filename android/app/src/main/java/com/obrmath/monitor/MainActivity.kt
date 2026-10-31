package com.obrmath.monitor

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.coroutines.delay
import org.json.JSONObject

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            val vm: MonitorViewModel = viewModel()
            val state by vm.state.collectAsStateWithLifecycle()
            ObrTheme(darkTheme = state.darkTheme) {
                MonitorScreen(vm = vm, state = state)
            }
        }
    }
}

private enum class PrimaryHub(val key: String, val label: String, val iconText: String) {
    OVERVIEW("OVERVIEW", "总览", "◉"),
    MARKET("MARKET", "行情信号", "⚡"),
    TRADING("TRADING", "双通道", "⇄"),
    EVOLUTION("EVOLUTION", "进化投研", "◈"),
    SETTINGS("SETTINGS", "风控设置", "⚙")
}

@Composable
private fun MonitorScreen(vm: MonitorViewModel, state: MonitorState) {
    val p = LocalObrPalette.current
    var base by remember { mutableStateOf(DEFAULT_SERVER) }
    var token by remember { mutableStateOf("") }
    var showLoginToken by remember { mutableStateOf(false) }

    // Navigation & Sub-module states
    var currentHub by remember { mutableStateOf(PrimaryHub.OVERVIEW) }
    var marketSubTab by remember { mutableStateOf("SIGNALS") } // SIGNALS, OUTCOMES, UNIVERSE
    var tradingSubTab by remember { mutableStateOf("PAPER") } // PAPER, LIVE, REPLAY
    var paperDetailTab by remember { mutableStateOf("POSITIONS") } // POSITIONS, ORDERS, FILLS
    var evolutionSubTab by remember { mutableStateOf("REVIEWS") } // REVIEWS, VERSIONS, REPORTS
    var selectedReviewHorizon by remember { mutableStateOf("DAILY") }
    var settingsSubTab by remember { mutableStateOf("CONTROL") } // CONTROL, FEES, ALERTS

    // Search & filter states
    var universeSearch by remember { mutableStateOf("") }
    var universeFilter by remember { mutableStateOf("ALL") } // ALL, FOCUS, BUY_SELL, UNVERIFIED
    var signalSearch by remember { mutableStateOf("") }
    var signalFilter by remember { mutableStateOf("ALL") } // ALL, CONFIRMED, REJECTED

    // Interactive Dialog states
    var notificationDenied by remember { mutableStateOf(false) }
    var requestedMode by remember { mutableStateOf<String?>(null) }
    var editingBudget by remember { mutableStateOf(false) }
    var editingLiveBudget by remember { mutableStateOf(false) }
    var selectedSignalForAudit by remember { mutableStateOf<JSONObject?>(null) }
    var showStrategyLab by remember { mutableStateOf(false) }
    var pendingReviewTrigger by remember { mutableStateOf<String?>(null) }
    var pendingPromoteVersion by remember { mutableStateOf<String?>(null) }

    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        notificationDenied = !granted
        if (granted) vm.background(true)
    }

    LaunchedEffect(lifecycle, state.connected) {
        if (!state.connected) {
            requestedMode = null
            editingBudget = false
            editingLiveBudget = false
            selectedSignalForAudit = null
            showStrategyLab = false
            pendingReviewTrigger = null
            pendingPromoteVersion = null
        }
        if (state.connected) token = ""
        if (state.connected) {
            lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
                while (true) {
                    delay(15000)
                    vm.refresh()
                }
            }
        }
    }

    // Auto-load evolution data when entering Evolution hub
    LaunchedEffect(currentHub, state.connected) {
        if (state.connected && currentHub == PrimaryHub.EVOLUTION && state.evolution == null) {
            vm.loadEvolution()
        }
        if (state.connected && currentHub == PrimaryHub.TRADING && tradingSubTab == "REPLAY" && state.demo == null) {
            vm.demo()
        }
    }

    Surface(
        modifier = Modifier.fillMaxSize(),
        color = p.background
    ) {
        if (!state.connected) {
            LoginTerminalScreen(
                base = base,
                onBaseChange = { base = it },
                token = token,
                onTokenChange = { token = it },
                showToken = showLoginToken,
                onToggleShowToken = { showLoginToken = !showLoginToken },
                busy = state.busy,
                error = state.error,
                darkTheme = state.darkTheme,
                onToggleTheme = vm::toggleTheme,
                onConnect = { vm.connect(base, token.trim()) }
            )
        } else {
            val d = state.dashboard
            val alertsCount = d?.alerts?.length() ?: 0
            val signalsCount = d?.signals?.length() ?: 0

            Scaffold(
                containerColor = p.background,
                topBar = {
                    TerminalTopHeader(
                        state = state,
                        onRefresh = vm::refresh,
                        onToggleTheme = vm::toggleTheme,
                        onDisconnect = vm::disconnect,
                        onRequestModeChange = { requestedMode = it },
                        onJumpTrading = {
                            currentHub = PrimaryHub.TRADING
                            tradingSubTab = "LIVE"
                        },
                        onDismissError = vm::dismissError,
                        onDismissNotice = vm::dismissNotice
                    )
                },
                bottomBar = {
                    NavigationBar(
                        containerColor = p.surface,
                        tonalElevation = 0.dp,
                        modifier = Modifier.border(BorderStroke(1.dp, p.borderSubtle))
                    ) {
                        PrimaryHub.entries.forEach { hub ->
                            val selected = currentHub == hub
                            NavigationBarItem(
                                selected = selected,
                                onClick = { currentHub = hub },
                                icon = {
                                    BadgedBox(
                                        badge = {
                                            if (hub == PrimaryHub.SETTINGS && alertsCount > 0) {
                                                Badge(containerColor = p.warning) {
                                                    Text(alertsCount.coerceAtMost(99).toString())
                                                }
                                            } else if (hub == PrimaryHub.MARKET && signalsCount > 0) {
                                                Badge(containerColor = p.primaryAccent) {
                                                    Text(signalsCount.coerceAtMost(99).toString())
                                                }
                                            }
                                        }
                                    ) {
                                        Text(
                                            text = hub.iconText,
                                            fontSize = 18.sp,
                                            fontWeight = FontWeight.Bold,
                                            color = if (selected) p.primaryAccent else p.textMuted
                                        )
                                    }
                                },
                                label = {
                                    Text(
                                        text = hub.label,
                                        style = MaterialTheme.typography.labelSmall,
                                        fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal
                                    )
                                },
                                colors = NavigationBarItemDefaults.colors(
                                    selectedIconColor = p.primaryAccent,
                                    selectedTextColor = p.primaryAccent,
                                    indicatorColor = p.primaryContainer,
                                    unselectedIconColor = p.textMuted,
                                    unselectedTextColor = p.textMuted
                                )
                            )
                        }
                    }
                }
            ) { innerPadding ->
                LazyColumn(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(innerPadding)
                        .padding(horizontal = 14.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                    contentPadding = PaddingValues(top = 12.dp, bottom = 28.dp)
                ) {
                    if (d != null) {
                        when (currentHub) {
                            PrimaryHub.OVERVIEW -> {
                                OverviewHubContent(
                                    d = d,
                                    onJumpToStock = { sym ->
                                        universeSearch = sym
                                        marketSubTab = "UNIVERSE"
                                        currentHub = PrimaryHub.MARKET
                                    },
                                    onJumpToTrading = { sub ->
                                        tradingSubTab = sub
                                        currentHub = PrimaryHub.TRADING
                                    },
                                    onJumpToEvolution = {
                                        currentHub = PrimaryHub.EVOLUTION
                                    },
                                    onJumpToAlerts = {
                                        settingsSubTab = "ALERTS"
                                        currentHub = PrimaryHub.SETTINGS
                                    }
                                )
                            }
                            PrimaryHub.MARKET -> {
                                MarketSignalsHubContent(
                                    d = d,
                                    subTab = marketSubTab,
                                    onSubTabChange = { marketSubTab = it },
                                    signalSearch = signalSearch,
                                    onSignalSearchChange = { signalSearch = it },
                                    signalFilter = signalFilter,
                                    onSignalFilterChange = { signalFilter = it },
                                    universeSearch = universeSearch,
                                    onUniverseSearchChange = { universeSearch = it },
                                    universeFilter = universeFilter,
                                    onUniverseFilterChange = { universeFilter = it },
                                    onSelectSignal = { selectedSignalForAudit = it }
                                )
                            }
                            PrimaryHub.TRADING -> {
                                DualChannelTradingHubContent(
                                    d = d,
                                    demoData = state.demo,
                                    busy = state.busy,
                                    subTab = tradingSubTab,
                                    onSubTabChange = {
                                        tradingSubTab = it
                                        if (it == "REPLAY" && state.demo == null) vm.demo()
                                    },
                                    paperDetailTab = paperDetailTab,
                                    onPaperDetailTabChange = { paperDetailTab = it },
                                    onRequestModeChange = { requestedMode = it },
                                    onEditPaperBudget = { editingBudget = true },
                                    onEditLiveBudget = { editingLiveBudget = true },
                                    onRunDemo = vm::demo
                                )
                            }
                            PrimaryHub.EVOLUTION -> {
                                EvolutionResearchHubContent(
                                    d = d,
                                    evolution = state.evolution,
                                    selectedReportDate = state.selectedReportDate,
                                    reportContent = state.report,
                                    busy = state.busy,
                                    subTab = evolutionSubTab,
                                    onSubTabChange = { evolutionSubTab = it },
                                    selectedHorizon = selectedReviewHorizon,
                                    onSelectHorizon = { selectedReviewHorizon = it },
                                    onRefreshEvolution = vm::loadEvolution,
                                    onTriggerReview = { pendingReviewTrigger = it },
                                    onOpenStrategyLab = { showStrategyLab = true },
                                    onPromoteVersion = { pendingPromoteVersion = it },
                                    onSelectReportDate = vm::report
                                )
                            }
                            PrimaryHub.SETTINGS -> {
                                RiskSettingsHubContent(
                                    d = d,
                                    state = state,
                                    subTab = settingsSubTab,
                                    onSubTabChange = { settingsSubTab = it },
                                    notificationDenied = notificationDenied,
                                    onRequestModeChange = { requestedMode = it },
                                    onEditPaperBudget = { editingBudget = true },
                                    onEditLiveBudget = { editingLiveBudget = true },
                                    onToggleBackground = { enabled ->
                                        if (enabled && Build.VERSION.SDK_INT >= 33) {
                                            permission.launch(Manifest.permission.POST_NOTIFICATIONS)
                                        } else {
                                            vm.background(enabled)
                                        }
                                    }
                                )
                            }
                        }
                    }
                }
            }
        }
    }

    // ========================================================================
    // Interactive Modals & Action Sheets
    // ========================================================================
    val dash = state.dashboard
    if (selectedSignalForAudit != null && dash != null) {
        SignalDetailDialog(
            signal = selectedSignalForAudit!!,
            outcomes = dash.outcomes.objects(),
            onDismiss = { selectedSignalForAudit = null },
            onJumpToStock = { sym ->
                selectedSignalForAudit = null
                universeSearch = sym
                marketSubTab = "UNIVERSE"
                currentHub = PrimaryHub.MARKET
            }
        )
    } else if (editingLiveBudget && state.connected && dash != null) {
        val liveCfgObj = dash.status.optJSONObject("trading_modes")?.optJSONObject("live_config") ?: JSONObject()
        LiveBudgetEditor(
            saved = liveCfgObj,
            onDismiss = { editingLiveBudget = false },
            onSave = { config, control ->
                vm.saveLiveConfig(config, control)
                editingLiveBudget = false
            }
        )
    } else if (editingBudget && state.connected && dash != null) {
        BudgetEditor(
            saved = dash.paperConfig,
            onDismiss = { editingBudget = false },
            onSave = { config, control ->
                vm.saveConfig(config, control)
                editingBudget = false
            }
        )
    } else if (requestedMode != null && state.connected && dash != null) {
        val revision = dash.status.optJSONObject("trading_modes")?.optInt("revision", -1) ?: -1
        ModeSwitchDialog(
            targetMode = requestedMode!!,
            revision = revision,
            onDismiss = { requestedMode = null },
            onConfirm = { mode, rev, ctrl ->
                vm.changeMode(mode, rev, ctrl)
                requestedMode = null
            }
        )
    } else if (showStrategyLab && state.connected) {
        val activeParams = state.evolution?.optJSONObject("active_strategy")?.optJSONObject("parameters")
        StrategyLabDialog(
            activeParams = activeParams,
            onDismiss = { showStrategyLab = false },
            onSubmit = { verId, params, notes, split, ctrl ->
                vm.proposeAndBacktestStrategy(verId, params, notes, split, ctrl)
                showStrategyLab = false
            }
        )
    } else if (pendingReviewTrigger != null && state.connected) {
        val horizon = pendingReviewTrigger!!
        ControlTokenPromptDialog(
            title = "强制生成 $horizon 周期复盘",
            description = "将立即聚合模拟盘/实盘成交、信号质量与错失机会，生成最新周期归因与 AI 调优建议。",
            confirmLabel = "立即生成",
            onDismiss = { pendingReviewTrigger = null },
            onConfirm = { ctrl ->
                vm.triggerPeriodReview(horizon, ctrl)
                pendingReviewTrigger = null
            }
        )
    } else if (pendingPromoteVersion != null && state.connected) {
        val verId = pendingPromoteVersion!!
        ControlTokenPromptDialog(
            title = "晋升候选版本 $verId 为线上稳定版",
            description = "仅已通过 Walk-Forward 样本外 (OOS) 验证的候选策略允许晋升；晋升后将立即切换实时信号引擎参数。",
            confirmLabel = "确认晋升",
            onDismiss = { pendingPromoteVersion = null },
            onConfirm = { ctrl ->
                vm.promoteStrategyVersion(verId, ctrl)
                pendingPromoteVersion = null
            }
        )
    } else if (state.pendingChange != null && dash != null) {
        AlertDialog(
            onDismissRequest = {},
            title = { Text("币安美股官方手续费变更提醒") },
            text = {
                LazyColumn(Modifier.heightIn(max = 420.dp)) {
                    item { Text(feeSummary(dash.fees)) }
                }
            },
            confirmButton = {
                Button(onClick = vm::acknowledge) { Text("我已知悉并核对") }
            }
        )
    }
}

// ============================================================================
// 0. Login / Onboarding Terminal Screen
// ============================================================================

@Composable
private fun LoginTerminalScreen(
    base: String,
    onBaseChange: (String) -> Unit,
    token: String,
    onTokenChange: (String) -> Unit,
    showToken: Boolean,
    onToggleShowToken: () -> Unit,
    busy: Boolean,
    error: String,
    darkTheme: Boolean,
    onToggleTheme: () -> Unit,
    onConnect: () -> Unit
) {
    val p = LocalObrPalette.current
    Column(
        modifier = Modifier
            .fillMaxSize()
            .safeDrawingPadding()
            .padding(horizontal = 20.dp),
        verticalArrangement = Arrangement.Center
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            StatusPill(text = "QUANT TERMINAL · V0.6", tone = BadgeTone.INFO)
            TextButton(onClick = onToggleTheme) {
                Text(if (darkTheme) "☀ 日间模式" else "☾ 机构暗色", color = p.primaryAccent)
            }
        }
        Spacer(Modifier.height(8.dp))
        Text(
            text = "OBR / MATH",
            color = p.textPrimary,
            style = MaterialTheme.typography.headlineMedium,
            fontSize = 30.sp
        )
        Text(
            text = "美股开盘区间突破与趋势延续 · 模拟盘/实盘双通道共用信号终端",
            color = p.textSecondary,
            style = MaterialTheme.typography.bodyMedium
        )
        Spacer(Modifier.height(20.dp))

        Surface(
            shape = RoundedCornerShape(16.dp),
            color = p.cardContainer,
            border = BorderStroke(1.dp, p.borderSubtle),
            modifier = Modifier.fillMaxWidth()
        ) {
            Column(
                modifier = Modifier.padding(18.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = "安全终端接入",
                        color = p.textPrimary,
                        style = MaterialTheme.typography.titleMedium
                    )
                    if (base != DEFAULT_SERVER) {
                        TextButton(
                            onClick = { onBaseChange(DEFAULT_SERVER) },
                            contentPadding = PaddingValues(horizontal = 8.dp, vertical = 2.dp)
                        ) {
                            Text("恢复默认地址", style = MaterialTheme.typography.labelSmall)
                        }
                    }
                }

                OutlinedTextField(
                    value = base,
                    onValueChange = onBaseChange,
                    label = { Text("服务器 HTTPS 根地址") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )

                OutlinedTextField(
                    value = token,
                    onValueChange = onTokenChange,
                    label = { Text("监控只读访问令牌 (Bearer Token)") },
                    visualTransformation = if (showToken) VisualTransformation.None else PasswordVisualTransformation(),
                    trailingIcon = {
                        TextButton(onClick = onToggleShowToken) {
                            Text(if (showToken) "隐藏" else "显示", style = MaterialTheme.typography.labelSmall)
                        }
                    },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )

                if (busy) {
                    LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                }
                if (error.isNotEmpty()) {
                    Surface(
                        shape = RoundedCornerShape(8.dp),
                        color = p.bearishContainer,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text(
                            text = error,
                            color = p.bearish,
                            style = MaterialTheme.typography.bodySmall,
                            modifier = Modifier.padding(10.dp)
                        )
                    }
                }

                Button(
                    onClick = onConnect,
                    enabled = !busy && token.isNotBlank(),
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(48.dp),
                    shape = RoundedCornerShape(10.dp)
                ) {
                    Text("连接量化监控终端", fontWeight = FontWeight.Bold)
                }

                Text(
                    text = "安全边界：默认仅在内存保留监控令牌。写操作（开关通道、修改预算、晋升策略）均要求独立 32 位操作令牌二次鉴权。",
                    color = p.textMuted,
                    style = MaterialTheme.typography.bodySmall
                )
            }
        }

        Spacer(Modifier.height(16.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            StatusPill("TLS 1.3 强校验", BadgeTone.BULLISH, showDot = false, modifier = Modifier.weight(1f))
            StatusPill("MAIN→CARD 隔离", BadgeTone.INFO, showDot = false, modifier = Modifier.weight(1f))
            StatusPill("5周期 AI 进化", BadgeTone.PAPER, showDot = false, modifier = Modifier.weight(1f))
        }
    }
}

// ============================================================================
// Persistent Top Header & Dual-Channel Quick Bar
// ============================================================================

@Composable
private fun TerminalTopHeader(
    state: MonitorState,
    onRefresh: () -> Unit,
    onToggleTheme: () -> Unit,
    onDisconnect: () -> Unit,
    onRequestModeChange: (String) -> Unit,
    onJumpTrading: () -> Unit,
    onDismissError: () -> Unit,
    onDismissNotice: () -> Unit
) {
    val p = LocalObrPalette.current
    val status = state.dashboard?.status
    val health = status?.optString("health", "UNKNOWN") ?: "UNKNOWN"
    val phase = status?.optString("market_phase", "UNKNOWN") ?: "UNKNOWN"
    val modes = status?.optJSONObject("trading_modes")

    val healthTone = when (health) {
        "HEALTHY" -> BadgeTone.BULLISH
        "CRITICAL" -> BadgeTone.BEARISH
        else -> BadgeTone.WARNING
    }
    val phaseTone = if (phase == "RTH_OPEN") BadgeTone.BULLISH else BadgeTone.NEUTRAL

    Surface(
        color = p.surface,
        border = BorderStroke(1.dp, p.borderSubtle),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(
            modifier = Modifier
                .statusBarsPadding()
                .padding(horizontal = 14.dp, vertical = 10.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Text(
                        text = "OBR / MATH",
                        color = p.textPrimary,
                        style = MaterialTheme.typography.titleLarge,
                        fontFamily = FontFamily.Monospace
                    )
                    StatusPill(text = health, tone = healthTone)
                    StatusPill(text = if (phase == "RTH_OPEN") "盘中 RTH" else "休市/盘后", tone = phaseTone, showDot = false)
                }

                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(2.dp)
                ) {
                    TextButton(
                        onClick = onRefresh,
                        enabled = !state.busy,
                        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 4.dp)
                    ) {
                        Text("刷新 ${state.lastRefreshTime}", style = MaterialTheme.typography.labelSmall)
                    }
                    TextButton(
                        onClick = onToggleTheme,
                        contentPadding = PaddingValues(horizontal = 6.dp, vertical = 4.dp)
                    ) {
                        Text(if (state.darkTheme) "☀" else "☾", fontSize = 15.sp)
                    }
                    TextButton(
                        onClick = onDisconnect,
                        contentPadding = PaddingValues(horizontal = 6.dp, vertical = 4.dp)
                    ) {
                        Text("断开", color = p.bearish, style = MaterialTheme.typography.labelSmall)
                    }
                }
            }

            DualChannelControlStrip(
                modes = modes,
                busy = state.busy,
                onRequestModeChange = onRequestModeChange,
                onJumpTrading = onJumpTrading
            )

            if (state.busy) {
                LinearProgressIndicator(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(2.dp),
                    color = p.primaryAccent
                )
            }

            if (state.error.isNotEmpty()) {
                Surface(
                    shape = RoundedCornerShape(8.dp),
                    color = p.bearishContainer,
                    border = BorderStroke(1.dp, p.bearish.copy(alpha = 0.5f)),
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onDismissError() }
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = state.error,
                            color = p.bearish,
                            style = MaterialTheme.typography.bodySmall,
                            modifier = Modifier.weight(1f)
                        )
                        Text("✕", color = p.bearish, style = MaterialTheme.typography.labelSmall)
                    }
                }
            }

            if (state.notice.isNotEmpty()) {
                Surface(
                    shape = RoundedCornerShape(8.dp),
                    color = p.bullishContainer,
                    border = BorderStroke(1.dp, p.bullish.copy(alpha = 0.5f)),
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onDismissNotice() }
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = state.notice,
                            color = p.bullish,
                            style = MaterialTheme.typography.bodySmall,
                            modifier = Modifier.weight(1f)
                        )
                        Text("✕", color = p.bullish, style = MaterialTheme.typography.labelSmall)
                    }
                }
            }
        }
    }
}

// ============================================================================
// 1. OVERVIEW HUB (总览)
// ============================================================================

private fun LazyListScope.OverviewHubContent(
    d: Dashboard,
    onJumpToStock: (String) -> Unit,
    onJumpToTrading: (String) -> Unit,
    onJumpToEvolution: () -> Unit,
    onJumpToAlerts: () -> Unit
) {
    val s = d.status
    val m = d.metrics.optJSONObject("latest")
    val modes = s.optJSONObject("trading_modes")
    val pos = d.positions

    val p95Ms = m?.optJSONObject("processing")?.optDouble("p95_ms", Double.NaN) ?: Double.NaN
    val p95Str = if (!p95Ms.isNaN()) "${"%.2f".format(p95Ms)} ms" else "未测得"
    val rssBytes = m?.optLong("rss_bytes", 0L) ?: 0L
    val rssMb = if (rssBytes > 0) "${"%.1f".format(rssBytes / 1048576.0)} MB" else "未测得"

    val paperCash = pos.optString("cash", pos.optJSONObject("configuration")?.optString("initial_cash", "600") ?: "600")
    val paperPnl = pos.optString("realized_pnl", "0.00")
    val liveFree = modes?.optJSONObject("live_ledger")?.optString("main_usdc_free", "0.00") ?: "0.00"
    val cardSettle = modes?.optJSONObject("live_ledger")?.optString("card_settlement_usdc", "0.00") ?: "0.00"

    // 4-Card KPI Hero Grid (2x2)
    item {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                KpiMetricCard(
                    label = "股票池覆盖 / 重点订阅",
                    value = "${s.optInt("observed_symbols")} / ${s.optInt("candidate_count")}",
                    subtitle = "Focus 焦点标的 ${s.optInt("focus_count")} 个",
                    tone = BadgeTone.INFO,
                    modifier = Modifier.weight(1f),
                    onClick = { onJumpToStock("") }
                )
                KpiMetricCard(
                    label = "内部计算延迟 P95",
                    value = p95Str,
                    subtitle = "进程内存 $rssMb",
                    tone = if (!p95Ms.isNaN() && p95Ms <= 20.0) BadgeTone.BULLISH else BadgeTone.INFO,
                    modifier = Modifier.weight(1f)
                )
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                KpiMetricCard(
                    label = "模拟盘可用资金",
                    value = formatUsd(paperCash),
                    subtitle = "今日已实现盈亏 ${formatUsd(paperPnl)}",
                    tone = BadgeTone.PAPER,
                    modifier = Modifier.weight(1f),
                    onClick = { onJumpToTrading("PAPER") }
                )
                KpiMetricCard(
                    label = "实盘 MAIN 可用 USDC",
                    value = formatUsd(liveFree),
                    subtitle = "CARD 结算累计 ${formatUsd(cardSettle)}",
                    tone = BadgeTone.BULLISH,
                    modifier = Modifier.weight(1f),
                    onClick = { onJumpToTrading("LIVE") }
                )
            }
        }
    }

    // Active Strategy & Shared Signal Architecture Card
    item {
        val activeVer = s.optString("active_strategy_version", "closed-bar-momentum-v2")
        TerminalSectionCard(
            title = "双通道共用信号与策略引擎",
            subtitle = sharedSignalSummary(modes),
            badgeText = activeVer,
            badgeTone = BadgeTone.INFO,
            actionLabel = "进化复盘",
            onAction = onJumpToEvolution
        ) {
            KeyValueMetricRow("当前运行模式", translateMode(s.optString("mode")))
            KeyValueMetricRow("市场交易时段", translateMarketPhase(s.optString("market_phase")))
            KeyValueMetricRow(
                "交易所规则核验",
                if (s.optBoolean("rules_verified")) "已通过只读核验" else "待核验 (未配置或超期)"
            )
            val momReady = s.optJSONArray("momentum_ready_symbols")?.length() ?: 0
            KeyValueMetricRow("多周期动量就绪标的", "$momReady / ${s.optInt("focus_count")} 个焦点标的")
        }
    }

    // Focus Symbols Quick-Jump Strip
    val focusSymbols = s.optJSONArray("focus_symbols")?.strings() ?: emptyList()
    if (focusSymbols.isNotEmpty()) {
        item {
            TerminalSectionCard(
                title = "重点实时订阅标的 (Tier-1 Focus)",
                subtitle = "订阅实时盘口 Quote、闭合 5m K 线及交易状态流，点击代码直达标的详情",
                badgeText = "${focusSymbols.size} 标的",
                badgeTone = BadgeTone.BULLISH
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    focusSymbols.forEach { sym ->
                        StatusPill(
                            text = sym,
                            tone = BadgeTone.INFO,
                            showDot = true,
                            onClick = { onJumpToStock(sym) }
                        )
                    }
                }
            }
        }
    }

    // Interactive Blocker Diagnostics Checklist
    val blockers = s.optJSONArray("blockers")?.strings() ?: emptyList()
    item {
        TerminalSectionCard(
            title = "开仓前置风控门控诊断 (Fail-Closed Gate)",
            subtitle = if (blockers.isEmpty()) "所有前置风控条件已满足，盘中收到确认信号即可执行" else "以下任一条件未满足时，系统保持只读观察并阻断自动新开仓",
            badgeText = if (blockers.isEmpty()) "全部就绪" else "${blockers.size} 项阻断",
            badgeTone = if (blockers.isEmpty()) BadgeTone.BULLISH else BadgeTone.WARNING
        ) {
            if (blockers.isEmpty()) {
                StatusPill("✓ 费率、量能、连续性与通道条件全部达标", BadgeTone.BULLISH)
            } else {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    blockers.forEach { code ->
                        BlockerDiagnosticCard(diagnoseBlocker(code))
                    }
                }
            }
        }
    }

    // WebSocket Multi-Feed Continuity Matrix
    val feeds = s.optJSONArray("feeds")?.objects() ?: emptyList()
    item {
        TerminalSectionCard(
            title = "行情 WebSocket 通道与连续性矩阵",
            subtitle = "源行情时间与内部耗时独立核算；断流缺口自动触发防污染锁定",
            badgeText = s.optString("market_connection"),
            badgeTone = if (s.optString("market_connection") == "CONNECTED") BadgeTone.BULLISH else BadgeTone.WARNING
        ) {
            if (feeds.isEmpty()) {
                Text("暂无行情通道实例", color = LocalObrPalette.current.textMuted)
            } else {
                val p = LocalObrPalette.current
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    feeds.forEachIndexed { idx, f ->
                        val role = f.optString("role").ifBlank { "feed_$idx" }
                        val connected = f.optBoolean("connected")
                        val gap = f.optBoolean("data_gap")
                        val roleName = when (role) {
                            "price" -> "全市场价格流 (price)"
                            "focus_market" -> "焦点盘口与 5m K线 (focus_market)"
                            "focus_status" -> "可交易与停牌状态流 (focus_status)"
                            else -> "通道 ($role)"
                        }
                        Surface(
                            shape = RoundedCornerShape(10.dp),
                            color = p.cardElevated,
                            border = BorderStroke(1.dp, p.borderSubtle),
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Column(
                                modifier = Modifier.padding(10.dp),
                                verticalArrangement = Arrangement.spacedBy(4.dp)
                            ) {
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    Text(roleName, color = p.textPrimary, style = MaterialTheme.typography.titleSmall)
                                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                        StatusPill(
                                            text = if (connected) "已连接" else "重连中",
                                            tone = if (connected) BadgeTone.BULLISH else BadgeTone.BEARISH
                                        )
                                        StatusPill(
                                            text = if (gap) "缺口锁定" else "连续正常",
                                            tone = if (gap) BadgeTone.WARNING else BadgeTone.INFO,
                                            showDot = false
                                        )
                                    }
                                }
                                Text(
                                    text = "队列深度 ${f.optInt("queue")} · 累计重连 ${f.optInt("reconnects")} 次 · 丢弃消息 ${f.optInt("dropped")}",
                                    color = p.textMuted,
                                    style = MaterialTheme.typography.labelSmall
                                )
                            }
                        }
                    }
                }
            }
        }
    }

    // Recent System Alerts Preview if any
    val alerts = d.alerts.objects()
    if (alerts.isNotEmpty()) {
        item {
            TerminalSectionCard(
                title = "最新系统告警摘要",
                badgeText = "${alerts.size} 条记录",
                badgeTone = BadgeTone.WARNING,
                actionLabel = "查看全部",
                onAction = onJumpToAlerts
            ) {
                alerts.take(3).forEach { a ->
                    KeyValueMetricRow(
                        label = a.optString("code"),
                        value = formatTimestampMs(a.optLong("time_ms", 0L))
                    )
                }
            }
        }
    }
}

// ============================================================================
// 2. MARKET & SIGNALS HUB (行情与信号)
// ============================================================================

private fun LazyListScope.MarketSignalsHubContent(
    d: Dashboard,
    subTab: String,
    onSubTabChange: (String) -> Unit,
    signalSearch: String,
    onSignalSearchChange: (String) -> Unit,
    signalFilter: String,
    onSignalFilterChange: (String) -> Unit,
    universeSearch: String,
    onUniverseSearchChange: (String) -> Unit,
    universeFilter: String,
    onUniverseFilterChange: (String) -> Unit,
    onSelectSignal: (JSONObject) -> Unit
) {
    val allSignals = d.signals.objects()
    val allOutcomes = d.outcomes.objects()
    val allSymbols = d.universe.optJSONArray("symbols")?.strings() ?: emptyList()

    item {
        SegmentedControlBar(
            options = listOf(
                "SIGNALS" to "突破信号 (${allSignals.size})",
                "OUTCOMES" to "后验表现 (${allOutcomes.size})",
                "UNIVERSE" to "股票池 (${allSymbols.size})"
            ),
            selectedKey = subTab,
            onSelect = onSubTabChange
        )
    }

    when (subTab) {
        "SIGNALS" -> {
            val confirmedCount = allSignals.count { it.optString("state") == "CONFIRMED" }
            val rejectedCount = allSignals.size - confirmedCount

            item {
                TerminalSectionCard(
                    title = "ORB 开盘突破与盘中延续信号流",
                    subtitle = "点击任意信号卡片可穿透查看量化指标、拒绝原因与信号后多周期表现",
                    badgeText = "确认 $confirmedCount / 总计 ${allSignals.size}",
                    badgeTone = if (confirmedCount > 0) BadgeTone.BULLISH else BadgeTone.INFO
                ) {
                    OutlinedTextField(
                        value = signalSearch,
                        onValueChange = onSignalSearchChange,
                        label = { Text("按股票代码或原因筛选信号 (如 AAPL, RVOL)") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                    FilterChipRow(
                        options = listOf(
                            "ALL" to "全部信号 (${allSignals.size})",
                            "CONFIRMED" to "已确认 CONFIRMED ($confirmedCount)",
                            "REJECTED" to "未通过过滤 ($rejectedCount)"
                        ),
                        selectedKey = signalFilter,
                        onSelect = onSignalFilterChange
                    )
                }
            }

            val filteredSignals = allSignals.filter { row ->
                val stateMatch = when (signalFilter) {
                    "CONFIRMED" -> row.optString("state") == "CONFIRMED"
                    "REJECTED" -> row.optString("state") != "CONFIRMED"
                    else -> true
                }
                val q = signalSearch.trim()
                val queryMatch = q.isEmpty() ||
                    row.optString("symbol").contains(q, ignoreCase = true) ||
                    row.optString("reason").contains(q, ignoreCase = true) ||
                    row.optString("kind").contains(q, ignoreCase = true)
                stateMatch && queryMatch
            }

            if (filteredSignals.isEmpty()) {
                item {
                    TerminalSectionCard(
                        title = "暂无匹配的策略信号",
                        subtitle = "系统仅在盘中闭合 5 分钟 K 线产生真实评估记录，绝不填充虚假示例信号。"
                    ) {
                        Text(
                            text = "当美股开盘 (RTH_OPEN) 且焦点标的完成 K 线闭合后，突破与趋势延续评估将实时流式展示在此处。",
                            color = LocalObrPalette.current.textMuted,
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                }
            } else {
                items(filteredSignals) { row ->
                    val p = LocalObrPalette.current
                    val symbol = row.optString("symbol")
                    val kind = row.optString("kind")
                    val state = row.optString("state")
                    val reason = row.optString("reason")
                    val refPrice = row.optString("reference_price")
                    val isConfirmed = state == "CONFIRMED"

                    Surface(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(12.dp))
                            .clickable { onSelectSignal(row) },
                        shape = RoundedCornerShape(12.dp),
                        color = p.cardContainer,
                        border = BorderStroke(
                            1.dp,
                            if (isConfirmed) p.bullish.copy(alpha = 0.5f) else p.borderSubtle
                        )
                    ) {
                        Column(
                            modifier = Modifier.padding(14.dp),
                            verticalArrangement = Arrangement.spacedBy(6.dp)
                        ) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Row(
                                    verticalAlignment = Alignment.CenterVertically,
                                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                                ) {
                                    Text(
                                        text = symbol,
                                        color = p.textPrimary,
                                        fontFamily = FontFamily.Monospace,
                                        fontWeight = FontWeight.ExtraBold,
                                        fontSize = 17.sp
                                    )
                                    StatusPill(text = kind, tone = BadgeTone.INFO, showDot = false)
                                }
                                StatusPill(
                                    text = if (isConfirmed) "CONFIRMED" else state,
                                    tone = if (isConfirmed) BadgeTone.BULLISH else BadgeTone.WARNING
                                )
                            }
                            Text(
                                text = translateSignalReason(reason),
                                color = p.textSecondary,
                                style = MaterialTheme.typography.bodySmall
                            )
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween
                            ) {
                                Text(
                                    text = "参考价: ${if (refPrice.isNotBlank()) "$$refPrice" else "—"} · 原始码: $reason",
                                    color = p.textMuted,
                                    style = MaterialTheme.typography.labelSmall
                                )
                                Text(
                                    text = "${formatTimestampMs(row.optLong("source_ms", 0L))} 详情 ▶",
                                    color = p.primaryAccent,
                                    style = MaterialTheme.typography.labelSmall
                                )
                            }
                        }
                    }
                }
            }
        }

        "OUTCOMES" -> {
            item {
                TerminalSectionCard(
                    title = "信号后多周期表现追踪 (Post-Signal Outcomes)",
                    subtitle = "自动追踪信号触发后 5m / 15m / 30m / 60m 及当日收盘的价格演化（仅用于离线研究，不反向污染实时策略）",
                    badgeText = "${allOutcomes.size} 条记录",
                    badgeTone = BadgeTone.INFO
                ) {
                    if (allOutcomes.isEmpty()) {
                        Text(
                            text = "当前暂无已完成的信号后周期表现样本。当盘中信号产生并经过 5/15/30/60 分钟采样后将自动落盘展示。",
                            color = LocalObrPalette.current.textMuted,
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                }
            }
            items(allOutcomes) { out ->
                val p = LocalObrPalette.current
                Surface(
                    shape = RoundedCornerShape(12.dp),
                    color = p.cardContainer,
                    border = BorderStroke(1.dp, p.borderSubtle),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(
                        modifier = Modifier.padding(14.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp)
                    ) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Text(
                                text = out.optString("symbol", "标的"),
                                color = p.textPrimary,
                                fontFamily = FontFamily.Monospace,
                                fontWeight = FontWeight.Bold,
                                fontSize = 16.sp
                            )
                            StatusPill(
                                text = "${out.optString("horizon_minutes", out.optString("horizon", "追踪"))} min",
                                tone = BadgeTone.INFO,
                                showDot = false
                            )
                        }
                        KeyValueMetricRow("触发参考价", formatUsd(out.optString("reference_price", "0")))
                        KeyValueMetricRow("观察窗口价格", formatUsd(out.optString("observed_price", out.optString("price", "0"))))
                        KeyValueMetricRow("收益率表现", formatPct(out.optString("return_pct", "0")))
                    }
                }
            }
        }

        "UNIVERSE" -> {
            val ver = d.universe.optJSONObject("instrument_verification")
            val verifiedCount = ver?.optInt("verified_count", 0) ?: 0
            val totalCount = allSymbols.size.coerceAtLeast(1)
            val focusList = d.universe.optJSONArray("focus")?.strings()?.toSet() ?: emptySet()
            val rulesObj = d.universe.optJSONObject("rules")

            item {
                TerminalSectionCard(
                    title = "美国上市股票与 ETF 候选池",
                    subtitle = "严格限定正规美国上市股票与 ETF，禁止股票代币化及衍生品交易",
                    badgeText = d.universe.optString("metadata_status", "UNVERIFIED"),
                    badgeTone = if (verifiedCount == allSymbols.size && allSymbols.isNotEmpty()) BadgeTone.BULLISH else BadgeTone.WARNING
                ) {
                    RiskGaugeBar(
                        label = "权威证券类型元数据核验进度",
                        valueText = "$verifiedCount / ${allSymbols.size}",
                        progress = verifiedCount.toFloat() / totalCount.toFloat(),
                        tone = if (verifiedCount > 0) BadgeTone.BULLISH else BadgeTone.WARNING
                    )
                    OutlinedTextField(
                        value = universeSearch,
                        onValueChange = onUniverseSearchChange,
                        label = { Text("搜索股票代码 (如 AAPL, NVDA, TSLA)") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                    FilterChipRow(
                        options = listOf(
                            "ALL" to "全部 (${allSymbols.size})",
                            "FOCUS" to "重点订阅 (${focusList.size})",
                            "BUY_SELL" to "可买 (BUY_SELL)",
                            "UNVERIFIED" to "规则待核验"
                        ),
                        selectedKey = universeFilter,
                        onSelect = onUniverseFilterChange
                    )
                }
            }

            val filteredSymbols = allSymbols.filter { sym ->
                val tradability = rulesObj?.optJSONObject(sym)?.optString("tradability") ?: "待核验"
                val matchesFilter = when (universeFilter) {
                    "FOCUS" -> sym in focusList
                    "BUY_SELL" -> tradability in setOf("BUY_SELL", "BUY")
                    "UNVERIFIED" -> tradability == "待核验"
                    else -> true
                }
                val matchesSearch = universeSearch.isBlank() || sym.contains(universeSearch.trim(), ignoreCase = true)
                matchesFilter && matchesSearch
            }

            items(filteredSymbols) { symbol ->
                val p = LocalObrPalette.current
                val rule = rulesObj?.optJSONObject(symbol)
                val tradability = rule?.optString("tradability") ?: "待核验"
                val isFocus = symbol in focusList
                val tone = when (tradability) {
                    "BUY_SELL", "BUY" -> BadgeTone.BULLISH
                    "SELL", "SELL_ONLY" -> BadgeTone.WARNING
                    else -> BadgeTone.NEUTRAL
                }

                Surface(
                    shape = RoundedCornerShape(10.dp),
                    color = p.cardContainer,
                    border = BorderStroke(1.dp, if (isFocus) p.primaryAccent.copy(alpha = 0.45f) else p.borderSubtle),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 14.dp, vertical = 10.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            Text(
                                text = symbol,
                                color = p.textPrimary,
                                fontFamily = FontFamily.Monospace,
                                fontWeight = FontWeight.Bold,
                                fontSize = 15.sp
                            )
                            if (isFocus) {
                                StatusPill("★ 重点订阅", BadgeTone.INFO, showDot = false)
                            }
                        }
                        StatusPill(text = tradability, tone = tone, showDot = true)
                    }
                }
            }
        }
    }
}

// ============================================================================
// 3. DUAL-CHANNEL TRADING HUB (双通道交易: 模拟盘 / 实盘账本 / 沙盒回放)
// ============================================================================

private fun LazyListScope.DualChannelTradingHubContent(
    d: Dashboard,
    demoData: JSONObject?,
    busy: Boolean,
    subTab: String,
    onSubTabChange: (String) -> Unit,
    paperDetailTab: String,
    onPaperDetailTabChange: (String) -> Unit,
    onRequestModeChange: (String) -> Unit,
    onEditPaperBudget: () -> Unit,
    onEditLiveBudget: () -> Unit,
    onRunDemo: () -> Unit
) {
    val modes = d.status.optJSONObject("trading_modes")
    val paperOn = modes?.optBoolean("paper_enabled") == true
    val liveOn = modes?.optBoolean("live_enabled") == true

    item {
        SegmentedControlBar(
            options = listOf(
                "PAPER" to "模拟盘 (${if (paperOn) "开启" else "关闭"})",
                "LIVE" to "实盘账本 (${if (liveOn) "开启" else "关闭"})",
                "REPLAY" to "沙盒回放"
            ),
            selectedKey = subTab,
            onSelect = onSubTabChange
        )
    }

    when (subTab) {
        "PAPER" -> {
            val pos = d.positions
            val cfg = pos.optJSONObject("configuration")
            val enabled = pos.optBoolean("enabled")
            val cash = pos.optString("cash", cfg?.optString("initial_cash", "600") ?: "600")
            val initialCash = cfg?.optString("initial_cash", "600") ?: "600"
            val realizedPnl = pos.optString("realized_pnl", "0.00")
            val dailyHalted = pos.optBoolean("daily_halted")
            val maxPositions = cfg?.optInt("max_positions", 2) ?: 2
            val maxDailyLoss = cfg?.optString("max_daily_loss", "6") ?: "6"
            val openPositions = pos.optJSONArray("positions")?.objects() ?: emptyList()
            val orders = (pos.optJSONArray("orders")?.objects() ?: emptyList()).takeLast(30).reversed()
            val fills = (pos.optJSONArray("fills")?.objects() ?: emptyList()).takeLast(30).reversed()

            item {
                TerminalSectionCard(
                    title = "模拟盘账户与风控状态",
                    subtitle = if (enabled) "模拟账户已建立 · 与实盘共用确认信号，独立资金撮合" else "等待模拟账户核验：${pos.optString("reason")}",
                    badgeText = if (paperOn) "模拟通道开启" else "模拟通道关闭",
                    badgeTone = if (paperOn) BadgeTone.PAPER else BadgeTone.NEUTRAL,
                    actionLabel = "编辑模拟预算",
                    onAction = onEditPaperBudget
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(10.dp)
                    ) {
                        KpiMetricCard(
                            label = "模拟可用现金",
                            value = formatUsd(cash),
                            subtitle = "初始资金 ${formatUsd(initialCash)}",
                            tone = BadgeTone.PAPER,
                            modifier = Modifier.weight(1f)
                        )
                        val pnlVal = realizedPnl.toDoubleOrNull() ?: 0.0
                        KpiMetricCard(
                            label = "当日已实现净盈亏",
                            value = formatUsd(realizedPnl),
                            subtitle = if (dailyHalted) "已触发日亏损熔断" else "熔断阈值 -$${maxDailyLoss}",
                            tone = if (pnlVal >= 0.0) BadgeTone.BULLISH else BadgeTone.BEARISH,
                            modifier = Modifier.weight(1f)
                        )
                    }

                    RiskGaugeBar(
                        label = "同时持仓槽位占用",
                        valueText = "${openPositions.size} / $maxPositions 笔",
                        progress = openPositions.size.toFloat() / maxPositions.coerceAtLeast(1).toFloat(),
                        tone = BadgeTone.PAPER
                    )

                    KeyValueMetricRow("单笔含费上限", formatUsd(cfg?.optString("per_order_budget", "300")))
                    KeyValueMetricRow("最大总敞口上限", formatUsd(cfg?.optString("max_exposure", "600")))
                    KeyValueMetricRow("每日交易标的数上限", "${cfg?.optInt("max_daily_symbols", 5) ?: 5} 个不同标的")

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        Button(
                            onClick = { onRequestModeChange(if (paperOn) "PAPER_OFF" else "PAPER_ON") },
                            enabled = !busy && modes?.optBoolean("control_configured") == true,
                            modifier = Modifier.weight(1f)
                        ) {
                            Text(if (paperOn) "关闭模拟盘新开仓" else "开启模拟盘通道")
                        }
                        OutlinedButton(
                            onClick = onEditPaperBudget,
                            enabled = !busy && modes?.optBoolean("control_configured") == true,
                            modifier = Modifier.weight(1f)
                        ) {
                            Text("调整模拟预算")
                        }
                    }
                }
            }

            // Sub-filter for Positions / Orders / Fills
            item {
                FilterChipRow(
                    options = listOf(
                        "POSITIONS" to "当前持仓 (${openPositions.size})",
                        "ORDERS" to "最近委托 (${orders.size})",
                        "FILLS" to "成交明细 (${fills.size})"
                    ),
                    selectedKey = paperDetailTab,
                    onSelect = onPaperDetailTabChange
                )
            }

            when (paperDetailTab) {
                "POSITIONS" -> {
                    if (openPositions.isEmpty()) {
                        item {
                            TerminalSectionCard(
                                title = "当前空仓 (Flat)",
                                subtitle = "暂无未平仓模拟头寸；修改模拟预算需在空仓且通道关闭状态下进行。"
                            ) {
                                Text("等待盘中满足条件的 ORB 突破确认信号。", color = LocalObrPalette.current.textMuted)
                            }
                        }
                    } else {
                        items(openPositions) { row ->
                            TerminalSectionCard(
                                title = row.optString("symbol"),
                                badgeText = "持仓中",
                                badgeTone = BadgeTone.BULLISH
                            ) {
                                KeyValueMetricRow("持仓股数 (Quantity)", row.optString("quantity"))
                                KeyValueMetricRow("持仓均价/成本 (Cost)", formatUsd(row.optString("cost")))
                            }
                        }
                    }
                }
                "ORDERS" -> {
                    if (orders.isEmpty()) {
                        item {
                            TerminalSectionCard(title = "暂无模拟订单记录") {
                                Text("尚未产生模拟委托单。", color = LocalObrPalette.current.textMuted)
                            }
                        }
                    } else {
                        items(orders) { row ->
                            val side = row.optString("side")
                            val stateStr = row.optString("state")
                            TerminalSectionCard(
                                title = "${row.optString("symbol")} · $side",
                                subtitle = "原因：${row.optString("reason")}",
                                badgeText = stateStr,
                                badgeTone = if (stateStr == "FILLED") BadgeTone.BULLISH else BadgeTone.INFO
                            ) {
                                KeyValueMetricRow("委托数量 / 已成交", "${row.optString("quantity")} / ${row.optString("filled")}")
                                KeyValueMetricRow("委托限价 (Limit)", formatUsd(row.optString("limit")))
                            }
                        }
                    }
                }
                "FILLS" -> {
                    if (fills.isEmpty()) {
                        item {
                            TerminalSectionCard(title = "暂无模拟成交记录") {
                                Text("尚未产生模拟撮合成交。", color = LocalObrPalette.current.textMuted)
                            }
                        }
                    } else {
                        items(fills) { row ->
                            val side = row.optString("side")
                            TerminalSectionCard(
                                title = "${row.optString("symbol")} · $side 成交",
                                badgeText = side,
                                badgeTone = if (side == "BUY") BadgeTone.INFO else BadgeTone.BULLISH
                            ) {
                                KeyValueMetricRow("成交数量", row.optString("quantity"))
                                KeyValueMetricRow("成交价格", formatUsd(row.optString("price")))
                                KeyValueMetricRow("手续费快照", formatUsd(row.optString("fee")))
                            }
                        }
                    }
                }
            }
        }

        "LIVE" -> {
            item {
                WalletFlowArchitectureCard(
                    modes = modes,
                    onEditLiveConfig = onEditLiveBudget,
                    onToggleLive = { onRequestModeChange(if (liveOn) "LIVE_OFF" else "LIVE_ON") }
                )
            }

            item {
                val cfg = modes?.optJSONObject("live_config")?.optJSONObject("configuration")
                    ?: modes?.optJSONObject("live_ledger")?.optJSONObject("configuration")
                TerminalSectionCard(
                    title = "实盘仓位与止盈止损参数",
                    subtitle = liveConfigSummary(modes),
                    badgeText = "自定义配置",
                    badgeTone = BadgeTone.INFO,
                    actionLabel = "修改参数",
                    onAction = onEditLiveBudget
                ) {
                    if (cfg != null) {
                        KeyValueMetricRow("分配资金 (MAIN USDC)", formatUsd(cfg.optString("allocated_usdc", "600")))
                        KeyValueMetricRow("单笔含费上限", formatUsd(cfg.optString("per_order_budget", "300")))
                        KeyValueMetricRow("同时持仓 / 每日标的上限", "${cfg.optInt("max_positions", 2)} 笔 / ${cfg.optInt("max_daily_symbols", 5)} 个")
                        KeyValueMetricRow("总敞口上限 / 日亏损熔断", "${formatUsd(cfg.optString("max_exposure", "600"))} / ${formatUsd(cfg.optString("max_daily_loss", "30"))}")
                        KeyValueMetricRow(
                            "净止盈 / 净止损触发阈值",
                            "+${formatPct(cfg.optString("take_profit_pct", "0.0175"))} / -${formatPct(cfg.optString("stop_loss_pct", "0.0080"))}"
                        )
                    }
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        val liveAvail = modes?.optBoolean("live_available") == true
                        val ctrlOk = modes?.optBoolean("control_configured") == true
                        Button(
                            onClick = { onRequestModeChange(if (liveOn) "LIVE_OFF" else "LIVE_ON") },
                            enabled = !busy && liveAvail && ctrlOk,
                            modifier = Modifier.weight(1f)
                        ) {
                            Text(if (liveOn) "关闭实盘通道" else "开启实盘通道")
                        }
                        OutlinedButton(
                            onClick = onEditLiveBudget,
                            enabled = !busy && ctrlOk,
                            modifier = Modifier.weight(1f)
                        ) {
                            Text("配置实盘参数")
                        }
                    }
                }
            }

            val liveBlockers = modes?.optJSONArray("live_blockers")?.strings() ?: emptyList()
            if (liveBlockers.isNotEmpty()) {
                item {
                    TerminalSectionCard(
                        title = "实盘启用安全门控检查",
                        subtitle = "实盘启动对账、费率与权威证券元数据全部核实前，系统自动拒绝实盘下单",
                        badgeText = "${liveBlockers.size} 项待核实",
                        badgeTone = BadgeTone.WARNING
                    ) {
                        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            liveBlockers.forEach { code ->
                                BlockerDiagnosticCard(diagnoseBlocker(code))
                            }
                        }
                    }
                }
            }
        }

        "REPLAY" -> {
            item {
                TerminalSectionCard(
                    title = "隔离沙盒合成回放 (Deterministic Replay)",
                    subtitle = "在隔离临时数据库中完整演练限价开仓、部分成交、净止盈 (+1.75%)、净止损 (-0.80%) 与日亏损熔断；绝不触碰生产账本",
                    badgeText = "SYNTHETIC_DEMO",
                    badgeTone = BadgeTone.INFO,
                    actionLabel = "重新运行",
                    onAction = onRunDemo
                ) {
                    if (demoData == null) {
                        Button(onClick = onRunDemo, enabled = !busy, modifier = Modifier.fillMaxWidth()) {
                            Text("加载并运行 3 大标准风控场景回放")
                        }
                    }
                }
            }

            val scenarios = demoData?.optJSONArray("scenarios")?.objects() ?: emptyList()
            items(scenarios) { scenario ->
                val scType = scenario.optString("scenario")
                val account = scenario.optJSONObject("account")
                val title = when (scType) {
                    "TAKE_PROFIT" -> "场景 1：ORB 突破后触发净止盈退出 (TAKE_PROFIT)"
                    "STOP_LOSS" -> "场景 2：突破回落触发净止损保护退出 (STOP_LOSS)"
                    else -> "场景 3：连续止损触发当日最大亏损熔断 (DAILY_LOSS_HALT)"
                }
                val tone = when (scType) {
                    "TAKE_PROFIT" -> BadgeTone.BULLISH
                    "STOP_LOSS" -> BadgeTone.WARNING
                    else -> BadgeTone.BEARISH
                }
                TerminalSectionCard(
                    title = title,
                    subtitle = "期末可用现金 ${formatUsd(account?.optString("cash"))} · 已实现盈亏 ${formatUsd(account?.optString("realized_pnl"))}",
                    badgeText = scType,
                    badgeTone = tone
                ) {
                    EnhancedEquityChart(
                        points = scenario.optJSONArray("equity_curve")?.objects() ?: emptyList(),
                        scenarioType = scType
                    )
                    val fills = account?.optJSONArray("fills")?.objects() ?: emptyList()
                    fills.forEach { fill ->
                        KeyValueMetricRow(
                            label = "${fill.optString("side")} ${fill.optString("symbol")} (${fill.optString("reason")})",
                            value = "${fill.optString("quantity")} 股 @ ${formatUsd(fill.optString("price"))} (费 ${formatUsd(fill.optString("fee"))})"
                        )
                    }
                }
            }
        }
    }
}

// ============================================================================
// 4. EVOLUTION & QUANT RESEARCH HUB (进化与投研: 5周期复盘 / 策略版本与回测 / 中文日报)
// ============================================================================

private fun LazyListScope.EvolutionResearchHubContent(
    d: Dashboard,
    evolution: JSONObject?,
    selectedReportDate: String,
    reportContent: String,
    busy: Boolean,
    subTab: String,
    onSubTabChange: (String) -> Unit,
    selectedHorizon: String,
    onSelectHorizon: (String) -> Unit,
    onRefreshEvolution: () -> Unit,
    onTriggerReview: (String) -> Unit,
    onOpenStrategyLab: () -> Unit,
    onPromoteVersion: (String) -> Unit,
    onSelectReportDate: (String) -> Unit
) {
    val versions = evolution?.optJSONArray("strategy_versions")?.objects() ?: emptyList()
    val reports = d.reports.objects()

    item {
        SegmentedControlBar(
            options = listOf(
                "REVIEWS" to "5周期复盘",
                "VERSIONS" to "策略实验室 (${versions.size})",
                "REPORTS" to "中文日报 (${reports.size})"
            ),
            selectedKey = subTab,
            onSelect = onSubTabChange
        )
    }

    when (subTab) {
        "REVIEWS" -> {
            val activeStrategy = evolution?.optJSONObject("active_strategy")
            val activeVerId = activeStrategy?.optString("version_id")
                ?: d.status.optString("active_strategy_version", "closed-bar-momentum-v2")

            item {
                TerminalSectionCard(
                    title = "自我进化与 5 周期自动复盘引擎",
                    subtitle = "闭环：模拟/实盘记录 ➔ 5 周期归因复盘 ➔ 外部 AI (Codex / Antigravity) 参数诊断 ➔ 样本外验证晋升",
                    badgeText = activeVerId,
                    badgeTone = BadgeTone.BULLISH,
                    actionLabel = "刷新诊断",
                    onAction = onRefreshEvolution
                ) {
                    FilterChipRow(
                        options = listOf(
                            "DAILY" to "每日复盘 (1D)",
                            "TRADING_5D" to "每5交易日 (5D)",
                            "MONTHLY" to "月度复盘 (1M)",
                            "QUARTERLY" to "季度复盘 (1Q)",
                            "SEMIANNUAL" to "半年度复盘 (6M)"
                        ),
                        selectedKey = selectedHorizon,
                        onSelect = onSelectHorizon
                    )
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        FilledTonalButton(
                            onClick = { onTriggerReview(selectedHorizon) },
                            enabled = !busy,
                            modifier = Modifier.weight(1f)
                        ) {
                            Text("重新生成当前周期复盘")
                        }
                        OutlinedButton(
                            onClick = onOpenStrategyLab,
                            enabled = !busy,
                            modifier = Modifier.weight(1f)
                        ) {
                            Text("打开候选策略实验室")
                        }
                    }
                }
            }

            val latestByPeriod = evolution?.optJSONObject("latest_reviews_by_period")
            val selectedReview = latestByPeriod?.optJSONObject(selectedHorizon)

            if (selectedReview != null) {
                val pPerf = selectedReview.optJSONObject("paper_performance")
                val lPerf = selectedReview.optJSONObject("live_performance")
                val sigDiag = selectedReview.optJSONObject("signal_diagnostics")
                val suggestions = selectedReview.optJSONArray("optimization_suggestions")?.objects() ?: emptyList()

                item {
                    TerminalSectionCard(
                        title = "${selectedReview.optString("period_label")} · 双通道绩效归因",
                        subtitle = "统计区间：${selectedReview.optString("period_key")}",
                        badgeText = selectedHorizon,
                        badgeTone = BadgeTone.INFO
                    ) {
                        Text(
                            text = evolutionPeriodSummary(selectedReview),
                            color = LocalObrPalette.current.textSecondary,
                            style = MaterialTheme.typography.bodySmall
                        )
                        HorizontalDivider(color = LocalObrPalette.current.borderSubtle.copy(alpha = 0.5f))
                        KeyValueMetricRow(
                            "模拟盘平仓 / 胜率 / 盈亏比",
                            "${pPerf?.optInt("closed_trades_count", 0)} 笔 / ${formatPct(pPerf?.optString("win_rate", "0"))} / ${pPerf?.optString("profit_loss_ratio", "0.00")}"
                        )
                        KeyValueMetricRow(
                            "模拟盘净收益 / 最大回撤",
                            "${formatUsd(pPerf?.optString("net_pnl", "0"))} / ${formatUsd(pPerf?.optString("max_drawdown", "0"))}"
                        )
                        KeyValueMetricRow(
                            "实盘平仓 / 胜率 / 净收益",
                            "${lPerf?.optInt("closed_trades_count", 0)} 笔 / ${formatPct(lPerf?.optString("win_rate", "0"))} / ${formatUsd(lPerf?.optString("net_pnl", "0"))}"
                        )
                        KeyValueMetricRow(
                            "信号质量 (候选 / 假突破 / 错失)",
                            "${sigDiag?.optInt("total_candidates", 0)} / ${sigDiag?.optInt("erroneous_signals_count", 0)} / ${sigDiag?.optInt("missed_opportunities_count", 0)}"
                        )
                    }
                }

                if (suggestions.isNotEmpty()) {
                    item {
                        TerminalSectionCard(
                            title = "AI 参数诊断与优化建议",
                            subtitle = "建议仅供参考，必须先在「策略实验室」通过样本外回测门控方可晋升",
                            badgeText = "${suggestions.size} 条建议",
                            badgeTone = BadgeTone.PAPER,
                            actionLabel = "去实验回测",
                            onAction = onOpenStrategyLab
                        ) {
                            suggestions.forEach { sugg ->
                                val p = LocalObrPalette.current
                                Surface(
                                    shape = RoundedCornerShape(8.dp),
                                    color = p.cardElevated,
                                    modifier = Modifier.fillMaxWidth()
                                ) {
                                    Column(
                                        modifier = Modifier.padding(10.dp),
                                        verticalArrangement = Arrangement.spacedBy(4.dp)
                                    ) {
                                        Text(
                                            text = "目标参数：${sugg.optString("parameter", "综合基线")} (${sugg.optString("action", "HOLD")})",
                                            color = p.primaryAccent,
                                            style = MaterialTheme.typography.labelLarge
                                        )
                                        Text(
                                            text = sugg.optString("rationale"),
                                            color = p.textPrimary,
                                            style = MaterialTheme.typography.bodySmall
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        "VERSIONS" -> {
            val activeObj = evolution?.optJSONObject("active_strategy")
            val activeParams = activeObj?.optJSONObject("parameters")

            item {
                TerminalSectionCard(
                    title = "当前线上稳定策略参数基线",
                    subtitle = "未通过样本外 (Out-of-Sample) 独立验证的候选策略严禁覆盖此稳定版本",
                    badgeText = activeObj?.optString("version_id", "closed-bar-momentum-v2"),
                    badgeTone = BadgeTone.BULLISH,
                    actionLabel = "新建候选提案",
                    onAction = onOpenStrategyLab
                ) {
                    if (activeParams != null) {
                        KeyValueMetricRow("开盘区间观察周期 (lookback)", "${activeParams.optInt("lookback", 3)} 根 5m K线")
                        KeyValueMetricRow("最小相对成交量倍数 (min_rvol)", activeParams.optString("min_rvol", "1.5"))
                        KeyValueMetricRow("最大突破追高幅度 (max_chase)", activeParams.optString("max_chase", "0.015"))
                        KeyValueMetricRow("最大盘口点差阈值 (max_spread)", activeParams.optString("max_spread", "0.0035"))
                        KeyValueMetricRow("趋势整理最大宽度 (max_consolidation)", activeParams.optString("max_consolidation", "0.008"))
                    }
                }
            }

            items(versions) { v ->
                val verId = v.optString("version_id")
                val statusStr = v.optString("status")
                val ev = v.optJSONObject("validation_evidence")
                val passed = ev?.optBoolean("passed_validation") == true
                val oosPnl = ev?.optString("out_of_sample_net_pnl", "0.00") ?: "0.00"
                val isPnl = ev?.optString("in_sample_net_pnl", "0.00") ?: "0.00"

                val tone = when (statusStr) {
                    "ACTIVE" -> BadgeTone.BULLISH
                    "VALIDATED" -> BadgeTone.INFO
                    "REJECTED" -> BadgeTone.BEARISH
                    else -> BadgeTone.WARNING
                }

                TerminalSectionCard(
                    title = verId,
                    subtitle = v.optString("notes").ifBlank { "量化参数版本记录" },
                    badgeText = statusStr,
                    badgeTone = tone,
                    actionLabel = if (passed && statusStr != "ACTIVE") "晋升为稳定版" else null,
                    onAction = if (passed && statusStr != "ACTIVE") {
                        { onPromoteVersion(verId) }
                    } else null
                ) {
                    KeyValueMetricRow("样本外验证门控 (OOS Gate)", if (passed) "✓ 验证通过" else "✕ 未通过 / 待验证")
                    KeyValueMetricRow("样本内净收益 (In-Sample PnL)", formatUsd(isPnl))
                    KeyValueMetricRow("样本外净收益 (Out-of-Sample PnL)", formatUsd(oosPnl))
                }
            }
        }

        "REPORTS" -> {
            item {
                TerminalSectionCard(
                    title = "中文运行日报归档",
                    subtitle = "按纽约美股交易日每天 16:15 自动生成系统与信号审计日报",
                    badgeText = "${reports.size} 份日报",
                    badgeTone = BadgeTone.INFO
                ) {
                    if (reports.isEmpty()) {
                        Text("暂无历史日报记录。", color = LocalObrPalette.current.textMuted)
                    } else {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .horizontalScroll(rememberScrollState()),
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            reports.forEach { row ->
                                val day = row.optString("date")
                                FilterChip(
                                    selected = day == selectedReportDate,
                                    onClick = { onSelectReportDate(day) },
                                    label = { Text(day, fontFamily = FontFamily.Monospace) }
                                )
                            }
                        }
                    }
                }
            }

            if (reportContent.isNotBlank()) {
                item {
                    TerminalSectionCard(
                        title = "日报正文 · ${selectedReportDate.ifBlank { "最新" }}",
                        badgeText = "NYSE / ET",
                        badgeTone = BadgeTone.NEUTRAL
                    ) {
                        Text(
                            text = reportContent,
                            color = LocalObrPalette.current.textPrimary,
                            style = MaterialTheme.typography.bodyMedium,
                            fontFamily = FontFamily.Monospace
                        )
                    }
                }
            }
        }
    }
}

// ============================================================================
// 5. RISK, FEES, ALERTS & SETTINGS HUB (风控与设置)
// ============================================================================

private fun LazyListScope.RiskSettingsHubContent(
    d: Dashboard,
    state: MonitorState,
    subTab: String,
    onSubTabChange: (String) -> Unit,
    notificationDenied: Boolean,
    onRequestModeChange: (String) -> Unit,
    onEditPaperBudget: () -> Unit,
    onEditLiveBudget: () -> Unit,
    onToggleBackground: (Boolean) -> Unit
) {
    val alerts = d.alerts.objects()
    val feeStatus = d.fees.optString("status", "UNVERIFIED")

    item {
        SegmentedControlBar(
            options = listOf(
                "CONTROL" to "通道与安全",
                "FEES" to "官方手续费",
                "ALERTS" to "系统告警 (${alerts.size})"
            ),
            selectedKey = subTab,
            onSelect = onSubTabChange
        )
    }

    when (subTab) {
        "CONTROL" -> {
            val modes = d.status.optJSONObject("trading_modes")

            item {
                val p = LocalObrPalette.current
                TerminalSectionCard(
                    title = "双通道独立开关（共用同一套确认信号）",
                    subtitle = "实盘与模拟盘可同时并行开启；2 个模块共用 1 套 ORB-Math 确认信号，资金账本与持仓完全隔离。",
                    badgeText = if (modes?.optBoolean("control_configured") == true) "操作鉴权已就绪" else "未配置操作令牌",
                    badgeTone = if (modes?.optBoolean("control_configured") == true) BadgeTone.BULLISH else BadgeTone.WARNING
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text("模拟盘通道 (Paper Trading)", color = p.textPrimary, style = MaterialTheme.typography.titleSmall)
                            Text("独立模拟撮合账本，实盘开启时模拟盘照样并行运行", color = p.textMuted, style = MaterialTheme.typography.bodySmall)
                        }
                        Switch(
                            checked = modes?.optBoolean("paper_enabled") == true,
                            enabled = !state.busy && modes?.optBoolean("control_configured") == true,
                            onCheckedChange = { onRequestModeChange(if (it) "PAPER_ON" else "PAPER_OFF") }
                        )
                    }
                    HorizontalDivider(color = p.borderSubtle.copy(alpha = 0.5f))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text("实盘通道 (Live · MAIN/USDC ➔ CARD)", color = p.textPrimary, style = MaterialTheme.typography.titleSmall)
                            Text("真实资金通道，买入用 MAIN 现货 USDC，卖出结算至 CARD", color = p.textMuted, style = MaterialTheme.typography.bodySmall)
                        }
                        Switch(
                            checked = modes?.optBoolean("live_enabled") == true,
                            enabled = !state.busy && modes?.optBoolean("live_available") == true && modes.optBoolean("control_configured"),
                            onCheckedChange = { onRequestModeChange(if (it) "LIVE_ON" else "LIVE_OFF") }
                        )
                    }
                }
            }

            item {
                TerminalSectionCard(
                    title = "实盘与模拟盘预算参数管理",
                    subtitle = "修改参数均需独立操作令牌，且对应账户需处于无持仓、无未完结挂单状态"
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        Button(
                            onClick = onEditLiveBudget,
                            enabled = !state.busy && modes?.optBoolean("control_configured") == true,
                            modifier = Modifier.weight(1f)
                        ) {
                            Text("配置实盘参数")
                        }
                        OutlinedButton(
                            onClick = onEditPaperBudget,
                            enabled = !state.busy && modes?.optBoolean("control_configured") == true,
                            modifier = Modifier.weight(1f)
                        ) {
                            Text("配置模拟预算")
                        }
                    }
                }
            }

            item {
                val p = LocalObrPalette.current
                TerminalSectionCard(
                    title = "Keystore 硬件加密与后台费率核查提醒",
                    subtitle = "开启后使用 Android Keystore 加密保存监控令牌，由 WorkManager 约每 15 分钟检查服务器费率变更记录",
                    badgeText = if (state.background) "已开启" else "未开启",
                    badgeTone = if (state.background) BadgeTone.BULLISH else BadgeTone.NEUTRAL
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        Text(
                            text = "后台手续费变更通知提醒",
                            color = p.textPrimary,
                            style = MaterialTheme.typography.titleSmall
                        )
                        Switch(
                            checked = state.background,
                            onCheckedChange = onToggleBackground
                        )
                    }
                    if (notificationDenied) {
                        Text(
                            text = "系统通知权限尚未授予，后台提醒无法弹出；请在 Android 系统设置中开启通知权限。",
                            color = p.warning,
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                    KeyValueMetricRow("当前连接服务器", state.base)
                }
            }
        }

        "FEES" -> {
            val rules = d.fees.optJSONObject("observation")?.optJSONObject("terms")?.optJSONArray("rules")?.objects() ?: emptyList()
            val statusText = when (feeStatus) {
                "CURRENT_PUBLIC_SCHEDULE" -> "官方公开规则已核查 (有效期内)"
                "STALE" -> "费率核查已超过 26 小时 (STALE)"
                else -> "尚无有效核查记录"
            }
            val tone = when (feeStatus) {
                "CURRENT_PUBLIC_SCHEDULE" -> BadgeTone.BULLISH
                "STALE" -> BadgeTone.WARNING
                else -> BadgeTone.BEARISH
            }

            item {
                TerminalSectionCard(
                    title = "币安官方美股手续费监控",
                    subtitle = "官方核查每天北京时间 09:00 执行；注意公开费用表不等于账户实际适用费率",
                    badgeText = feeStatus,
                    badgeTone = tone
                ) {
                    KeyValueMetricRow("核查状态", statusText, monospace = false)
                    KeyValueMetricRow("官方核查来源", d.fees.optString("source", "https://www.binance.com/en/fee/stocks"))
                    val checkedMs = d.fees.optJSONObject("observation")?.optLong("checked_ms", 0L) ?: 0L
                    KeyValueMetricRow("最近核查时间", formatTimestampMs(checkedMs))
                }
            }

            items(rules) { rule ->
                TerminalSectionCard(
                    title = "费率规则 · ${rule.optString("id", "RULE")}",
                    subtitle = rule.optString("description", "官方公开费率条款"),
                    badgeText = rule.optString("status", "ACTIVE"),
                    badgeTone = BadgeTone.INFO
                ) {
                    val keys = rule.keys()
                    while (keys.hasNext()) {
                        val k = keys.next()
                        if (k !in setOf("id", "description", "status")) {
                            KeyValueMetricRow(k, rule.optString(k))
                        }
                    }
                }
            }
        }

        "ALERTS" -> {
            if (alerts.isEmpty()) {
                item {
                    TerminalSectionCard(
                        title = "系统运行平稳 · 暂无告警",
                        badgeText = "0 告警",
                        badgeTone = BadgeTone.BULLISH
                    ) {
                        Text(
                            text = "当前未触发断流、高延迟、磁盘低空间或对账异常告警。",
                            color = LocalObrPalette.current.textMuted,
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                }
            } else {
                items(alerts) { row ->
                    val code = row.optString("code", "ALERT")
                    val timeMs = row.optLong("time_ms", 0L)
                    val detail = row.optJSONObject("detail")
                    val tone = if (code.contains("FAIL") || code.contains("DISCONNECT")) BadgeTone.BEARISH else BadgeTone.WARNING

                    TerminalSectionCard(
                        title = code,
                        subtitle = "触发时间：${formatTimestampMs(timeMs)}",
                        badgeText = "告警",
                        badgeTone = tone
                    ) {
                        if (detail != null && detail.length() > 0) {
                            val keys = detail.keys()
                            while (keys.hasNext()) {
                                val k = keys.next()
                                KeyValueMetricRow(k, detail.optString(k))
                            }
                        } else {
                            Text("无附加诊断字段", color = LocalObrPalette.current.textMuted, style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
            }
        }
    }
}
