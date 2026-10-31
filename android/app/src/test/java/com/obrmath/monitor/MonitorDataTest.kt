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
}
