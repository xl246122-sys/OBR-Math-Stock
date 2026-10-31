from dataclasses import replace
from datetime import date, time, timedelta
from decimal import Decimal as D

import pytest

from app.calendar import Calendar, Session
from app.market import Bar, Quote, QuoteGate, number
from app.strategy import OBRMathEngine, Parameters
from app.universe import import_csv, prioritize


DAY = date(2026, 10, 30)
SESSION = Session.from_verified_hours(DAY, source="SYNTHETIC_TEST")


def bar(index, close="100", high="100", low="99", volume="100"):
    start = SESSION.open_ms + index*300000
    return Bar("TEST", start, start+299999, D(low), D(high), D(low), D(close), D(volume), True)


def history(progress=600000, volume="100"):
    return [(DAY-timedelta(days=i), progress, D(volume)) for i in range(1, 11)]


def orb(**kwargs):
    engine = OBRMathEngine("TEST", SESSION)
    engine.on_bar(bar(0), SESSION.open_ms+300000)
    b = bar(1, "100.2", "100.3")
    return engine, engine.on_bar(b, b.end_ms+1, **kwargs)[0]


def test_orb_positive_and_dedup():
    engine, decision = orb(historical_volumes=history(), volume_verified=True, tradable=True, spread=D(".001"))
    assert decision.state == "CONFIRMED" and decision.rvol == 2
    b = bar(2, "100.3", "100.4")
    assert engine.on_bar(b, b.end_ms+1) == []


@pytest.mark.parametrize("kwargs,reason", [
    ({}, "DATA_INSUFFICIENT"),
    ({"volume_verified": True}, "COLD_START"),
    ({"volume_verified": True, "historical_volumes": history(volume="1000")}, "LOW_RVOL"),
    ({"volume_verified": True, "historical_volumes": history(progress=300000)}, "COLD_START"),
    ({"volume_verified": True, "historical_volumes": history(), "spread": D(".01")}, "WIDE_SPREAD"),
    ({"volume_verified": True, "historical_volumes": history(), "spread": D(".001")}, "TRADABILITY_UNVERIFIED"),
])
def test_orb_gates(kwargs, reason):
    assert orb(**kwargs)[1].reason == reason


def test_future_or_same_day_history_excluded():
    samples = [(DAY+timedelta(days=i), 600000, D(100)) for i in range(10)]
    assert orb(volume_verified=True, historical_volumes=samples)[1].reason == "COLD_START"


def test_duplicate_history_cannot_fake_warmup():
    assert orb(volume_verified=True, historical_volumes=[history()[0]]*10)[1].reason == "COLD_START"


def test_incomplete_and_future_bars_not_used():
    engine = OBRMathEngine("TEST", SESSION)
    b = bar(0)
    assert engine.on_bar(replace(b, closed=False), b.end_ms+1) == []
    assert engine.on_bar(b, b.end_ms-1) == []
    assert engine.orb is None
    engine.on_bar(b, b.end_ms+1)
    jump = bar(2, "100.2", "100.3")
    decision = engine.on_bar(jump, jump.end_ms+1)[0]
    assert decision.reason == "INCOMPLETE_SESSION"
    assert engine.on_bar(bar(1), jump.end_ms+1) == []


def test_stale_signal():
    engine = OBRMathEngine("TEST", SESSION)
    engine.on_bar(bar(0), bar(0).end_ms+1)
    b = bar(1, "100.2", "100.3")
    assert engine.on_bar(b, b.end_ms+3000)[0].reason == "DATA_STALE"


def test_continuation_excludes_current_high():
    engine = OBRMathEngine("TEST", SESSION)
    for idx, close in enumerate(["99", "99.8", "99.9", "100"]):
        b = bar(idx, close, "100", "99")
        engine.on_bar(b, b.end_ms+1)
    b = bar(4, "100.2", "101", "100")
    decisions = engine.on_bar(b, b.end_ms+1, history(1500000), volume_verified=True, tradable=True, spread=D(".001"))
    continuation = next(d for d in decisions if d.kind == "INTRADAY_CONTINUATION")
    assert continuation.level == 100 and continuation.state == "CONFIRMED"


def test_quote_source_time_and_reordering():
    message = {"e": "quote", "s": "TEST", "bp": "100", "ap": "100.1", "bs": 2, "as": 3, "T": 10000, "E": 10100}
    q = Quote.parse(message, 10150)
    gate = QuoteGate(["TEST"])
    assert gate.check(q) == "ACCEPTED"
    assert gate.check(q) == "DUPLICATE"
    assert gate.check(replace(q, source_ms=9999)) == "OUT_OF_ORDER"
    assert gate.check(replace(q, source_ms=None)) == "UNKNOWN_SOURCE_LATENCY"
    assert gate.check(replace(q, received_ms=15000)) == "DATA_STALE"
    assert gate.check(replace(q, push_ms=20000)) == "CLOCK_ANOMALY"
    with pytest.raises(ValueError, match="CROSSED_BOOK"):
        Quote.parse({**message, "bp": "102"}, 10150)


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-1", "hello"])
def test_invalid_numbers(bad):
    with pytest.raises(ValueError):
        number(bad)


def test_calendar_dst_early_close_and_unknown():
    before = Session.from_verified_hours(date(2026, 3, 6), source="SYNTHETIC_TEST")
    after = Session.from_verified_hours(date(2026, 3, 9), source="SYNTHETIC_TEST")
    assert after.open_ms-before.open_ms == (72-1)*3600000
    early = Session.from_verified_hours(date(2026, 11, 27), time(13), "SYNTHETIC_TEST")
    assert not early.can_enter(early.close_ms-20*60000)
    assert early.should_exit(early.close_ms-5*60000)
    cal = Calendar([early], [date(2026, 12, 25)])
    assert cal.status(date(2026, 12, 25)) == "MARKET_CLOSED"
    assert cal.status(DAY) == "CALENDAR_UNKNOWN"


def test_csv_version_errors_and_verified_selection():
    result = import_csv("symbol\nBA\n ba \n???\nNBIS\n")
    assert result.symbols == ("BA", "NBIS") and len(result.errors) == 2
    assert result.version == import_csv("symbol\nBA\n ba \n???\nNBIS\n").version
    assert prioritize(result.symbols, {"BA": "BUY_SELL"}, {"NBIS": 100}) == ("BA",)
    with pytest.raises(ValueError):
        prioritize([], {}, {}, 301)
