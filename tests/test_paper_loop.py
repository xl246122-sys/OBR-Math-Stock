from dataclasses import replace
from datetime import date,timedelta
from decimal import Decimal as D
import json
import pytest
from app.calendar import Session
from app.execution import Fees
from app.market import Quote
from app.paper_runtime import PaperRuntime,readiness
from app.paper_config import PaperConfig
from app.storage import AuditStore
from app.trading_state import TradingState

DAY=date(2026,10,30)
SESSION=Session.from_verified_hours(DAY,source="SYNTHETIC")
NOW=SESSION.open_ms+600000
FEES=Fees(D(".001"),D(".001"),D(".1"))
RULE={"tickSize":".01","stepSize":".01","minNotional":"5","maxNotional":"1000000","maxQty":"1000000"}

def quote(now,price="100",size="10",symbol="TEST"):
    return Quote(symbol,D(price),D(price),D(size),D(size),now,now,now)

def signal(now=NOW,symbol="TEST",identity="candidate"):
    return {"candidate_id":identity,"symbol":symbol,"state":"CONFIRMED","source_ms":now,"level":"100"}

def context(now=NOW,**changes):
    c={"now_ms":now,"session":SESSION,"quotes":{"TEST":quote(now)},"rules":{"TEST":RULE},"fees":FEES,
       "fee_version":"SYNTHETIC_FEE_V1","buy_symbols":{"TEST"},"sell_symbols":{"TEST"},"max_exposure":D(600),
       "healthy":True,"signals":[]}
    c.update(changes);return c

def runtime(tmp_path):return PaperRuntime(AuditStore(tmp_path/"paper.db"),PaperConfig())

def enter(p):
    p.step(context(signals=[signal()]))
    p.step(context(NOW+1))
    return p.account.broker

def test_complete_entry_fill_take_profit_and_restart(tmp_path):
    p=runtime(tmp_path)
    p.step(context(signals=[signal()]))
    assert not p.account.broker.fills  # no use of a pre-order quote
    p.step(context(NOW+1))
    assert p.account.broker.positions["TEST"].quantity>0
    p.step(context(NOW+2,quotes={"TEST":quote(NOW+2,"102")}))
    assert any(o.reason=="TAKE_PROFIT" for o in p.account.broker.orders.values())
    p.step(context(NOW+3,quotes={"TEST":quote(NOW+3,"102")}))
    assert p.account.broker.positions["TEST"].quantity==0
    assert p.account.broker.cash>D(600)
    cash=p.account.broker.cash
    p.store.close()
    restored=runtime(tmp_path)
    restored.step(context(NOW+3,quotes={"TEST":quote(NOW+3,"102")},signals=[signal()]))
    assert restored.account.broker.cash==cash
    assert len(restored.account.broker.fills)==2
    restored.store.close()

def test_bad_entry_health_cancels_unfilled_buys_and_protects_filled_positions(tmp_path):
    p=runtime(tmp_path);p.step(context(signals=[signal()]))
    p.step(context(NOW+1,quotes={"TEST":quote(NOW+1,size="1")}))
    p.step(context(NOW+2,healthy=False,fees=None,quotes={"TEST":quote(NOW+2,"98")}))
    b=p.account.broker
    assert b.orders["candidate"].state=="CANCELED"
    assert any(o.side=="SELL" for o in b.orders.values())
    p.step(context(NOW+3,healthy=False,fees=None,quotes={"TEST":quote(NOW+3,"98")}))
    assert p.account.broker.positions["TEST"].quantity==0
    assert len([f for f in p.account.broker.fills if f["side"]=="BUY"])==1
    p.store.close()

def test_daily_unrealized_loss_latches_and_survives_restart(tmp_path):
    p=runtime(tmp_path);enter(p)
    p.step(context(NOW+2,quotes={"TEST":quote(NOW+2,"97")}))
    assert p.account.broker.daily_halted
    assert any(o.reason=="DAILY_LOSS_LIMIT" for o in p.account.broker.orders.values())
    p.store.close();p=runtime(tmp_path)
    assert p.account.broker.daily_halted
    p.step(context(NOW+3,quotes={"TEST":quote(NOW+3,"99")}))
    assert p.account.broker.daily_halted
    p.store.close()

