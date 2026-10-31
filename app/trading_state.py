"""Effective-time status changes; protected states cannot be undone by resumes."""
import heapq
from app.market import timestamp


class TradingState:
    BLOCKED = {"TRADING_HALTED","TRADING_PAUSED","TRADING_SUSPENDED","UNAVAILABLE"}
    def __init__(self, symbols):
        self.symbols = frozenset(symbols)
        self.pending = []
        self.serial = 0
        self.last = {}
        self.halted = set()
        self.overrides = {}

    def receive(self,event,now_ms):
        symbol = event.get("symbol")
        if symbol not in self.symbols:
            return
        effective = timestamp(event.get("time") if event.get("e")=="tradingStatus" else event.get("t"))
        if len(self.pending)>=2000:
            raise ValueError("STATUS_QUEUE_FULL")
        self.serial += 1
        heapq.heappush(self.pending,(effective,self.serial,dict(event)))
        self.advance(now_ms)

    def advance(self,now_ms):
        while self.pending and self.pending[0][0]<=now_ms:
            effective,_,event = heapq.heappop(self.pending)
            symbol = event["symbol"]
            if effective < self.last.get(symbol,-1):
                continue
            self.last[symbol] = effective
            status = event.get("status")
            if status in self.BLOCKED:
                self.halted.add(symbol)
            elif status=="TRADING_RESUMED":
                self.halted.discard(symbol)
            direction = event.get("tradability")
            protected = self.overrides.get(symbol) in {"OFFMARKET","DELISTING"}
            if direction is not None and (event.get("e")=="tradability" or not protected):
                self.overrides[symbol] = direction

    def direction(self,symbol,rules,now_ms):
        self.advance(now_ms)
        if symbol in self.halted:
            return "NONE"
        original = rules.get(symbol,{}).get("tradability","NONE")
        if original in {"OFFMARKET","DELISTING"}:
            return original
        return self.overrides.get(symbol,original)
