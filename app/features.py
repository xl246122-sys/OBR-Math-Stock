"""Bounded causal features; never interpolate missing historical prices or volume."""
from collections import deque, defaultdict
from datetime import date
from decimal import Decimal
from app.market import number, timestamp


class Momentum:
    def __init__(self, capacity=400, tolerance_ms=10000):
        self.samples = deque(maxlen=capacity)
        self.tolerance_ms = tolerance_ms

    def add(self, source_ms, price, received_ms):
        timestamp(source_ms)
        price = number(price, positive=True)
        if source_ms > received_ms or received_ms-source_ms > self.tolerance_ms:
            return False
        if self.samples and source_ms <= self.samples[-1][0]:
            return False
        if self.samples and source_ms-self.samples[-1][0] > self.tolerance_ms:
            self.samples.clear()  # a gap cannot masquerade as uninterrupted momentum
        # Retain one sample per second so high-frequency ticks cannot evict the
        # five-minute reference from the bounded buffer.
        if self.samples and self.samples[-1][0]//1000 == source_ms//1000:
            self.samples[-1] = (source_ms,price)
        else:
            self.samples.append((source_ms,price))
        while self.samples and self.samples[0][0] < source_ms-310000:
            self.samples.popleft()
        return True

    def at(self, now_ms):
        past = [(t,p) for t,p in self.samples if t <= now_ms]
        if not past or now_ms-past[-1][0] > self.tolerance_ms:
            return {1:None,3:None,5:None}
        current = past[-1][1]
        result = {}
        for minute in (1,3,5):
            target = now_ms-minute*60000
            reference = next(((t,p) for t,p in reversed(past) if t<=target),None)
            result[minute] = current/reference[1]-1 if reference and target-reference[0]<=self.tolerance_ms else None
        return result


class VolumeHistory:
    def __init__(self, rows=(), days=20):
        self.days = days
        self.values = defaultdict(dict)
        for row in rows:
            self.add(row["symbol"],date.fromisoformat(row["day"]),row["progress_ms"],row["volume"])

    def add(self,symbol,day,progress_ms,volume):
        if progress_ms <= 0 or progress_ms % 300000:
            raise ValueError("INVALID_VOLUME_PROGRESS")
        by_day = self.values[symbol]
        by_day.setdefault(day,{})[progress_ms] = number(volume)
        for old in sorted(by_day)[:-self.days]:
            del by_day[old]

    def before(self,symbol,day,progress_ms):
        return [(d,progress_ms,values[progress_ms]) for d,values in sorted(self.values.get(symbol,{}).items())
                if d<day and progress_ms in values]


class VolumeEvidence:
    """Collect quality facts, but do not self-approve a feed for trading."""
    def __init__(self):
        self.last = {}
        self.updates = defaultdict(int)
        self.failures = defaultdict(int)

    def observe(self,bar):
        previous = self.last.get(bar.symbol)
        valid = True
        if previous:
            if bar.start_ms < previous.start_ms or (bar.start_ms == previous.start_ms and bar.volume < previous.volume):
                valid = False
        if valid:
            self.last[bar.symbol] = bar
            self.updates[bar.symbol] += 1
        else:
            self.failures[bar.symbol] += 1
        return valid


class SessionVolumes:
    """Only complete, continuous RTH prefixes enter same-progress history."""
    def __init__(self, history):
        self.history = history
        self.current = {}

    def observe(self, bar, session, *, continuous=True):
        if not bar.closed or not session.open_ms <= bar.start_ms < bar.end_ms < session.close_ms:
            return False
        if (bar.start_ms-session.open_ms) % 300000 or bar.end_ms-bar.start_ms != 299999:
            return False
        previous = self.current.get(bar.symbol)
        if previous and session.day < previous[0]:
            return False
        if previous is None or previous[0] != session.day:
            previous = (session.day,session.open_ms,Decimal(0),True)
        day, expected, cumulative, complete = previous
        if bar.start_ms < expected:
            return False
        complete = complete and continuous and bar.start_ms == expected
        cumulative += number(bar.volume)
        self.current[bar.symbol] = (day,bar.end_ms+1,cumulative,complete)
        if complete:
            self.history.add(bar.symbol,day,bar.end_ms+1-session.open_ms,cumulative)
        return complete
