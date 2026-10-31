from datetime import date, timedelta
from decimal import Decimal as D
from app.features import Momentum, VolumeHistory, SessionVolumes
from app.calendar import Session
from app.market import Bar


def test_high_frequency_prices_preserve_five_minutes_and_reject_future():
    m=Momentum()
    for now in range(0,310001,100):
        m.add(now,D(100)+D(now)/100000,now)
    assert len(m.samples)<=312
    assert all(v is not None for v in m.at(310000).values())
    assert not m.add(320000,200,310000)
    assert not m.add(300000,200,310000)
    assert all(v is None for v in m.at(330000).values())
    m.add(340000,200,340000)
    assert all(v is None for v in m.at(340000).values())


def bar(session, index):
    start=session.open_ms+index*300000
    return Bar("TEST",start,start+299999,D(100),D(101),D(99),D(100),D(10),True)


def test_history_requires_complete_prefix_and_excludes_same_or_future_days():
    h=VolumeHistory();v=SessionVolumes(h)
    day=date(2026,10,30)
    session=Session.from_verified_hours(day,source="SYNTHETIC")
    assert v.observe(bar(session,0),session)
    assert v.observe(bar(session,1),session)
    assert h.before("TEST",day,600000)==[]
    assert h.before("TEST",day+timedelta(days=1),600000)==[(day,600000,D(20))]
    assert not v.observe(bar(session,3),session)
    assert not v.observe(bar(session,4),session)
    assert h.before("TEST",day+timedelta(days=1),1500000)==[]


def test_gap_and_midday_start_cannot_build_valid_history():
    h=VolumeHistory();v=SessionVolumes(h)
    session=Session.from_verified_hours(date(2026,10,30),source="SYNTHETIC")
    assert not v.observe(bar(session,1),session)
    assert not v.observe(bar(session,2),session)
    assert not h.values
    v=SessionVolumes(h)
    assert not v.observe(bar(session,0),session,continuous=False)
    assert not v.observe(bar(session,1),session)


def test_history_retains_only_twenty_days():
    h=VolumeHistory()
    day=date(2026,9,1)
    for n in range(30):h.add("TEST",day+timedelta(days=n),300000,n)
    assert len(h.values["TEST"])==20


def test_runtime_restores_only_continuous_volume_prefixes(tmp_path):
    import asyncio
    from app.runtime import Runtime
    from tests.test_runtime import settings, kline
    async def scenario():
        config=settings(tmp_path)
        runtime=Runtime(config)
        worker=asyncio.create_task(runtime.writer.run())
        session=runtime.calendar.sessions[date(2026,10,30)]
        for index in range(2):
            start=session.open_ms+index*300000
            runtime.process(kline(start,"100","101"),start+300000)
        await runtime.writer.stop(worker)
        runtime.store.close()
        restored=Runtime(config)
        try:
            assert restored.volume_history.before("TEST",date(2026,10,31),600000)==[(session.day,600000,D(200))]
        finally:
            restored.store.close()
    asyncio.run(scenario())
