"""Isolated live equity ledger, order state machine, and reconciliation contract.

Enforces user-mandated rules:
- BUY funded from MAIN wallet USDC budget;
- SELL proceeds settle to CARD wallet (never recycled into MAIN USDC without manual user action);
- Never auto-transfer between wallets;
- Order submission status='S' is ACCEPTED_PENDING_REPORT, never FILLED;
- Cancel submission is CANCEL_PENDING until confirmed by execution report/query;
- Timed-out creation latches UNKNOWN_ORDER_STATE without retrying or releasing reserved funds;
- Pre-existing manual account positions are isolated in external_positions and never auto-adopted.
"""
from dataclasses import dataclass, asdict
from decimal import Decimal
from app.execution import Fees
from app.live_contract import (
    limit_request,
    cancel_request,
    query_request,
    live_client_order_id,
)
from app.live_scope import InstrumentEvidence, public_scope
from app.market import number, timestamp


ACTIVE_LIVE_STATES = {
    "SUBMITTING",
    "ACCEPTED_PENDING_REPORT",
    "NEW",
    "PARTIALLY_FILLED",
    "CANCEL_PENDING",
    "UNKNOWN_ORDER_STATE",
}
TERMINAL_LIVE_STATES = {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}


@dataclass
class LiveOrder:
    client_id: str
    source_id: str
    symbol: str
    side: str
    limit: Decimal
    quantity: Decimal
    created_ms: int
    reserved_usdc: Decimal = Decimal(0)
    reserved_shares: Decimal = Decimal(0)
    state: str = "SUBMITTING"
    exchange_order_id: str | None = None
    filled: Decimal = Decimal(0)
    cumulative_quote: Decimal = Decimal(0)
    fees: Decimal = Decimal(0)
    reason: str = "BREAKOUT"
    last_update_ms: int = 0


@dataclass
class LivePosition:
    symbol: str
    quantity: Decimal = Decimal(0)
    cost_usdc: Decimal = Decimal(0)
    reserved_quantity: Decimal = Decimal(0)


class RecordedLiveTransport:
    """Contract-testing transport for recorded/mock exchange responses without real-money side effects."""

    def __init__(self, responses=None):
        self.responses = dict(responses or {})
        self.calls = []

    def place_order(self, payload, now_ms):
        if payload.get("provenance") == "SIMULATED":
            raise PermissionError("PAPER_ORDER_CANNOT_TOUCH_LIVE_TRANSPORT")
        self.calls.append(("PLACE", dict(payload), now_ms))
        handler = self.responses.get(("PLACE", payload["clientOrderId"])) or self.responses.get("PLACE")
        if callable(handler):
            return handler(payload, now_ms)
        if isinstance(handler, Exception):
            raise handler
        if isinstance(handler, dict):
            return dict(handler)
        return {"status": "S", "orderId": f"ord-{payload['clientOrderId'][-12:]}", "clientOrderId": payload["clientOrderId"]}

    def cancel_order(self, payload, now_ms):
        self.calls.append(("CANCEL", dict(payload), now_ms))
        client_id = payload["origClientOrderId"]
        handler = self.responses.get(("CANCEL", client_id)) or self.responses.get("CANCEL")
        if callable(handler):
            return handler(payload, now_ms)
        if isinstance(handler, Exception):
            raise handler
        if isinstance(handler, dict):
            return dict(handler)
        return {"status": "S", "origClientOrderId": client_id}

    def query_order(self, payload, now_ms):
        self.calls.append(("QUERY", dict(payload), now_ms))
        client_id = payload.get("origClientOrderId")
        handler = self.responses.get(("QUERY", client_id)) or self.responses.get("QUERY")
        if callable(handler):
            return handler(payload, now_ms)
        if isinstance(handler, Exception):
            raise handler
        if isinstance(handler, dict):
            return dict(handler)
        raise LookupError("ORDER_REPORT_UNAVAILABLE")


