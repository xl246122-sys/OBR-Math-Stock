"""Validated market primitives. Source time is never replaced by push time."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


def number(value, *, positive=False):
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("INVALID_NUMBER") from exc
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ValueError("INVALID_NUMBER")
    return result


def timestamp(value):
    if type(value) is not int or value < 0:
        raise ValueError("INVALID_TIMESTAMP")
    return value


@dataclass(frozen=True)
class Quote:
    symbol: str
    bid: Decimal
    ask: Decimal
    bid_size: Decimal
    ask_size: Decimal
    source_ms: int | None
    push_ms: int
    received_ms: int

    @classmethod
    def parse(cls, message, received_ms):
        if message.get("e") != "quote" or not isinstance(message.get("s"), str):
            raise ValueError("INVALID_QUOTE")
        quote = cls(message["s"], number(message["bp"], positive=True),
                    number(message["ap"], positive=True), number(message["bs"]),
                    number(message["as"]),
                    None if message.get("T") is None else timestamp(message["T"]),
                    timestamp(message["E"]), timestamp(received_ms))
        if quote.bid > quote.ask:
            raise ValueError("CROSSED_BOOK")
        return quote


class QuoteGate:
    def __init__(self, symbols, max_age_ms=2000, clock_tolerance_ms=250):
        self.symbols = frozenset(symbols)
        self.last = {}
        self.max_age_ms = max_age_ms
        self.clock_tolerance_ms = clock_tolerance_ms

    def check(self, quote):
        if quote.symbol not in self.symbols:
            return "UNSUBSCRIBED_SYMBOL"
        if quote.source_ms is None:
            return "UNKNOWN_SOURCE_LATENCY"
        age = quote.received_ms - quote.source_ms
        if age < -self.clock_tolerance_ms or quote.push_ms > quote.received_ms + self.clock_tolerance_ms:
            return "CLOCK_ANOMALY"
        if age > self.max_age_ms:
            return "DATA_STALE"
        if quote.ask_size == 0 or quote.bid_size == 0:
            return "EMPTY_BOOK"
        previous = self.last.get(quote.symbol)
        key = (quote.source_ms, quote.bid, quote.ask, quote.bid_size, quote.ask_size)
        if previous and key == previous:
            return "DUPLICATE"
        if previous and quote.source_ms <= previous[0]:
            return "OUT_OF_ORDER"
        self.last[quote.symbol] = key
        return "ACCEPTED"


@dataclass(frozen=True)
class Bar:
    symbol: str
    start_ms: int
    end_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    closed: bool

    @classmethod
    def parse(cls, message):
        k = message["k"]
        if message.get("e") != "kline" or k.get("i") != "5m" or k.get("s") != message.get("s"):
            raise ValueError("INVALID_KLINE")
        if type(k.get("x")) is not bool:
            raise ValueError("INVALID_CLOSED_FLAG")
        bar = cls(k["s"], timestamp(k["t"]), timestamp(k["ct"]),
                  *(number(k[field], positive=True) for field in ("o", "h", "l", "c")),
                  number(k["v"]), k["x"])
        bar.validate()
        return bar

    def validate(self):
        timestamp(self.start_ms)
        timestamp(self.end_ms)
        if type(self.closed) is not bool:
            raise ValueError("INVALID_CLOSED_FLAG")
        for value in (self.open, self.high, self.low, self.close):
            number(value, positive=True)
        number(self.volume)
        if self.end_ms - self.start_ms != 299999:
            raise ValueError("INVALID_BAR_DURATION")
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("INVALID_OHLC")
