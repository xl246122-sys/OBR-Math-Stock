"""Offline pipeline load: JSON parsing, real Runtime, bounded audit queue and SQLite.
No external network; synthetic instruments are never written to production DB.
"""
import asyncio,json,sys,time,tracemalloc,platform
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.calendar import Session
from app.config import Settings
from app.runtime import Runtime

class OfflineFeed:
    def __init__(self,streams):
        self.connected=True;self.data_gap=False;self.queue=asyncio.Queue(maxsize=1000)
        self.dropped=0;self.reconnects=0;self.last_received_ms=None

def stats(values):
    values=sorted(values)
    return {f'p{p}_ms':values[min(len(values)-1,int((len(values)-1)*p/100))]/1e6 for p in (50,95,99)}

async def run(count):
    with TemporaryDirectory(prefix='obr-load-') as folder:
        root=Path(folder);session=Session.from_verified_hours(date(2026,10,30),source='SYNTHETIC_LOAD')
        symbols=[f'TEST{i}' for i in range(count)]
        (root/'universe.json').write_text(json.dumps({'version':'SYNTHETIC','symbols':symbols,'rules':{s:{'tradability':'BUY_SELL'} for s in symbols}}))
        (root/'calendar.json').write_text(json.dumps({'source':'SYNTHETIC','closed_days':[],'sessions':[{'day':str(session.day),'open_ms':session.open_ms,'close_ms':session.close_ms}]}))
        tracemalloc.start();r=Runtime(Settings('x'*32,True,root/'db',root/'universe.json',root/'calendar.json',focus_limit=count),feed_factory=OfflineFeed)
        worker=asyncio.create_task(r.writer.run());processing=[];audit_latency=[];batch=[];started=time.perf_counter_ns()
        try:
            for index in range(12):
                start=session.open_ms+index*300000
                for symbol in symbols:
                    payload={'e':'kline','s':symbol,'k':{'s':symbol,'i':'5m','t':start,'ct':start+299999,
                        'o':'100','h':str(100+index*.01+.01),'l':'99.99','c':str(100+index*.01),'v':'100','x':True}}
                    raw=json.dumps(payload);before=time.perf_counter_ns()
                    r.process(json.loads(raw),start+300000)
                    processing.append(time.perf_counter_ns()-before);batch.append(before)
                    if len(batch)>=64:
                        await r.writer.queue.join();end=time.perf_counter_ns();audit_latency.extend(end-t for t in batch);batch=[]
            await r.writer.queue.join();end=time.perf_counter_ns();audit_latency.extend(end-t for t in batch)
            peak=tracemalloc.get_traced_memory()[1]
            return {'symbols':count,'events':len(processing),'processing':stats(processing),'to_audit_batch_completion':stats(audit_latency),
                'tracemalloc_peak_bytes':peak,'elapsed_ms':(end-started)/1e6,'audit_failure':r.writer.failure,
                'stored_bars':r.store.day_counts(session.open_ms,session.close_ms)['bars']}
        finally:
            await r.writer.stop(worker);r.store.close();tracemalloc.stop()

async def main():
    result={'provenance':'SYNTHETIC_OFFLINE_PIPELINE','platform':platform.platform(),'python':sys.version,
        'excludes':['real WS network','live market load','real order routing'],'runs':[]}
    for count in (10,50,100,200,300):result['runs'].append(await run(count))
    output=Path(sys.argv[1] if len(sys.argv)>1 else 'docs/evidence/v05-pipeline-load.json')
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result['runs']))
if __name__=='__main__':asyncio.run(main())