class LiveLedger:
    """Independent live account ledger separated from PaperBroker."""

    NAMESPACE = "LIVE_EQUITY_MAIN_USDC_CARD"

    def __init__(self, main_usdc_budget, per_order_budget, fees: Fees, *, max_positions=2):
        self.main_usdc_free = number(main_usdc_budget, positive=True)
        self.initial_main_usdc_budget = self.main_usdc_free
        self.per_order_budget = number(per_order_budget, positive=True)
        if self.per_order_budget > self.main_usdc_free:
            raise ValueError("LIVE_ORDER_BUDGET_EXCEEDS_MAIN_BUDGET")
        if type(max_positions) is not int or not 1 <= max_positions <= 5:
            raise ValueError("INVALID_POSITION_LIMIT")
        self.fees = fees
        self.max_positions = max_positions
        self.card_settlement_usdc = Decimal(0)
        self.realized_pnl_usdc = Decimal(0)
        self.orders: dict[str, LiveOrder] = {}
        self.source_to_client: dict[str, str] = {}
        self.strategy_positions: dict[str, LivePosition] = {}
        self.external_positions: dict[str, Decimal] = {}
        self.fills: list[dict] = []
        self.processed_trade_ids: set[str] = set()
        self.reconciled = False
        self.reconciled_ms: int | None = None
        self.blockers: set[str] = {"LIVE_ACCOUNT_NOT_RECONCILED"}

    @property
    def main_usdc_reserved(self) -> Decimal:
        return sum(
            (o.reserved_usdc for o in self.orders.values() if o.side == "BUY" and o.state in ACTIVE_LIVE_STATES),
            Decimal(0),
        )

    def can_submit_entry(self, symbol: str) -> tuple[bool, list[str]]:
        reasons = sorted(self.blockers)
        if not self.reconciled:
            if "LIVE_ACCOUNT_NOT_RECONCILED" not in reasons:
                reasons.append("LIVE_ACCOUNT_NOT_RECONCILED")
        if any(o.state == "UNKNOWN_ORDER_STATE" for o in self.orders.values()):
            reasons.append("LIVE_UNKNOWN_ORDER_STATE")
        if symbol in self.external_positions and self.external_positions[symbol] > 0:
            reasons.append("EXTERNAL_POSITION_ISOLATED")
        active_symbols = {s for s, p in self.strategy_positions.items() if p.quantity > 0}
        active_symbols.update(
            o.symbol for o in self.orders.values() if o.side == "BUY" and o.state in ACTIVE_LIVE_STATES
        )
        if symbol not in active_symbols and len(active_symbols) >= self.max_positions:
            reasons.append("LIVE_POSITION_LIMIT")
        return (len(reasons) == 0), reasons

    def reconcile_account(self, *, main_usdc_available, exchange_positions, open_orders, now_ms):
        """Reconcile exchange snapshot at startup without adopting pre-existing manual positions."""
        timestamp(now_ms)
        available = number(main_usdc_available)
        if available < self.main_usdc_free:
            self.blockers.add("LIVE_MAIN_USDC_INSUFFICIENT")
            self.reconciled = False
            return False
        self.blockers.discard("LIVE_MAIN_USDC_INSUFFICIENT")
        for symbol, qty in (exchange_positions or {}).items():
            total_qty = number(qty)
            strat_qty = self.strategy_positions.get(symbol, LivePosition(symbol)).quantity
            if total_qty < strat_qty:
                self.blockers.add(f"LIVE_POSITION_DEFICIT:{symbol}")
                self.reconciled = False
                return False
            manual_qty = total_qty - strat_qty
            if manual_qty > 0:
                self.external_positions[symbol] = manual_qty
        for raw_order in (open_orders or ()):
            cid = raw_order.get("clientOrderId") or raw_order.get("origClientOrderId")
            if cid and cid in self.orders:
                self.apply_execution_report(raw_order, now_ms)
            elif cid and cid.startswith("obr-"):
                self.blockers.add(f"UNTRACKED_STRATEGY_ORDER:{cid}")
                self.reconciled = False
                return False
        if any(o.state == "UNKNOWN_ORDER_STATE" for o in self.orders.values()):
            self.blockers.add("LIVE_UNKNOWN_ORDER_STATE")
            self.reconciled = False
            return False
        self.blockers.discard("LIVE_ACCOUNT_NOT_RECONCILED")
        self.blockers.discard("LIVE_UNKNOWN_ORDER_STATE")
        self.reconciled = True
        self.reconciled_ms = now_ms
        return True

    def submit_entry(self, *, source_id, symbol, price, quantity, instrument: InstrumentEvidence, transport, now_ms):
        timestamp(now_ms)
        if source_id in self.source_to_client:
            existing = self.orders[self.source_to_client[source_id]]
            if (existing.symbol, existing.limit, existing.quantity) != (symbol, number(price, positive=True), number(quantity, positive=True)):
                raise ValueError("LIVE_IDEMPOTENCY_CONFLICT")
            return existing
        ok, reasons = self.can_submit_entry(symbol)
        if not ok:
            raise ValueError(reasons[0])
        client_id = live_client_order_id(source_id, prefix="obr")
        req = limit_request(
            symbol=symbol,
            side="BUY",
            price=price,
            quantity=quantity,
            wallet="MAIN",
            quote_asset="USDC",
            client_id=client_id,
            instrument=instrument,
            now_ms=now_ms,
        )
        limit_dec = number(req["price"], positive=True)
        qty_dec = number(req["quantity"], positive=True)
        notional = limit_dec * qty_dec
        reserve = notional + self.fees.charge("BUY", notional)
        if reserve > self.per_order_budget or reserve > self.main_usdc_free:
            raise ValueError("LIVE_BUDGET_EXCEEDED")
        self.main_usdc_free -= reserve
        order = LiveOrder(
            client_id=client_id,
            source_id=source_id,
            symbol=symbol,
            side="BUY",
            limit=limit_dec,
            quantity=qty_dec,
            created_ms=now_ms,
            reserved_usdc=reserve,
            state="SUBMITTING",
            last_update_ms=now_ms,
        )
        self.orders[client_id] = order
        self.source_to_client[source_id] = client_id
        try:
            response = transport.place_order(req, now_ms)
        except Exception:
            # Never release reserved funds or retry when transport outcome is ambiguous.
            order.state = "UNKNOWN_ORDER_STATE"
            self.blockers.add("LIVE_UNKNOWN_ORDER_STATE")
            return order
        status = response.get("status")
        order.exchange_order_id = str(response["orderId"]) if response.get("orderId") is not None else None
        if status == "S" or status == "NEW":
            # Submission acknowledgement is NOT a fill.
            order.state = "ACCEPTED_PENDING_REPORT"
        elif status == "REJECTED":
            self.main_usdc_free += order.reserved_usdc
            order.reserved_usdc = Decimal(0)
            order.state = "REJECTED"
        else:
            order.state = "UNKNOWN_ORDER_STATE"
            self.blockers.add("LIVE_UNKNOWN_ORDER_STATE")
        return order

    def submit_exit(self, *, source_id, symbol, price, quantity, reason, instrument: InstrumentEvidence, transport, now_ms):
        timestamp(now_ms)
        if source_id in self.source_to_client:
            existing = self.orders[self.source_to_client[source_id]]
            if (existing.side, existing.symbol, existing.limit, existing.quantity) != ("SELL", symbol, number(price, positive=True), number(quantity, positive=True)):
                raise ValueError("LIVE_IDEMPOTENCY_CONFLICT")
            return existing
        position = self.strategy_positions.get(symbol)
        qty_dec = number(quantity, positive=True)
        if position is None or qty_dec > position.quantity - position.reserved_quantity:
            raise ValueError("LIVE_INSUFFICIENT_STRATEGY_POSITION")
        client_id = live_client_order_id(source_id, prefix="ext")
        req = limit_request(
            symbol=symbol,
            side="SELL",
            price=price,
            quantity=quantity,
            wallet="MAIN",
            quote_asset="USDC",
            client_id=client_id,
            instrument=instrument,
            now_ms=now_ms,
        )
        limit_dec = number(req["price"], positive=True)
        position.reserved_quantity += qty_dec
        order = LiveOrder(
            client_id=client_id,
            source_id=source_id,
            symbol=symbol,
            side="SELL",
            limit=limit_dec,
            quantity=qty_dec,
            created_ms=now_ms,
            reserved_shares=qty_dec,
            state="SUBMITTING",
            reason=reason,
            last_update_ms=now_ms,
        )
        self.orders[client_id] = order
        self.source_to_client[source_id] = client_id
        try:
            response = transport.place_order(req, now_ms)
        except Exception:
            order.state = "UNKNOWN_ORDER_STATE"
            self.blockers.add("LIVE_UNKNOWN_ORDER_STATE")
            return order
        status = response.get("status")
        order.exchange_order_id = str(response["orderId"]) if response.get("orderId") is not None else None
        if status in {"S", "NEW"}:
            order.state = "ACCEPTED_PENDING_REPORT"
        elif status == "REJECTED":
            position.reserved_quantity -= order.reserved_shares
            order.reserved_shares = Decimal(0)
            order.state = "REJECTED"
        else:
            order.state = "UNKNOWN_ORDER_STATE"
            self.blockers.add("LIVE_UNKNOWN_ORDER_STATE")
        return order

    def request_cancel(self, client_id, transport, now_ms):
        timestamp(now_ms)
        order = self.orders[client_id]
        if order.state in TERMINAL_LIVE_STATES:
            return order
        req = cancel_request(symbol=order.symbol, client_id=order.client_id, order_id=order.exchange_order_id)
        try:
            response = transport.cancel_order(req, now_ms)
        except Exception:
            order.state = "UNKNOWN_ORDER_STATE"
            self.blockers.add("LIVE_UNKNOWN_ORDER_STATE")
            return order
        if response.get("status") in {"S", "CANCEL_PENDING"}:
            # Do NOT release reserved cash/shares on cancel request acceptance; wait for confirmed CANCELED report.
            order.state = "CANCEL_PENDING"
            order.last_update_ms = now_ms
        elif response.get("status") == "CANCELED":
            self.apply_execution_report({"clientOrderId": client_id, "status": "CANCELED", "filledQty": str(order.filled)}, now_ms)
        else:
            order.state = "UNKNOWN_ORDER_STATE"
            self.blockers.add("LIVE_UNKNOWN_ORDER_STATE")
        return order

    def apply_execution_report(self, report: dict, now_ms: int):
        """Process authoritative order status / execution report from user stream or order detail query."""
        timestamp(now_ms)
        client_id = report.get("clientOrderId") or report.get("origClientOrderId")
        if client_id not in self.orders:
            raise KeyError("UNKNOWN_CLIENT_ORDER_ID")
        order = self.orders[client_id]
        if order.state in TERMINAL_LIVE_STATES:
            return order
        if report.get("orderId") is not None:
            order.exchange_order_id = str(report["orderId"])
        status = report.get("status")
        trade_id = str(report.get("tradeId") or "")
        new_filled = number(report.get("filledQty", order.filled))
        if new_filled < order.filled or new_filled > order.quantity:
            raise ValueError("INVALID_EXECUTION_REPORT_QTY")
        delta_qty = new_filled - order.filled
        if delta_qty > 0:
            if trade_id and trade_id in self.processed_trade_ids:
                return order
            if trade_id:
                self.processed_trade_ids.add(trade_id)
            fill_price = number(report["lastPrice"], positive=True)
            notional = delta_qty * fill_price
            fee = number(report["fee"]) if "fee" in report and report["fee"] is not None else (
                self.fees.charge(order.side, order.cumulative_quote + notional) - order.fees
            )
            order.filled = new_filled
            order.cumulative_quote += notional
            order.fees += fee
            if order.side == "BUY":
                consumed = notional + fee
                if consumed <= order.reserved_usdc:
                    order.reserved_usdc -= consumed
                else:
                    extra = consumed - order.reserved_usdc
                    order.reserved_usdc = Decimal(0)
                    self.main_usdc_free = max(Decimal(0), self.main_usdc_free - extra)
                pos = self.strategy_positions.setdefault(order.symbol, LivePosition(order.symbol))
                pos.quantity += delta_qty
                pos.cost_usdc += consumed
            else:
                pos = self.strategy_positions[order.symbol]
                allocated_cost = pos.cost_usdc * delta_qty / pos.quantity
                pos.quantity -= delta_qty
                pos.cost_usdc -= allocated_cost
                pos.reserved_quantity -= delta_qty
                order.reserved_shares -= delta_qty
                net_proceeds = notional - fee
                # SELL proceeds settle to CARD wallet, never auto-transferred to MAIN USDC.
                self.card_settlement_usdc += net_proceeds
                self.realized_pnl_usdc += net_proceeds - allocated_cost
            self.fills.append({
                "provenance": "LIVE_EXCHANGE_REPORT",
                "client_id": order.client_id,
                "source_id": order.source_id,
                "symbol": order.symbol,
                "side": order.side,
                "quantity": str(delta_qty),
                "price": str(fill_price),
                "fee": str(fee),
                "settlement_wallet": "MAIN" if order.side == "BUY" else "CARD",
                "time_ms": now_ms,
            })
        if status in {"NEW", "ACCEPTED"}:
            order.state = "PARTIALLY_FILLED" if order.filled > 0 else "NEW"
        elif status == "PARTIALLY_FILLED":
            order.state = "PARTIALLY_FILLED"
        elif status == "FILLED" or order.filled == order.quantity:
            order.state = "FILLED"
            if order.side == "BUY" and order.reserved_usdc > 0:
                self.main_usdc_free += order.reserved_usdc
                order.reserved_usdc = Decimal(0)
        elif status in {"CANCELED", "EXPIRED", "REJECTED"}:
            order.state = status
            if order.side == "BUY" and order.reserved_usdc > 0:
                self.main_usdc_free += order.reserved_usdc
                order.reserved_usdc = Decimal(0)
            elif order.side == "SELL" and order.reserved_shares > 0:
                self.strategy_positions[order.symbol].reserved_quantity -= order.reserved_shares
                order.reserved_shares = Decimal(0)
        order.last_update_ms = now_ms
        if not any(o.state == "UNKNOWN_ORDER_STATE" for o in self.orders.values()):
            self.blockers.discard("LIVE_UNKNOWN_ORDER_STATE")
        return order

    def snapshot(self):
        return {
            "schema": 1,
            "account_namespace": self.NAMESPACE,
            "paper_isolated": True,
            "scope": public_scope(),
            "reconciled": self.reconciled,
            "reconciled_ms": self.reconciled_ms,
            "main_usdc_free": str(self.main_usdc_free),
            "main_usdc_reserved": str(self.main_usdc_reserved),
            "card_settlement_usdc": str(self.card_settlement_usdc),
            "realized_pnl_usdc": str(self.realized_pnl_usdc),
            "per_order_budget": str(self.per_order_budget),
            "max_positions": self.max_positions,
            "fees": asdict(self.fees),
            "strategy_positions": [asdict(p) for p in self.strategy_positions.values() if p.quantity > 0],
            "external_positions": {k: str(v) for k, v in sorted(self.external_positions.items()) if v > 0},
            "orders": [asdict(o) for o in self.orders.values()],
            "fills": list(self.fills),
            "blockers": sorted(self.blockers),
        }

    @classmethod
    def restore(cls, state):
        if state.get("schema") != 1 or state.get("account_namespace") != cls.NAMESPACE:
            raise ValueError("UNSUPPORTED_LIVE_STATE")
        fees = Fees(**{k: Decimal(str(v)) for k, v in state["fees"].items()})
        budget = max(Decimal(str(state["main_usdc_free"])), Decimal(str(state["per_order_budget"])))
        ledger = cls(budget, state["per_order_budget"], fees, max_positions=state.get("max_positions", 2))
        ledger.main_usdc_free = number(state["main_usdc_free"])
        ledger.card_settlement_usdc = number(state.get("card_settlement_usdc", "0"))
        ledger.realized_pnl_usdc = Decimal(str(state.get("realized_pnl_usdc", "0")))
        ledger.reconciled = False  # Restart always requires fresh exchange reconciliation
        ledger.reconciled_ms = state.get("reconciled_ms")
        ledger.blockers = set(state.get("blockers", ())) | {"LIVE_ACCOUNT_NOT_RECONCILED"}
        for row in state.get("strategy_positions", ()):
            pos = LivePosition(
                row["symbol"],
                number(row["quantity"]),
                number(row["cost_usdc"]),
                number(row["reserved_quantity"]),
            )
            ledger.strategy_positions[pos.symbol] = pos
        for sym, qty in state.get("external_positions", {}).items():
            ledger.external_positions[sym] = number(qty)
        for row in state.get("orders", ()):
            vals = dict(row)
            for field_name in ("limit", "quantity", "reserved_usdc", "reserved_shares", "filled", "cumulative_quote", "fees"):
                vals[field_name] = number(vals[field_name])
            order = LiveOrder(**vals)
            ledger.orders[order.client_id] = order
            ledger.source_to_client[order.source_id] = order.client_id
        ledger.fills = list(state.get("fills", ()))
        return ledger