def test_position_limit_budget_and_total_exposure(tmp_path):
    p=runtime(tmp_path)
    symbols={"A","B","C"}
    c=context(quotes={s:quote(NOW,symbol=s) for s in symbols},rules={s:RULE for s in symbols},buy_symbols=symbols,sell_symbols=symbols,
              signals=[signal(symbol=s,identity=s) for s in sorted(symbols)])
    p.step(c)
    assert len(p.account.broker.orders)==2
    assert all(o.reserved<=300 for o in p.account.broker.orders.values())
    assert sum(o.reserved for o in p.account.broker.orders.values())<=600
    assert any(e["kind"]=="ENTRY_REJECTED" for e in p.last_events)
    p.store.close()

def test_halt_prevents_fills_and_resume_allows_exit(tmp_path):
    p=runtime(tmp_path);enter(p)
    p.step(context(NOW+2,buy_symbols=set(),sell_symbols=set(),quotes={"TEST":quote(NOW+2,"98")}))
    assert len(p.account.broker.fills)==1
    assert "POSITION_TRADING_HALTED:TEST" in p.account.broker.risk_alerts
    p.step(context(NOW+3,buy_symbols=set(),sell_symbols={"TEST"},quotes={"TEST":quote(NOW+3,"98")}))
    p.step(context(NOW+4,buy_symbols=set(),sell_symbols={"TEST"},quotes={"TEST":quote(NOW+4,"98")}))
    assert p.account.broker.positions["TEST"].quantity==0
    p.store.close()

def test_stale_signal_and_missing_tick_are_rejected(tmp_path):
    p=runtime(tmp_path)
    p.step(context(NOW+3000,signals=[signal()]))
    assert p.last_events[-1]["reason"]=="SIGNAL_STALE"
    rule=dict(RULE);rule.pop("tickSize")
    p.step(context(NOW+3001,signals=[signal(NOW+3001)],rules={"TEST":rule}))
    assert p.last_events[-1]["reason"]=="TRADING_RULE_INCOMPLETE"
    assert not p.account.broker.orders
    p.store.close()

def test_partial_order_uses_original_fee_snapshot(tmp_path):
    p=runtime(tmp_path);p.step(context(signals=[signal()]))
    p.step(context(NOW+1,quotes={"TEST":quote(NOW+1,size="1")}))
    p.step(context(NOW+2,fees=Fees(D(".002"),D(".002"),D(".1")),fee_version="NEW"))
    o=p.account.broker.orders["candidate"]
    assert o.fees==o.notional*D(".001")
    assert o.fee_version=="SYNTHETIC_FEE_V1"
    p.store.close()

def test_expiry_without_quotes_and_end_of_day_exit(tmp_path):
    p=runtime(tmp_path);p.step(context(signals=[signal()]))
    p.step(context(NOW+3000,quotes={}))
    assert p.account.broker.orders["candidate"].state=="EXPIRED"
    assert p.account.broker.cash==600
    p.store.close()
    p=PaperRuntime(AuditStore(tmp_path/"other.db"),PaperConfig());enter(p)
    end=SESSION.close_ms-300000
    p.step(context(end,quotes={"TEST":quote(end)}))
    assert any(o.reason=="SESSION_EXIT" for o in p.account.broker.orders.values())
    p.step(context(end+1,quotes={"TEST":quote(end+1)}))
    assert p.account.broker.positions["TEST"].quantity==0
    nxt=Session.from_verified_hours(DAY+timedelta(days=3),source="SYNTHETIC")
    p.step(context(nxt.open_ms,session=nxt,quotes={}))
    assert p.account.broker.session.day==nxt.day
    assert not p.account.broker.symbols
    p.store.close()

