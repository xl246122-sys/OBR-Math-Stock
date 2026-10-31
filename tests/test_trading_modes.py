import asyncio
from dataclasses import replace
import pytest
from fastapi.testclient import TestClient
from app.api import create_app
from app.runtime import Runtime
from app.storage import AuditStore
from app.trading_modes import TradingModes, ModeConflict
from tests.test_runtime import settings
from tests.test_paper_loop import enter, context, quote, NOW


def test_modes_are_exclusive_persistent_and_live_never_claimed_ready(tmp_path):
    store=AuditStore(tmp_path/'modes.db');m=TradingModes(store)
    assert m.snapshot()['paper_enabled'] and not m.snapshot()['live_enabled']
    m.change('OFF',0)
    assert not m.snapshot()['paper_enabled'] and not m.snapshot()['live_enabled']
    with pytest.raises(ModeConflict,match='REVISION'):m.change('PAPER',0)
    with pytest.raises(ModeConflict,match='LIVE_EXECUTION'):m.change('LIVE',1)
    assert m.state['mode']=='OFF'
    m=TradingModes(store);assert m.state['mode']=='OFF'
    m.change('PAPER',1)
    assert len(store.recent('alerts'))==2
    store.close()


def test_mode_storage_failure_keeps_previous_state(tmp_path,monkeypatch):
    store=AuditStore(tmp_path/'modes.db');m=TradingModes(store)
    def fail(*args):raise OSError('synthetic')
    monkeypatch.setattr(store,'save_trading_mode',fail)
    with pytest.raises(OSError):m.change('OFF',0)
    assert m.state=={'mode':'PAPER','revision':0}
    store.close()


def test_off_cancels_pending_entry_but_still_exits_position(tmp_path):
    async def run():
        r=Runtime(settings(tmp_path));enter(r.paper)
        await r.change_mode('OFF',0)
        await r.paper_tick(context(NOW+2,quotes={'TEST':quote(NOW+2,'102')}))
        await r.paper_tick(context(NOW+3,quotes={'TEST':quote(NOW+3,'102')}))
        assert r.paper.account.broker.positions['TEST'].quantity==0
        assert r.trading_modes.state['mode']=='OFF'
        assert 'PAPER_MODE_OFF' in r.status()['blockers']
        r.store.close()
    asyncio.run(run())


def test_write_requires_separate_control_token_and_current_revision(tmp_path):
    conf=replace(settings(tmp_path),control_token='c'*32)
    app=create_app(conf);r=Runtime(conf);app.state.runtime=r
    client=TestClient(app);monitor={'Authorization':'Bearer '+conf.api_token}
    request={'mode':'OFF','revision':0}
    assert client.post('/api/v1/trading-mode',json=request).status_code==401
    assert client.post('/api/v1/trading-mode',headers=monitor,json=request).status_code==403
    headers={**monitor,'X-OBR-Control-Token':'c'*32}
    response=client.post('/api/v1/trading-mode',headers=headers,json=request)
    assert response.status_code==200 and response.json()['mode']=='OFF'
    assert client.post('/api/v1/trading-mode',headers=headers,json={'mode':'PAPER','revision':0}).status_code==409
    assert client.post('/api/v1/trading-mode',headers=headers,json={'mode':'LIVE','revision':1}).status_code==409
    assert client.post('/api/v1/trading-mode',headers=headers,json={'mode':'PAPER','revision':True}).status_code==422
    assert client.get('/api/v1/trading-mode',headers=monitor).json()['mode']=='OFF'
    r.store.close()


def test_control_token_must_be_configured_and_different(tmp_path):
    conf=settings(tmp_path);conf=replace(conf,control_token=conf.api_token)
    app=create_app(conf);r=Runtime(conf);app.state.runtime=r
    client=TestClient(app)
    assert client.post('/api/v1/trading-mode',headers={'Authorization':'Bearer '+conf.api_token,'X-OBR-Control-Token':conf.api_token},json={'mode':'OFF','revision':0}).status_code==503
    assert not r.mode_status()['control_configured']
    r.store.close()

def test_off_releases_unfilled_simulation_reservation(tmp_path):
    from tests.test_paper_loop import signal
    async def run():
        r=Runtime(settings(tmp_path))
        r.paper.step(context(signals=[signal()]))
        assert r.paper.account.broker.cash<600
        await r.change_mode('OFF',0)
        await r.paper_tick(context(NOW+1))
        assert r.paper.account.broker.orders['candidate'].state=='CANCELED'
        assert not r.paper.account.broker.fills
        assert r.paper.account.broker.cash==600
        r.store.close()
    asyncio.run(run())


