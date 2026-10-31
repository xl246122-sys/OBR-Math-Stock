"""One atomic paper lifecycle step. No network access or live-order client."""
from decimal import Decimal as D
from app.execution import floor_step, entry_limit
from app.market import number

ACTIVE={"ACKNOWLEDGED","PARTIALLY_FILLED"}
TERMINAL={"FILLED","CANCELED","EXPIRED"}

def fresh(q, now):
    return q is not None and q.source_ms is not None and 0<=now-q.source_ms<=2000 and q.push_ms<=now+250 and q.bid>0 and q.ask>=q.bid

def cycle(b, c):
    now=c["now_ms"];quotes=c["quotes"];session=c.get("session")
    events=[]
    def event(kind, **fields): events.append({"time_ms":now,"kind":kind,"provenance":"SIMULATED",**fields})
    def cancel_buys(reason):
        for order in b.orders.values():
            if order.side=="BUY" and order.state in ACTIVE:
                b.cancel(order.client_id);event("CANCELED",client_id=order.client_id,reason=reason)
    before={key:o.state for key,o in b.orders.items()}
    b.expire(now)
    for key,o in b.orders.items():
        if o.state=="EXPIRED" and before[key]!=o.state:event("EXPIRED",client_id=key)
    if session and session.day>b.session.day:
        cancel_buys("DAY_ROLLOVER")
        if b.rollover(session):event("DAY_ROLLOVER",day=str(session.day))
    day_ok=session is not None and session.day==b.session.day
    if c.get("fees") is not None:
        b.fees=c["fees"];b.fee_version=c["fee_version"]
    fee_ok=c.get("fees") is not None
    buy=set(c.get("buy_symbols",()));sell=set(c.get("sell_symbols",()))
    healthy=c.get("healthy",False) and fee_ok and day_ok and b.session.can_enter(now)
    unknown=any(o.state=="UNKNOWN_ORDER_STATE" for o in b.orders.values())
    if unknown: b.risk_alerts.add("UNKNOWN_ORDER_STATE")
    def pnl():
        total=b.realized_pnl;valid=True
        for s,p in b.positions.items():
            if p.quantity<=0:continue
            q=quotes.get(s)
            if not fresh(q,now):
                valid=False;b.risk_alerts.add("POSITION_WITHOUT_FRESH_QUOTE:"+s);continue
            proceeds=p.quantity*q.bid
            total+=proceeds-b.fees.charge("SELL",proceeds)-p.cost
        return total,valid
    net,marks_ok=pnl()
    if net<=-b.max_daily_loss:b.daily_halted=True;b.risk_alerts.add("DAILY_LOSS_LIMIT")
    healthy=healthy and not unknown and not b.daily_halted and marks_ok
    if not healthy:cancel_buys("ENTRY_RISK_GATE")
    for o in b.orders.values():
        if o.state in ACTIVE and o.side=="BUY" and o.symbol not in buy:
            b.cancel(o.client_id);event("CANCELED",client_id=o.client_id,reason="TRADABILITY_CHANGED")
    # Fill only previously submitted orders, once per source quote. New entries
    # and exits below wait for a subsequent quote; cached depth is not recycled.
    for s,q in quotes.items():
        if not fresh(q,now):continue
        if s not in sell and s not in buy:continue
        sides=({"BUY"} if s in buy else set()) | ({"SELL"} if s in sell else set())
        for fill in b.on_quote(q,now,allowed_sides=sides): event("FILL",**{k:v for k,v in fill.items() if k!="provenance"})
    net,marks_ok=pnl()
    if net<=-b.max_daily_loss:b.daily_halted=True;b.risk_alerts.add("DAILY_LOSS_LIMIT")
    if b.daily_halted:cancel_buys("DAILY_LOSS_LIMIT")
    if not fee_ok and any(p.quantity>0 for p in b.positions.values()):
        b.risk_alerts.add("EXIT_USING_LAST_VERIFIED_FEES")
    # Risk exits are independent of entry readiness, queue gaps and audit health.
    if b.daily_halted:
        for s,p in b.positions.items():
            q=quotes.get(s)
            if s not in sell or p.quantity<=p.reserved_quantity or not fresh(q,now):continue
            attempt=b.exit_attempts.get(s,0)
            if attempt>=3:b.risk_alerts.add("UNFILLED_EXIT_RISK:"+s);continue
            b.exit_attempts[s]=attempt+1
            o=b.submit_exit(f"risk:{b.session.day}:{s}:{attempt}",s,q.bid,p.quantity-p.reserved_quantity,now,"DAILY_LOSS_LIMIT")
            event("ORDER",client_id=o.client_id,side="SELL",reason=o.reason)
    for o in b.protect_positions(quotes,now,sell):event("ORDER",client_id=o.client_id,side="SELL",reason=o.reason)
    healthy=healthy and not b.daily_halted and marks_ok
    max_exposure=number(c["max_exposure"],positive=True)
    for signal in sorted(c.get("signals",()),key=lambda s:number(s.get("score") or 0),reverse=True):
        identity=signal["candidate_id"];s=signal["symbol"]
        if identity in b.orders:continue
        try:
            if signal.get("state")!="CONFIRMED":raise ValueError("SIGNAL_NOT_CONFIRMED")
            if not healthy or s not in buy:raise ValueError("ENTRY_RISK_GATE")
            if not 0<=now-signal["source_ms"]<=2000:raise ValueError("SIGNAL_STALE")
            q=quotes.get(s)
            if not fresh(q,now) or q.ask_size<=0 or q.bid_size<=0:raise ValueError("NO_EXECUTABLE_QUOTE")
            if (q.ask-q.bid)/q.bid>D(".002"):raise ValueError("WIDE_SPREAD")
            rule=c["rules"][s]
            tick=number(rule["tickSize"],positive=True);step=number(rule["stepSize"],positive=True)
            limit=entry_limit(signal["level"],q.ask,D(".005"),tick)
            exposure=sum(max(p.cost,p.quantity*quotes[symbol].ask) for symbol,p in b.positions.items() if p.quantity>0)
            exposure+=sum(o.reserved for o in b.orders.values() if o.side=="BUY" and o.state not in TERMINAL)
            budget=min(b.per_order_budget,b.cash,max_exposure-exposure)
            if signal.get("score") is not None:
                budget=min(budget,b.per_order_budget*min(D(100),number(signal["score"]))/100)
            if budget<=b.fees.minimum:raise ValueError("EXPOSURE_LIMIT")
            notional=min(budget/(1+b.fees.buy_rate),budget-b.fees.minimum,number(rule["maxNotional"],positive=True))
            quantity=floor_step(min(notional/limit,q.ask_size,number(rule["maxQty"],positive=True)),step)
            if quantity<=0 or quantity*limit<number(rule["minNotional"],positive=True):raise ValueError("MIN_NOTIONAL")
            o=b.submit(identity,s,limit,quantity,now)
            event("ORDER",client_id=o.client_id,symbol=s,side="BUY",quantity=str(quantity),limit=str(limit),fee_version=b.fee_version,signal=dict(signal))
        except (ValueError,KeyError) as error:
            event("ENTRY_REJECTED",client_id=identity,symbol=s,reason=str(error) if isinstance(error,ValueError) else "TRADING_RULE_INCOMPLETE")
    b.events=(b.events+events)[-500:]
    return events
