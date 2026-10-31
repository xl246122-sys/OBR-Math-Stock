import asyncio
from dataclasses import asdict
from datetime import date, datetime, time
import json
from pathlib import Path
import urllib.request

from app.calendar import Session
from app.config import Settings
from app.runtime import Runtime
from app.monitoring import daily_report
from app.universe import import_csv


def settings(tmp_path):
    session = Session.from_verified_hours(date(2026,10,30), source="SYNTHETIC")
    universe = tmp_path/"universe.json"
    universe.write_text(json.dumps({"version": "synthetic", "symbols": ["TEST"],
                                   "rules": {"TEST": {"tradability": "BUY_SELL"}}}))
    calendar = tmp_path/"calendar.json"
    calendar.write_text(json.dumps({"source": "SYNTHETIC", "sessions": [{"day": str(session.day),
                                   "open_ms": session.open_ms, "close_ms": session.close_ms}],
                                   "closed_days": ["2026-10-31"]}))
    return Settings("x"*32, True, tmp_path/"state", universe, calendar)


def kline(start, close, high):
    return {"e": "kline", "s": "TEST", "k": {"s": "TEST", "i": "5m", "t": start, "ct": start+299999,
            "o": "99", "h": high, "l": "99", "c": close, "v": "100", "x": True}}


def test_real_chinese_csv_column():
    result = import_csv("代码,说明\nBA,候选\nBA,重复\nNBIS,候选\n")
    assert result.symbols == ("BA", "NBIS") and len(result.errors) == 1


def test_live_observation_pipeline_persists_watch_signal_and_bar(tmp_path):
    async def scenario():
        runtime = Runtime(settings(tmp_path))
        worker = asyncio.create_task(runtime.writer.run())
        session = runtime.calendar.sessions[date(2026,10,30)]
        runtime.process(kline(session.open_ms, "100", "100"), session.open_ms+300000)
        runtime.process(kline(session.open_ms+300000, "100.2", "100.3"), session.open_ms+600000)
        await runtime.writer.stop(worker)
        saved = runtime.store.recent("signals")
        assert saved[0]["state"] == "WATCH_ONLY"
        assert saved[0]["provenance"] == "LIVE_OBSERVATION"
        assert saved[0]["reason"] == "DATA_INSUFFICIENT"
        assert runtime.store.day_counts(session.open_ms, session.close_ms)["bars"] == 2
        runtime.store.close()
    asyncio.run(scenario())


def test_report_idempotent_on_closed_day_and_restorable(tmp_path):
    runtime = Runtime(settings(tmp_path))
    metrics = runtime.metrics.snapshot(runtime.settings.data_dir)
    day = date(2026,10,31)
    first = daily_report(runtime.store, tmp_path/"reports", day, runtime.calendar, runtime.status(), metrics, 10)
    second = daily_report(runtime.store, tmp_path/"reports", day, runtime.calendar, runtime.status(), metrics, 20)
    assert first == second and "MARKET_CLOSED" in first
    assert len(runtime.store.recent("reports")) == 1
    assert runtime.store.recent("reports")[0]["generated_ms"] == 10
    runtime.store.close()


def test_credentials_not_exposed_in_settings_repr(tmp_path):
    conf = Settings("TOKENSECRET", binance_api_key="EXCHANGESECRET")
    assert "TOKENSECRET" not in repr(conf) and "EXCHANGESECRET" not in repr(conf)


def test_only_authenticated_http_call_is_fixed_readonly_get(monkeypatch):
    from app.exchange import exchange_info
    calls = []
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{"symbols":[]}'
    class Opener:
        def open(self, request, timeout):
            calls.append((request.full_url, request.method))
            assert request.get_header("X-mbx-apikey") == "TEST_SECRET"
            return Response()
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a: Opener())
    result = exchange_info("TEST_SECRET")
    assert result["http_status"] == 200
    assert calls == [("https://api.binance.com/sapi/v1/equity/market/exchangeInfo", "GET")]
    assert "TEST_SECRET" not in repr(result)