def test_parallel_paper_and_live_switches_share_signal_and_save_live_config(tmp_path):
    from datetime import timedelta
    from decimal import Decimal as D
    from tests.test_runtime import kline
    from tests.test_paper_loop import DAY, SESSION, RULE, FEES
    conf = replace(settings(tmp_path), control_token='c'*32, live_control_enabled=True)
    app = create_app(conf)
    r = Runtime(conf)
    app.state.runtime = r
    client = TestClient(app)
    monitor = {'Authorization': 'Bearer ' + conf.api_token}
    headers = {**monitor, 'X-OBR-Control-Token': 'c'*32}

    # Initially PAPER is enabled, LIVE is off, and live_available is True
    mode_resp = client.get('/api/v1/trading-mode', headers=monitor).json()
    assert mode_resp['mode'] == 'PAPER'
    assert mode_resp['paper_enabled'] is True
    assert mode_resp['live_enabled'] is False
    assert mode_resp['live_available'] is True
    assert mode_resp['shared_signal'] is True

    # Configure Live position parameters while Live is OFF (Paper still running!)
    live_cfg_payload = {
        'allocated_usdc': '800',
        'per_order_budget': '160',
        'max_positions': 4,
        'max_daily_loss': '40',
        'max_exposure': '640',
        'max_daily_symbols': 4,
        'take_profit_pct': '0.025',
        'stop_loss_pct': '0.012',
        'revision': 0,
    }
    cfg_resp = client.post('/api/v1/live-config', headers=headers, json=live_cfg_payload)
    assert cfg_resp.status_code == 200
    saved_cfg = cfg_resp.json()
    assert saved_cfg['revision'] == 1
    assert saved_cfg['configuration']['allocated_usdc'] == '800'
    assert saved_cfg['configuration']['per_order_budget'] == '160'
    assert saved_cfg['configuration']['max_positions'] == 4
    assert saved_cfg['configuration']['take_profit_pct'] == '0.025'
    assert saved_cfg['configuration']['stop_loss_pct'] == '0.012'

    # Toggle LIVE_ON -> transitions mode to BOTH (Paper still running + Live running)
    both_resp = client.post('/api/v1/trading-mode', headers=headers, json={'mode': 'LIVE_ON', 'revision': mode_resp['revision']})
    assert both_resp.status_code == 200
    both_data = both_resp.json()
    assert both_data['mode'] == 'BOTH'
    assert both_data['paper_enabled'] is True
    assert both_data['live_enabled'] is True

    # Editing live-config while live_enabled is True is allowed when live account is flat, and rejects stale revision
    assert client.post('/api/v1/live-config', headers=headers, json={**live_cfg_payload, 'revision': 0}).status_code == 409
    cfg_resp2 = client.post('/api/v1/live-config', headers=headers, json={**live_cfg_payload, 'per_order_budget': '200', 'revision': 1})
    assert cfg_resp2.status_code == 200
    assert cfg_resp2.json()['configuration']['per_order_budget'] == '200'

    # Feed 1 confirmed breakout signal -> verify BOTH paper and live receive the same signal
    r.rules_verified = True
    r.rules = {"TEST": {**RULE, "tradability": "BUY_SELL"}}
    r.paper_verified = {"fees": FEES, "volume_symbols": {"TEST"}, "blockers": [], "ticks": {"TEST": D(".01")}}
    for n in range(1, 11):
        r.volume_history.add("TEST", DAY - timedelta(days=n), 600000, 100)
    for offset in range(299000, 600000, 1000):
        t = SESSION.open_ms + offset
        r.momentum["TEST"].add(t, D(99) + D(offset - 299000) / 250000, t)
    r.process(kline(SESSION.open_ms, "100", "100"), SESSION.open_ms + 300000)
    r.process({"e": "quote", "s": "TEST", "bp": "100.2", "ap": "100.2", "bs": "10", "as": "10", "T": NOW, "E": NOW}, NOW)
    r.process(kline(SESSION.open_ms + 300000, "100.2", "100.3"), NOW)

    assert len(r.paper.pending) == 1 and r.paper.pending[0]["state"] == "CONFIRMED"
    assert len(r.live.pending) == 1 and r.live.pending[0]["state"] == "CONFIRMED"
    assert r.paper.pending[0]["candidate_id"] == r.live.pending[0]["candidate_id"]
    assert len(r.live.received_signals) == 1
    r.store.close()
