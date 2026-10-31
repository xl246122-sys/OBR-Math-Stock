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
}
