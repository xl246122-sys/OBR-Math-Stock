from dataclasses import replace
from datetime import date
from decimal import Decimal as D
import pytest
from app.calendar import Session
from app.execution import Fees, PaperBroker, entry_limit, floor_step, net_return, exit_reason
from app.market import Quote

SESSION = Session.from_verified_hours(date(2026,10,30), source="SYNTHETIC_TEST")
NOW = SESSION.open_ms+600000
FEES = Fees(D(".001"), D(".001"), D(".1"))


def broker():
    return PaperBroker(D(10000), D(2000), FEES, SESSION)


def quote(ms=NOW+1, size=2):
    return Quote("TEST", D("99.9"), D(100), D(10), D(size), ms, ms, ms)


def test_partial_fill_cannot_reuse_liquidity_and_cash_reconciles():
    b = broker()
    order = b.submit("id", "TEST", D(101), D(5), NOW)
    first = b.on_quote(quote(), NOW+1)
    assert first[0]["provenance"] == "SIMULATED"
    assert order.filled == 2 and order.state == "PARTIALLY_FILLED"
    assert not b.on_quote(quote(), NOW+1)
    b.on_quote(quote(NOW+2, 3), NOW+2)
    assert order.state == "FILLED" and order.fees == D(".5")
    assert b.cash == D("9499.5")


def test_cancel_partial_and_idempotency_conflict():
    b = broker()
    order = b.submit("id", "TEST", D(101), D(5), NOW)
    assert b.submit("id", "TEST", D(101), D(5), NOW) is order
    with pytest.raises(ValueError, match="IDEMPOTENCY_CONFLICT"):
        b.submit("id", "TEST", D(101), D(6), NOW)
    b.on_quote(quote(), NOW+1)
    b.cancel("id")
    assert b.cash == D("9799.8") and order.filled == 2
    assert b.on_quote(quote(NOW+2), NOW+2) == []


def test_unknown_cancel_retains_reserve_and_blocks_reentry():
    b = broker()
    order = b.submit("id", "TEST", D(101), D(5), NOW)
    cash = b.cash
    b.cancel("id", confirmed=False)
    b.expire(NOW+3000)
    assert order.state == "UNKNOWN_ORDER_STATE" and cash == b.cash
    with pytest.raises(ValueError, match="REENTRY_LIMIT"):
        b.submit("new", "TEST", D(101), D(5), NOW)


def test_expiry_stale_and_unmarketable_quotes():
    b = broker()
    order = b.submit("id", "TEST", D(99), D(5), NOW)
    assert b.on_quote(quote(), NOW+1) == []
    b.expire(NOW+2000)
    assert order.state == "EXPIRED" and b.cash == 10000


def test_max_five_and_health_budget_gates():
    b = broker()
    b.max_positions = 5
    for i in range(5):
        b.submit(str(i), f"TEST{i}", D(100), D(1), NOW)
    with pytest.raises(ValueError, match="DAILY_LIMIT"):
        b.submit("six", "SIX", D(100), D(1), NOW)
    with pytest.raises(ValueError, match="ENTRY_DISABLED"):
        broker().submit("x", "TEST", D(100), D(1), NOW, healthy=False)
    with pytest.raises(ValueError, match="BUDGET_EXCEEDED"):
        broker().submit("x", "TEST", D(100), D(20), NOW)


def test_rounding_and_chase_cap():
    assert floor_step(D("1.234"), D(".01")) == D("1.23")
    assert entry_limit(D(100), D("100.1"), D(".005"), D(".01")) == D("100.50")
    with pytest.raises(ValueError, match="CHASE_LIMIT"):
        entry_limit(D(100), D("100.51"), D(".005"), D(".01"))


def test_net_fees_and_independent_exit_policy():
    net = net_return(D(10), D(100), D(1), D(102), FEES)
    assert net == (D(1020)-D("1.02")-D(1001))/D(1001)
    assert exit_reason(net, NOW, SESSION) == "TAKE_PROFIT"
    assert exit_reason(D("-.008"), NOW, SESSION) == "STOP_LOSS"
    assert exit_reason(D(0), SESSION.close_ms-300000, SESSION) == "SESSION_EXIT"