def test_transaction_failure_rolls_back_complete_cycle_and_latches(tmp_path,monkeypatch):
    p=runtime(tmp_path);p.step(context())
    original=p.account.broker.cash
    def fail(*a):raise OSError("SYNTHETIC_DISK_FAILURE")
    monkeypatch.setattr(p.store,"save_paper_state",fail)
    with pytest.raises(RuntimeError):p.step(context(signals=[signal()]))
    assert p.failure=="PAPER_STORAGE_FAILED"
    assert p.account.broker.cash==original and not p.account.broker.orders
    p.store.close()

def test_missing_verification_never_creates_account(tmp_path):
    p=runtime(tmp_path);p.step(context(fees=None,signals=[signal()]))
    assert p.account is None and p.store.load_paper_state() is None
    assert readiness(tmp_path,NOW)["fees"] is None
    p.store.close()

def test_status_effective_time_and_protected_state():
    state=TradingState(["TEST"]);rules={"TEST":{"tradability":"BUY_SELL"}}
    state.receive({"e":"tradingStatus","symbol":"TEST","time":NOW,"status":"TRADING_HALTED","tradability":"NONE"},NOW)
    state.receive({"e":"tradingStatus","symbol":"TEST","time":NOW+1000,"status":"TRADING_RESUMED","tradability":"BUY_SELL"},NOW)
    assert state.direction("TEST",rules,NOW)=="NONE"
    assert state.direction("TEST",rules,NOW+1000)=="BUY_SELL"
    state.receive({"e":"tradability","symbol":"TEST","t":NOW+1001,"tradability":"DELISTING"},NOW+1001)
    state.receive({"e":"tradingStatus","symbol":"TEST","time":NOW+1002,"status":"TRADING_RESUMED","tradability":"BUY_SELL"},NOW+1002)
    assert state.direction("TEST",rules,NOW+1002)=="DELISTING"

def test_verified_fee_expiry_and_effective_rule_change_fail_closed(tmp_path):
    from app.fee_watch import update,SOURCE
    observation={"source":SOURCE,"product":"DIRECT_US_EQUITIES","checked_ms":NOW,
                 "terms":{"rules":[{"id":"promo","expires_ms":NOW+1000}]}}
    observed,_=update(tmp_path/"fee-watch.json",observation,NOW)
    evidence={"schema":1,"checked_ms":NOW,"expires_ms":NOW+2000,"evidence_reference":"SYNTHETIC_ONLY",
              "fee_fingerprint":observed["fingerprint"],"active_rule_ids":["promo"],
              "account_fee_model":{"source":SOURCE,"model":"PROPORTIONAL_WITH_MINIMUM","account_scope":"SYNTHETIC",
                                   "buy_rate":".001","sell_rate":".001","minimum":".1"},
              "volume_verified_symbols":["TEST"],"verified_price_ticks":{"TEST":".01"}}
    path=tmp_path/"paper-verification.json";path.write_text(json.dumps(evidence))
    assert readiness(tmp_path,NOW)["fees"]==FEES
    assert readiness(tmp_path,NOW+1000)["fees"] is None
    assert readiness(tmp_path,NOW+2000)["fees"] is None
    evidence["fee_fingerprint"]="CHANGED";path.write_text(json.dumps(evidence))
    assert readiness(tmp_path,NOW)["fees"] is None


def test_stale_position_blocks_entries_and_unknown_orders_remain_reserved(tmp_path):
    p=runtime(tmp_path);enter(p)
    p.step(context(NOW+5000,quotes={},signals=[signal(NOW+5000,symbol="OTHER",identity="two")]))
    assert "POSITION_WITHOUT_FRESH_QUOTE:TEST" in p.account.broker.risk_alerts
    assert len(p.account.broker.orders)==1
    p.store.close()
    p=PaperRuntime(AuditStore(tmp_path/"unknown.db"),PaperConfig())
    p.step(context(signals=[signal()]))
    p.account.execute("cancel","candidate",confirmed=False)
    cash=p.account.broker.cash
    p.step(context(NOW+1,signals=[signal(NOW+1,identity="two")]))
    assert p.account.broker.cash==cash
    assert p.account.broker.orders["candidate"].state=="UNKNOWN_ORDER_STATE"
    assert len(p.account.broker.orders)==1
    p.store.close()