class LiveRuntime:
    """Independent live worker sharing the strategy's confirmed signal stream."""

    def __init__(self, store, config, ledger=None):
        self.store = store
        self.config = config
        self.ledger = ledger
        self.pending = []
        self.received_signals = []
        self.failure = None

    def submit(self, decision):
        payload = asdict(decision) if hasattr(decision, "__dataclass_fields__") else dict(decision)
        if len(self.pending) >= 100:
            self.failure = "LIVE_SIGNAL_QUEUE_FULL"
            return False
        self.pending.append(payload)
        self.received_signals = (self.received_signals + [payload])[-50:]
        return True

    def is_flat(self) -> bool:
        if self.ledger is None:
            return True
        has_pos = any(p.quantity > 0 for p in self.ledger.strategy_positions.values())
        has_ord = any(o.state in ACTIVE_LIVE_STATES for o in self.ledger.orders.values())
        return not has_pos and not has_ord

    def status_summary(self, live_enabled: bool):
        snap = self.ledger.snapshot() if self.ledger else None
        return {
            "account_namespace": LiveLedger.NAMESPACE,
            "paper_isolated": True,
            "shared_signal": True,
            "live_enabled": live_enabled,
            "initialized": self.ledger is not None,
            "reconciled": bool(self.ledger and self.ledger.reconciled),
            "configuration": self.config.public(),
            "main_usdc_free": snap["main_usdc_free"] if snap else str(self.config.allocated_usdc),
            "main_usdc_reserved": snap["main_usdc_reserved"] if snap else "0",
            "card_settlement_usdc": snap["card_settlement_usdc"] if snap else "0",
            "realized_pnl_usdc": snap["realized_pnl_usdc"] if snap else "0",
            "strategy_positions": snap["strategy_positions"] if snap else [],
            "external_positions": snap["external_positions"] if snap else {},
            "orders": (snap["orders"][-30:] if snap else []),
            "fills": (snap["fills"][-30:] if snap else []),
            "received_signals_count": len(self.received_signals),
            "pending_signals_count": len(self.pending),
        }
