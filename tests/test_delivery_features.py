import asyncio
from dataclasses import replace
import pytest
from app.paper_config import PaperConfig
from app.runtime import Runtime
from app.demo import demonstration
from tests.test_runtime import settings
from tests.test_paper_loop import enter


def test_demo_is_isolated_deterministic_and_covers_exit_paths():
    result=demonstration()
    assert result['provenance']=='SYNTHETIC_DEMO' and not result['production_account_modified']
    for scenario in result['scenarios']:
        account=scenario['account']
        assert not account['positions']
        assert len(account['fills'])==2
        assert account['fills'][-1]['reason']==scenario['scenario']
    assert demonstration()==result


def test_budget_save_requires_off_persists_and_does_not_reset_cash(tmp_path):
    async def run():
        conf=settings(tmp_path);r=Runtime(conf)
        updated=PaperConfig(initial_cash='1000',per_order_budget='200',max_positions=2)
        with pytest.raises(ValueError,match='TURN_MODE_OFF'):await r.change_paper_config(updated,0)
        await r.change_mode('OFF',0)
        await r.change_paper_config(updated,0)
        with pytest.raises(ValueError,match='REVISION'):await r.change_paper_config(updated,0)
        r.store.close();r=Runtime(conf)
        assert r.paper_config.initial_cash==1000 and r.config_revision==1
        r.store.close()
    asyncio.run(run())


def test_budget_change_rejects_open_account_and_save_failure(tmp_path,monkeypatch):
    async def run():
        r=Runtime(settings(tmp_path));enter(r.paper)
        await r.change_mode('OFF',0)
        with pytest.raises(ValueError,match='FLAT'):await r.change_paper_config(PaperConfig(per_order_budget=200),0)
        r.store.close()
    asyncio.run(run())


def test_empty_account_config_failure_does_not_change_in_memory_values(tmp_path,monkeypatch):
    async def run():
        r=Runtime(settings(tmp_path));await r.change_mode('OFF',0)
        def fail(*args):raise OSError('SYNTHETIC_DISK_FAILURE')
        monkeypatch.setattr(r.store,'save_paper_configuration',fail)
        with pytest.raises(OSError):await r.change_paper_config(PaperConfig(per_order_budget=200),0)
        assert r.paper_config.per_order_budget==300 and r.config_revision==0
        r.store.close()
    asyncio.run(run())
