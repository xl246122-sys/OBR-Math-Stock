"""Serialized paper worker and fail-closed, expiring verification evidence."""
import asyncio
from dataclasses import asdict
from decimal import Decimal
import json
from app.execution import Fees, PaperBroker
from app.paper_account import PaperAccount
from app.market import number
from app.fee_watch import view as fee_view, SOURCE


def readiness(directory, now):
    result={"fees":None,"fee_version":None,"volume_symbols":set(),"ticks":{},"blockers":["PAPER_VERIFICATION_REQUIRED"]}
    try:
        data=json.loads((directory/"paper-verification.json").read_text(encoding="utf-8"))
        if data.get("schema")!=1 or not 0<=now-data["checked_ms"]<=26*3600000 or not now<data["expires_ms"]<=data["checked_ms"]+26*3600000:
            return result
        if not data.get("evidence_reference"):return result
        observed=fee_view(directory/"fee-watch.json",now)
        model=data["account_fee_model"]
        if observed["status"]!="CURRENT_PUBLIC_SCHEDULE" or data["fee_fingerprint"]!=observed["fingerprint"] or model.get("source")!=SOURCE:
            return result
        if sorted(data["active_rule_ids"]) != observed["active_rules_now"]:
            return result
        if model.get("model")!="PROPORTIONAL_WITH_MINIMUM" or not model.get("account_scope"):
            return result
        # Tiered/rounded/quantity-dependent fees require a separate supported model;
        # do not coerce them into this simpler model.
        fees=Fees(**{k:number(model[k]) for k in ("buy_rate","sell_rate","minimum")})
        if not isinstance(data["volume_verified_symbols"],list) or not all(isinstance(s,str) for s in data["volume_verified_symbols"]):
            return result
        volume=set(data["volume_verified_symbols"])
        ticks={s:number(v,positive=True) for s,v in data["verified_price_ticks"].items()}
        result.update(fees=fees,fee_version=observed["fingerprint"]+":"+str(data["checked_ms"]),volume_symbols=volume,ticks=ticks,blockers=[])
    except (OSError,ValueError,KeyError,TypeError):pass
    return result


class PaperRuntime:
    def __init__(self,store,config):
        self.store=store;self.config=config;self.account=None
        self.pending=[];self.failure=None;self.last_events=[];self.verified=None
        self.cached={"enabled":False,"reason":"PAPER_VERIFICATION_REQUIRED","positions":[],"configuration":config.public(),"pipeline_connected":True}
        if store.load_paper_state() is not None:
            self.account=PaperAccount(store)
            broker=self.account.broker
            if (broker.per_order_budget,broker.max_positions,broker.max_daily_loss,broker.max_symbols)!=(config.per_order_budget,config.max_positions,config.max_daily_loss,config.max_daily_symbols):
                self.failure="PAPER_CONFIG_MISMATCH"
            self.publish()

    def submit(self,decision):
        if len(self.pending)>=100:
            self.failure="PAPER_SIGNAL_QUEUE_FULL"
            return False
        self.pending.append(asdict(decision))
        return True

    def publish(self):
        if self.account is None:return
        state=json.loads(json.dumps(self.account.broker.snapshot(),default=str))
        self.cached={"enabled":True,"pipeline_connected":True,"reason":self.failure,
                     "configuration":self.config.public(),"cash":state["cash"],
                     "positions":[p for p in state["positions"] if Decimal(p["quantity"])>0],
                     "orders":state["orders"],"fills":state["fills"],"events":state["events"],
                     "realized_pnl":state["realized_pnl"],"daily_halted":state["daily_halted"],
                     "effective_risk":{"per_order_budget":state["per_order_budget"],"max_positions":state["max_positions"],
                         "max_daily_loss":state["max_daily_loss"],"max_daily_symbols":state["max_symbols"],"max_exposure":str(self.config.max_exposure)},
                     "alerts":state["risk_alerts"],"session":state["session"],"fee_version":state["fee_version"]}

    def step(self,context):
        if self.failure=="PAPER_STORAGE_FAILED":return
        try:
            if self.account is None:
                if context.get("fees") is None or context.get("session") is None:
                    return
                self.account=PaperAccount(self.store,PaperBroker(self.config.initial_cash,self.config.per_order_budget,
                    context["fees"],context["session"],max_positions=self.config.max_positions,
                    max_daily_loss=self.config.max_daily_loss,max_symbols=self.config.max_daily_symbols))
            self.last_events=self.account.execute("cycle",context)
            self.publish()
        except Exception:
            self.failure="PAPER_STORAGE_FAILED" if self.account is None or self.account.failure else "PAPER_CYCLE_FAILED"
            self.cached={**self.cached,"reason":self.failure}
            raise

    async def tick(self,context):
        signals,self.pending=self.pending,[]
        context={**context,"signals":signals,"healthy":context["healthy"] and self.failure is None}
        worker=asyncio.create_task(asyncio.to_thread(self.step,context))
        try:await asyncio.shield(worker)
        except asyncio.CancelledError:
            await worker  # storage must finish before Runtime closes the shared DB
            raise
        except Exception:pass  # latched status, never kill the independent risk task
