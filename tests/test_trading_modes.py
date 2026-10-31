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
