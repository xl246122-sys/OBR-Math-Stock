package com.obrmath.monitor

import org.junit.Assert.*
import org.junit.Test
import org.json.JSONObject

class MonitorDataTest {
    @Test fun defaultServerIsValidHttps() {
        assertEquals("https://43.163.203.127",validatedBase(DEFAULT_SERVER))
    }
    @Test fun serviceAddressRejectsCredentialLeaksAndInsecureSchemes() {
        listOf("http://example.com", "https://user:secret@example.com", "https://example.com?token=secret",
            "https://example.com/#token", "https://example.com/api", "https:///missing", "https://example.com:0").forEach { url ->
            try { validatedBase(url);fail("Must reject: $url") } catch (_: IllegalArgumentException) { }
        }
        assertEquals("https://example.com:8443",validatedBase(" https://example.com:8443/ "))
    }
    @Test fun tokenCannotInjectHeaders() {
        try { MonitorApi("https://example.com", "test\r\nInjected: value");fail("Header injection accepted") }
        catch (_: IllegalArgumentException) { }
    }
    @Test fun missingAndNullChangesDoNotTriggerNotifications() {
        assertNull(feeChangeId(JSONObject()))
        assertNull(feeChangeId(JSONObject("{\"change\":null}")))
        assertNull(feeChangeId(JSONObject("{\"change\":{\"id\":\"\"}}")))
    }
    @Test fun changeSummaryPreservesBothVersionsAndSource() {
        val fees=JSONObject("""{"source":"https://www.binance.com/en/fee/stocks","change":{"id":"change-1","kind":"TERMS_CHANGED","before":{"rate":"0.001"},"after":{"rate":"0.0005"}}}""")
        assertEquals("change-1",feeChangeId(fees))
        assertTrue(feeSummary(fees).contains("0.001"))
        assertTrue(feeSummary(fees).contains("0.0005"))
        assertTrue(feeSummary(fees).contains("https://www.binance.com/en/fee/stocks"))
    }
    @Test fun feedHealthSummaryFormatsRoleAndGapTruthfully() {
        val status = JSONObject("""{"feeds":[{"role":"price","connected":true,"data_gap":false,"reconnects":0,"dropped":0},{"role":"focus_status","connected":false,"data_gap":true,"reconnects":2,"dropped":1}]}""")
        val summary = feedHealthSummary(status)
        assertTrue(summary.contains("price：已连接 · 连续正常"))
        assertTrue(summary.contains("focus_status：重连中 · 缺口锁定(待连续性恢复)"))
    }
    @Test fun liveLedgerSummaryReflectsMainUsdcAndCardSettlementIsolation() {
        val modes = JSONObject("""{"live_ledger":{"account_namespace":"LIVE_EQUITY_MAIN_USDC_CARD","reconciled":false,"main_usdc_free":"399.83","main_usdc_reserved":"200.17","card_settlement_usdc":"203.83","external_positions":{"AAPL":"5"}}}""")
        val summary = liveLedgerSummary(modes)
        assertTrue(summary.contains("LIVE_EQUITY_MAIN_USDC_CARD"))
        assertTrue(summary.contains("未完成对账（禁止实盘开仓）"))
        assertTrue(summary.contains("CARD 卖出结算累计：$203.83（不自动划转回现货）"))
        assertTrue(summary.contains("手工既有仓位隔离数：1 个标的"))
    }
    @Test fun liveConfigAndSharedSignalSummaryFormatCorrectly() {
        val modes = JSONObject("""{"paper_enabled":true,"live_enabled":true,"live_config":{"revision":1,"configuration":{"allocated_usdc":"800","per_order_budget":"160","max_positions":4,"max_daily_loss":"40","max_exposure":"640","max_daily_symbols":4,"take_profit_pct":"0.025","stop_loss_pct":"0.012","buy_wallet":"MAIN","quote_asset":"USDC","sell_settlement_wallet":"CARD"}},"live_ledger":{"received_signals_count":3}}""")
        val cfgSummary = liveConfigSummary(modes)
        assertTrue(cfgSummary.contains("实盘配置资金：$800 USDC · 单笔上限 $160"))
        assertTrue(cfgSummary.contains("同时持仓上限：4 笔"))
        assertTrue(cfgSummary.contains("止盈比例：0.025 · 止损比例：0.012"))
        val sigSummary = sharedSignalSummary(modes)
        assertTrue(sigSummary.contains("模拟盘通道：运行中 · 实盘通道：运行中"))
        assertTrue(sigSummary.contains("2 个模块共用 1 套 ORB-Math 确认信号"))
        assertTrue(sigSummary.contains("实盘通道累计接收共享信号：3 次"))
    }
    @Test fun evolutionPeriodSummaryFormatsMetricsAndSuggestions() {
        val rev = JSONObject("""{"period_label":"每日复盘","period_key":"2026-10-30","paper_performance":{"closed_trades_count":2,"win_rate":"0.5000","profit_loss_ratio":"2.10","net_pnl":"6.60","max_drawdown":"2.20"},"live_performance":{"closed_trades_count":0,"win_rate":"0.0000","profit_loss_ratio":"0.00","net_pnl":"0.00"},"signal_diagnostics":{"total_candidates":3,"erroneous_signals_count":1,"missed_opportunities_count":2},"optimization_suggestions":[{"rationale":"建议在样本外回测中验证下调 min_rvol"}]}""")
        val summary = evolutionPeriodSummary(rev)
        assertTrue(summary.contains("每日复盘 (2026-10-30)"))
        assertTrue(summary.contains("胜率 0.5000 · 盈亏比 2.10"))
        assertTrue(summary.contains("错失机会 2"))
        assertTrue(summary.contains("建议在样本外回测中验证下调 min_rvol"))
    }
    @Test fun blockerAndSignalDiagnosticsTranslateIntoFinancialChinese() {
        val feeDiag = diagnoseBlocker("FEES_NOT_VERIFIED")
        assertEquals("WARNING", feeDiag.severity)
        assertTrue(feeDiag.title.contains("手续费"))
        val gapDiag = diagnoseBlocker("MARKET_DATA_GAP")
        assertEquals("CRITICAL", gapDiag.severity)
        assertTrue(translateSignalReason("ORB_BREAKOUT_CONFIRMED").contains("开盘区间突破确认"))
        assertTrue(translateSignalReason("RVOL_BELOW_THRESHOLD").contains("RVOL"))
        assertEquals("美股盘中交易 (RTH Open)", translateMarketPhase("RTH_OPEN"))
        assertEquals("1.75%", formatPct("0.0175"))
        assertEquals("$600.00", formatUsd("600"))
        assertEquals("-$12.50", formatUsd("-12.5"))
    }
}