def test_runtime_closed_bar_to_signal_to_paper_roundtrip(tmp_path):
    import asyncio
    from tests.test_runtime import settings,kline
    from app.runtime import Runtime
    async def run():
        r=Runtime(settings(tmp_path));worker=asyncio.create_task(r.writer.run())
        r.rules_verified=True;r.rules={"TEST":{**RULE,"tradability":"BUY_SELL"}}
        r.paper_verified={"fees":FEES,"volume_symbols":{"TEST"},"blockers":[],"ticks":{"TEST":D(".01")}}
        for n in range(1,11):r.volume_history.add("TEST",DAY-timedelta(days=n),600000,100)
        for offset in range(299000,600000,1000):
            t=SESSION.open_ms+offset;r.momentum["TEST"].add(t,D(99)+D(offset-299000)/250000,t)
        r.process(kline(SESSION.open_ms,"100","100"),SESSION.open_ms+300000)
        r.process({"e":"quote","s":"TEST","bp":"100.2","ap":"100.2","bs":"10","as":"10","T":NOW,"E":NOW},NOW)
        r.process(kline(SESSION.open_ms+300000,"100.2","100.3"),NOW)
        assert len(r.paper.pending)==1 and r.paper.pending[0]["state"]=="CONFIRMED"
        await r.paper.tick(context(quotes=dict(r.quotes)))
        await r.paper.tick(context(NOW+1,quotes={"TEST":quote(NOW+1,"100.2")}))
        assert len(r.paper.account.broker.fills)==1
        await r.paper.tick(context(NOW+2,quotes={"TEST":quote(NOW+2,"103")}))
        await r.paper.tick(context(NOW+3,quotes={"TEST":quote(NOW+3,"103")}))
        assert r.paper.account.broker.positions["TEST"].quantity==0
        assert r.paper.account.broker.cash>600
        await r.writer.stop(worker)
        assert r.store.recent("signals")[0]["state"]=="CONFIRMED"
        r.store.close()
    asyncio.run(run())


def test_restart_pins_held_symbol_even_if_no_longer_buyable(tmp_path):
    from tests.test_runtime import settings
    from app.runtime import Runtime
    config=settings(tmp_path)
    p=PaperRuntime(AuditStore(config.data_dir/"obr.db"),PaperConfig());enter(p);p.store.close()
    data=json.loads(config.universe_file.read_text());data["rules"]["TEST"]["tradability"]="SELL"
    config.universe_file.write_text(json.dumps(data))
    r=Runtime(config)
    assert r.focus==("TEST",)
    assert len(r.feeds)==3
    assert r.paper.account.broker.positions["TEST"].quantity>0
    assert "MARKET_DISCONNECTED" in r.status()["blockers"]
    r.store.close()


def test_score_and_visible_liquidity_bound_order_size(tmp_path):
    p=runtime(tmp_path)
    p.step(context(signals=[{**signal(),"score":"50"}],quotes={"TEST":quote(NOW,size=".5")}))
    order=p.account.broker.orders["candidate"]
    assert order.quantity==D(".5") and order.reserved<=150
    p.store.close()

def test_changed_account_limits_block_new_entries_but_keep_risk_worker(tmp_path):
    p=runtime(tmp_path);enter(p);p.store.close()
    p=PaperRuntime(AuditStore(tmp_path/"paper.db"),PaperConfig(per_order_budget="200"))
    assert p.failure=="PAPER_CONFIG_MISMATCH"
    import asyncio
    asyncio.run(p.tick(context(NOW+2,quotes={"TEST":quote(NOW+2,"102")})))
    asyncio.run(p.tick(context(NOW+3,quotes={"TEST":quote(NOW+3,"102")})))
    assert p.account.broker.positions["TEST"].quantity==0
    assert p.cached["effective_risk"]["per_order_budget"]=="300"
    p.store.close()
