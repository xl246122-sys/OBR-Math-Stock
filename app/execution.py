"""In-memory paper-only limit execution. No network client exists here."""
from dataclasses import dataclass, asdict
from datetime import date
from app.calendar import Session
from decimal import Decimal, ROUND_DOWN
from app.market import number


def floor_step(value, step):
    value, step = number(value), number(step, positive=True)
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


@dataclass(frozen=True)
class Fees:
    buy_rate: Decimal
    sell_rate: Decimal
    minimum: Decimal

    def __post_init__(self):
        for value in (self.buy_rate, self.sell_rate, self.minimum):
            number(value)

    def charge(self, side, notional):
        return max(self.minimum, notional*(self.buy_rate if side == "BUY" else self.sell_rate))


def net_return(quantity, entry_price, entry_fees, exit_bid, fees):
    """Estimated executable return; fees are explicit assumptions, not exchange facts."""
    quantity, entry_price = number(quantity, positive=True), number(entry_price, positive=True)
    cost = quantity*entry_price + number(entry_fees)
    proceeds = quantity*number(exit_bid, positive=True)
    return (proceeds-fees.charge("SELL", proceeds)-cost)/cost


def exit_reason(net, now_ms, session):
    if session.should_exit(now_ms):
        return "SESSION_EXIT"
    if net <= Decimal("-0.008"):
        return "STOP_LOSS"
    if net >= Decimal("0.0175"):
        return "TAKE_PROFIT"
    return None


@dataclass
class PaperOrder:
    client_id: str
    symbol: str
    limit: Decimal
    quantity: Decimal
    expires_ms: int
    reserved: Decimal
    state: str = "ACKNOWLEDGED"
    filled: Decimal = Decimal(0)
    notional: Decimal = Decimal(0)
    fees: Decimal = Decimal(0)
    side: str = "BUY"
    reason: str = "BREAKOUT"
    created_ms: int = 0
    fee_schedule: dict | None = None
    fee_version: str = "EXPLICIT_ASSUMPTION"


@dataclass
class PaperPosition:
    symbol: str
    quantity: Decimal = Decimal(0)
    cost: Decimal = Decimal(0)  # remaining acquisition cost, including fees
    reserved_quantity: Decimal = Decimal(0)


