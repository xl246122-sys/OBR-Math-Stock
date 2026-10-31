"""Deterministic isolated educational replay; never touches production account data."""
from datetime import date,timedelta
from decimal import Decimal as D
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
import json
from app.calendar import Session
from app.market import Bar,Quote
from app.strategy import OBRMathEngine,Parameters
from app.execution import Fees
from app.paper_config import PaperConfig
from app.paper_runtime import PaperRuntime
from app.storage import AuditStore


@lru_cache(maxsize=1)
def demonstration():
    session=Session.from_verified_hours(date(2026,10,30),source='SYNTHETIC_DEMO')
    now=session.open_ms+600000
    rule={'tickSize':'.01','stepSize':'.01','minNotional':'5','maxNotional':'1000000','maxQty':'1000000'}
    results=[]
    for scenario,exit_price in [('TAKE_PROFIT','103'),('STOP_LOSS','99'),('DAILY_LOSS_LIMIT','96')]:
        with TemporaryDirectory(prefix='obr-isolated-replay-') as directory:
            store=AuditStore(Path(directory)/'demo.db')
            try:
                p=PaperRuntime(store,PaperConfig())
                engine=OBRMathEngine('DEMO',session,Parameters(require_momentum=True))
                def bar(index,close,high):
                    start=session.open_ms+index*300000
                    return Bar('DEMO',start,start+299999,D('99'),D(high),D('99'),D(close),D(100),True)
                engine.on_bar(bar(0,'100','100'),session.open_ms+300000)
                signal=engine.on_bar(bar(1,'100.2','100.3'),now,
                    historical_volumes=[(session.day-timedelta(days=d),600000,D(100)) for d in range(1,11)],
                    volume_verified=True,tradable=True,spread=D(0),momentum={1:D('.01'),3:D('.01'),5:D('.01')})[0]
                assert signal.state=='CONFIRMED'
                points=[]
                for index,price in enumerate(('100.2','100.2',exit_price,exit_price)):
                    t=now+index;value=D(price)
                    q=Quote('DEMO',value,value,D(10),D(10),t,t,t)
                    p.step({'now_ms':t,'session':session,'quotes':{'DEMO':q},'rules':{'DEMO':rule},
                        'fees':Fees(D('.001'),D('.001'),D('.1')),'fee_version':'SYNTHETIC_ASSUMPTION_NOT_OFFICIAL',
                        'buy_symbols':{'DEMO'},'sell_symbols':{'DEMO'},'max_exposure':D(600),'healthy':True,
                        'signals':[asdict(signal)] if index==0 else []})
                    b=p.account.broker
                    equity=b.cash+sum(o.reserved for o in b.orders.values() if o.side=='BUY')+sum(pos.quantity*value for pos in b.positions.values())
                    points.append({'time_ms':t,'equity':str(equity)})
                results.append({'scenario':scenario,'signal':asdict(signal),'equity_curve':points,'account':p.cached})
            finally:store.close()
    return json.loads(json.dumps({'provenance':'SYNTHETIC_DEMO','production_account_modified':False,
        'description':'固定合成行情与假设手续费，仅演示程序流程；不是市场收益或官方费用。',
        'scenarios':results},default=str))
