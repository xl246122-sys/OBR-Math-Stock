from dataclasses import replace
from datetime import date
from decimal import Decimal as D
import json
import pytest
from app.calendar import Session
from app.execution import PaperBroker, Fees
from app.market import Quote
from app.paper_account import PaperAccount
from app.storage import AuditStore

SESSION=Session.from_verified_hours(date(2026,10,30),source="SYNTHETIC")
NOW=SESSION.open_ms+600000


def broker():
    return PaperBroker(D(10000),D(2000),Fees(D(".001"),D(".001"),D(".1")),SESSION)


def quote(price="100",ms=NOW+1,size=10):
    return Quote("TEST",D(price),D(price),D(size),D(size),ms,ms,ms)


def bought():
    b=broker()
    b.submit("buy","TEST",D(100),D(10),NOW)
    b.on_quote(quote(),NOW+1)
    return b


def test_automatic_exit_and_net_pnl_after_fees():
    b=bought()
    q=quote("102",NOW+2)
    orders=b.protect_positions({"TEST":q},NOW+2)
    assert orders[0].reason=="TAKE_PROFIT"
    fills=b.on_quote(q,NOW+2)
    assert fills[0]["side"]=="SELL"
    assert b.positions["TEST"].quantity==0
    assert b.cash==D("10017.98") and b.realized_pnl==D("17.98")


def test_partial_exit_reserves_remaining_position_and_prevents_short():
    b=bought()
    q=quote("98",NOW+2,4)
    b.protect_positions({"TEST":q},NOW+2)
    b.on_quote(q,NOW+2)
    assert b.positions["TEST"].quantity==6
    assert b.positions["TEST"].reserved_quantity==6
    with pytest.raises(ValueError,match="INSUFFICIENT_POSITION"):
        b.submit_exit("duplicate","TEST",D(98),D(1),NOW+3,"STOP_LOSS")
    assert b.protect_positions({"TEST":quote("97",NOW+3)},NOW+3)==[]


def test_stale_exit_alert_and_bounded_retries():
    b=bought()
    b.protect_positions({},NOW+3000)
    assert "POSITION_WITHOUT_FRESH_QUOTE:TEST" in b.risk_alerts
    for attempt in range(4):
        now=NOW+4000+attempt*3000
        b.protect_positions({"TEST":quote("98",now)},now)
    assert b.exit_attempts["TEST"]==3
    assert "UNFILLED_EXIT_RISK:TEST" in b.risk_alerts


def test_unknown_sell_cancel_does_not_release_shares():
    b=bought()
    order=b.submit_exit("sell","TEST",D(99),D(10),NOW+2,"STOP_LOSS")
    b.cancel("sell",confirmed=False)
    b.expire(NOW+10000)
    assert order.state=="UNKNOWN_ORDER_STATE"
    assert b.positions["TEST"].reserved_quantity==10


def test_exit_can_use_available_bid_when_ask_depth_is_empty():
    b=bought()
    q=replace(quote("98",NOW+2),ask_size=D(0))
    b.protect_positions({"TEST":q},NOW+2)
    fills=b.on_quote(q,NOW+2)
    assert fills[0]["side"]=="SELL" and b.positions["TEST"].quantity==0


def test_transactional_restart_does_not_refill_same_quote(tmp_path):
    store=AuditStore(tmp_path/"paper.db")
    account=PaperAccount(store,broker())
    account.execute("submit","buy","TEST",D(100),D(10),NOW)
    account.execute("on_quote",quote(size=4),NOW+1)
    store.close()
    store=AuditStore(tmp_path/"paper.db")
    resumed=PaperAccount(store)
    assert resumed.broker.positions["TEST"].quantity==4
    assert resumed.execute("on_quote",quote(size=4),NOW+1)==[]
    resumed.execute("on_quote",quote(ms=NOW+2,size=6),NOW+2)
    assert resumed.broker.positions["TEST"].quantity==10
    store.close()


def test_storage_failure_rolls_back_and_latches(tmp_path,monkeypatch):
    store=AuditStore(tmp_path/"paper.db")
    account=PaperAccount(store,broker())
    def fail(state): raise OSError("synthetic full disk")
    monkeypatch.setattr(store,"save_paper_state",fail)
    with pytest.raises(RuntimeError,match="PAPER_STORAGE_FAILED"):
        account.execute("submit","buy","TEST",D(100),D(10),NOW)
    assert account.broker.cash==10000 and not account.broker.orders
    with pytest.raises(RuntimeError):
        account.execute("expire",NOW+10000)
    store.close()