class PaperBroker:
    """Paper-only research broker with independent, bounded exit protection.

    Budget and fees must be provided explicitly. Filled positions remain reserved
    from cash; cancel only releases unfilled funds. Quote depth is consumed once.
    """
    def __init__(self, cash, per_order_budget, fees, session, *, max_symbols=5, max_orders=5, max_daily_loss=None, max_positions=2):
        self.cash = number(cash, positive=True)
        self.per_order_budget = number(per_order_budget, positive=True)
        self.fees, self.session = fees, session
        if not 1 <= max_symbols <= 5 or max_orders < 1:
            raise ValueError("INVALID_RISK_LIMIT")
        self.max_symbols, self.max_orders = max_symbols, max_orders
        if type(max_positions) is not int or not 1 <= max_positions <= 5:
            raise ValueError("INVALID_POSITION_LIMIT")
        self.max_positions = max_positions
        self.orders = {}
        self.symbols = set()
        self.last_quote = {}
        self.positions = {}
        self.fills = []
        self.realized_pnl = Decimal(0)
        self.max_daily_loss = number(max_daily_loss if max_daily_loss is not None else self.cash*Decimal(".01"), positive=True)
        self.exit_attempts = {}
        self.risk_alerts = set()
        self.daily_halted = False
        self.events = []
        self.fee_version = "EXPLICIT_ASSUMPTION"

    def rollover(self, session):
        if session.day <= self.session.day:
            return False
        if any(p.quantity>0 for p in self.positions.values()) or any(
            o.state not in {"FILLED","CANCELED","EXPIRED"} for o in self.orders.values()):
            self.risk_alerts.add("OVERNIGHT_EXPOSURE_OR_UNKNOWN_ORDER")
            return False
        self.session=session
        self.symbols.clear()
        # Keep historical orders/fills for audit; daily entry count is tracked by symbols.
        self.realized_pnl=Decimal(0)
        self.exit_attempts.clear()
        self.risk_alerts.clear()
        self.daily_halted = False
        return True

    def cycle(self, context):
        from app.paper_cycle import cycle
        return cycle(self, context)

    def submit(self, client_id, symbol, limit, quantity, now_ms, ttl_ms=2000, *, healthy=True):
        limit, quantity = number(limit, positive=True), number(quantity, positive=True)
        if client_id in self.orders:
            existing = self.orders[client_id]
            if (symbol, limit, quantity) != (existing.symbol, existing.limit, existing.quantity):
                raise ValueError("IDEMPOTENCY_CONFLICT")
            return existing
        if not healthy or self.daily_halted or not self.session.can_enter(now_ms) or self.realized_pnl <= -self.max_daily_loss:
            raise ValueError("ENTRY_DISABLED")
        if ttl_ms <= 0 or ttl_ms > 10000:
            raise ValueError("INVALID_TTL")
        if symbol in self.symbols:
            raise ValueError("REENTRY_LIMIT")
        if len(self.symbols) >= min(self.max_symbols,self.max_orders):
            raise ValueError("DAILY_LIMIT")
        occupied = {s for s,p in self.positions.items() if p.quantity > 0}
        occupied.update(o.symbol for o in self.orders.values() if o.side == "BUY"
                        and o.state not in {"FILLED", "CANCELED", "EXPIRED"})
        if len(occupied) >= self.max_positions:
            raise ValueError("POSITION_LIMIT")
        cost = limit*quantity
        reserve = cost+self.fees.charge("BUY", cost)
        if reserve > self.per_order_budget or reserve > self.cash:
            raise ValueError("BUDGET_EXCEEDED")
        self.cash -= reserve
        order = PaperOrder(client_id, symbol, limit, quantity,
                           min(now_ms+ttl_ms, self.session.close_ms-20*60000), reserve,
                           created_ms=now_ms,fee_schedule=asdict(self.fees),fee_version=self.fee_version)
        self.orders[client_id] = order
        self.symbols.add(symbol)  # conservative: a canceled attempt also consumes a daily slot
        return order

    def submit_exit(self, client_id, symbol, limit, quantity, now_ms, reason, ttl_ms=2000):
        limit, quantity = number(limit, positive=True), number(quantity, positive=True)
        if client_id in self.orders:
            order = self.orders[client_id]
            if (order.side, order.symbol, order.limit, order.quantity) != ("SELL",symbol,limit,quantity):
                raise ValueError("IDEMPOTENCY_CONFLICT")
            return order
        position = self.positions.get(symbol)
        if position is None or quantity > position.quantity-position.reserved_quantity:
            raise ValueError("INSUFFICIENT_POSITION")
        if not 0 < ttl_ms <= 10000:
            raise ValueError("INVALID_TTL")
        position.reserved_quantity += quantity
        order = PaperOrder(client_id, symbol, limit, quantity, now_ms+ttl_ms, Decimal(0), side="SELL", reason=reason,
                           created_ms=now_ms,fee_schedule=asdict(self.fees),fee_version=self.fee_version)
        self.orders[client_id] = order
        return order

    def cancel(self, client_id, *, confirmed=True):
        order = self.orders[client_id]
        if order.state in {"FILLED", "CANCELED", "EXPIRED"}:
            return order
        if not confirmed:
            order.state = "UNKNOWN_ORDER_STATE"
            return order
        if order.side == "BUY":
            self.cash += order.reserved
        else:
            self.positions[order.symbol].reserved_quantity -= order.quantity-order.filled
        order.reserved = Decimal(0)
        order.state = "CANCELED"
        return order

    def expire(self, now_ms):
        for order in self.orders.values():
            if order.state in {"ACKNOWLEDGED", "PARTIALLY_FILLED"} and now_ms >= order.expires_ms:
                self.cancel(order.client_id)
                order.state = "EXPIRED"

    def on_quote(self, quote, now_ms, allowed_sides=None):
        self.expire(now_ms)
        if quote.source_ms is None or not 0 <= now_ms-quote.source_ms <= 2000:
            return []
        if quote.push_ms > now_ms+250 or quote.bid <= 0 or quote.ask < quote.bid:
            return []
        for value in (quote.bid,quote.ask,quote.bid_size,quote.ask_size):
            number(value)
        if quote.source_ms <= self.last_quote.get(quote.symbol, -1):
            return []
        self.last_quote[quote.symbol] = quote.source_ms
        available = {"BUY": quote.ask_size, "SELL": quote.bid_size}
        fills = []
        for order in self.orders.values():
            if order.symbol != quote.symbol or order.state not in {"ACKNOWLEDGED", "PARTIALLY_FILLED"}:
                continue
            if allowed_sides is not None and order.side not in allowed_sides:
                continue
            if quote.source_ms < order.created_ms:
                continue
            price = quote.ask if order.side == "BUY" else quote.bid
            marketable = price <= order.limit if order.side == "BUY" else price >= order.limit
            if not marketable or available[order.side] <= 0:
                continue
            quantity = min(order.quantity-order.filled, available[order.side])
            notional = quantity*price
            schedule = Fees(**{k:number(v) for k,v in order.fee_schedule.items()}) if order.fee_schedule else self.fees
            fee_total = schedule.charge(order.side, order.notional+notional)
            incremental_fee = fee_total-order.fees
            order.filled += quantity
            order.notional += notional
            order.fees = fee_total
            if order.side == "BUY":
                order.reserved -= notional+incremental_fee
                position = self.positions.setdefault(order.symbol, PaperPosition(order.symbol))
                position.quantity += quantity
                position.cost += notional+incremental_fee
            else:
                position = self.positions[order.symbol]
                cost = position.cost*quantity/position.quantity
                position.quantity -= quantity
                position.cost -= cost
                position.reserved_quantity -= quantity
                self.cash += notional-incremental_fee
                self.realized_pnl += notional-incremental_fee-cost
            available[order.side] -= quantity
            order.state = "FILLED" if order.filled == order.quantity else "PARTIALLY_FILLED"
            fills.append({"provenance": "SIMULATED", "client_id": order.client_id,
                          "symbol": order.symbol, "side": order.side, "reason": order.reason,
                          "quantity": quantity, "price": price, "fee": incremental_fee,
                          "source_ms": quote.source_ms,"fee_version":order.fee_version})
            if order.state == "FILLED":
                self.cash += order.reserved
                order.reserved = Decimal(0)
        self.fills.extend(fills)
        return fills

    def protect_positions(self, quotes, now_ms, tradable_symbols=None):
        """Runs even when entry health is false. Never invents a fill without a quote."""
        self.expire(now_ms)
        created = []
        for symbol, position in self.positions.items():
            if position.quantity == 0:
                continue
            if tradable_symbols is not None and symbol not in tradable_symbols:
                self.risk_alerts.add("POSITION_TRADING_HALTED:"+symbol)
                continue
            quote = quotes.get(symbol)
            if quote is None or quote.source_ms is None or not 0 <= now_ms-quote.source_ms <= 2000 or quote.push_ms>now_ms+250 or quote.bid<=0 or quote.ask<quote.bid:
                self.risk_alerts.add("POSITION_WITHOUT_FRESH_QUOTE:"+symbol)
                continue
            net = (position.quantity*quote.bid-self.fees.charge("SELL",position.quantity*quote.bid)-position.cost)/position.cost
            reason = exit_reason(net, now_ms, self.session)
            if reason is None:
                continue
            # Cancel pending buys before exiting so an old entry cannot reopen exposure.
            for order in self.orders.values():
                if order.symbol == symbol and order.side == "BUY" and order.state in {"ACKNOWLEDGED","PARTIALLY_FILLED"}:
                    self.cancel(order.client_id)
            remaining = position.quantity-position.reserved_quantity
            if remaining <= 0:
                continue
            attempt = self.exit_attempts.get(symbol,0)
            if attempt >= 3:
                self.risk_alerts.add("UNFILLED_EXIT_RISK:"+symbol)
                continue
            self.exit_attempts[symbol] = attempt+1
            created.append(self.submit_exit(f"exit:{self.session.day}:{symbol}:{attempt+1}",symbol,
                                           quote.bid,remaining,now_ms,reason))
        return created

    def snapshot(self):
        return {"schema":1,"cash":str(self.cash),"per_order_budget":str(self.per_order_budget),
                "fees":asdict(self.fees),"session":asdict(self.session),
                "max_symbols":self.max_symbols,"max_orders":self.max_orders,"max_daily_loss":str(self.max_daily_loss),
                "max_positions":self.max_positions,
                "daily_halted":self.daily_halted,"events":self.events,"fee_version":self.fee_version,
                "orders":[asdict(o) for o in self.orders.values()],"positions":[asdict(p) for p in self.positions.values()],
                "symbols":sorted(self.symbols),"last_quote":self.last_quote,"fills":self.fills,
                "realized_pnl":str(self.realized_pnl),"exit_attempts":self.exit_attempts,"risk_alerts":sorted(self.risk_alerts)}

    @classmethod
    def restore(cls, state):
        if state.get("schema") != 1:
            raise ValueError("UNSUPPORTED_PAPER_STATE")
        session_data = dict(state["session"])
        if isinstance(session_data["day"],str):
            session_data["day"] = date.fromisoformat(session_data["day"])
        session = Session(**session_data)
        fees = Fees(**{k:Decimal(v) for k,v in state["fees"].items()})
        broker = cls(state["cash"] if Decimal(state["cash"])>0 else "1", state["per_order_budget"],fees,session,
                     max_symbols=state["max_symbols"],max_orders=state["max_orders"],max_daily_loss=state["max_daily_loss"],
                     max_positions=state.get("max_positions",2))
        broker.cash = number(state["cash"])
        for row in state["orders"]:
            values = dict(row)
            for name in ("limit","quantity","reserved","filled","notional","fees"):
                values[name] = number(values[name])
            order = PaperOrder(**values)
            if order.fee_schedule is None:
                order.fee_schedule = asdict(fees)
            broker.orders[order.client_id] = order
        for row in state["positions"]:
            position = PaperPosition(row["symbol"],number(row["quantity"]),number(row["cost"]),number(row["reserved_quantity"]))
            if position.reserved_quantity > position.quantity:
                raise ValueError("CORRUPT_POSITION_RESERVATION")
            broker.positions[position.symbol] = position
        broker.symbols = set(state["symbols"])
        broker.last_quote = dict(state["last_quote"])
        broker.fills = list(state["fills"])
        broker.realized_pnl = Decimal(state["realized_pnl"])
        if not broker.realized_pnl.is_finite():
            raise ValueError("CORRUPT_PNL")
        broker.exit_attempts = dict(state["exit_attempts"])
        broker.risk_alerts = set(state["risk_alerts"])
        broker.daily_halted = state.get("daily_halted",False)
        broker.events = list(state.get("events",[]))
        broker.fee_version = state.get("fee_version","EXPLICIT_ASSUMPTION")
        return broker


def entry_limit(breakout_level, ask, deviation, tick):
    cap = number(breakout_level, positive=True)*(1+number(deviation))
    limit = floor_step(cap, tick)
    if number(ask, positive=True) > limit:
        raise ValueError("CHASE_LIMIT")
    return limit
