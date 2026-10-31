"""Pure closed-bar research engine. No broker or network access.

Confirmation uses completed 5m bars; short-period momentum and live volume
calibration remain separate requirements before wiring this into trading.
"""
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
import hashlib
from statistics import median

from app.market import number


@dataclass(frozen=True)
class Parameters:
    lookback: int = 3
    min_history: int = 10
    min_rvol: Decimal = Decimal("1.5")
    max_chase: Decimal = Decimal("0.005")
    max_spread: Decimal = Decimal("0.002")
    max_consolidation: Decimal = Decimal("0.02")
    max_age_ms: int = 2000
    version: str = "closed-bar-research-v1"
    require_momentum: bool = False
    strength_weight: Decimal = Decimal("0.35")
    volume_weight: Decimal = Decimal("0.40")
    momentum_weight: Decimal = Decimal("0.25")

    def __post_init__(self):
        if self.lookback not in (3, 6) or self.min_history < 2 or self.max_age_ms <= 0:
            raise ValueError("INVALID_PARAMETERS")
        for v in (self.min_rvol, self.max_chase, self.max_spread, self.max_consolidation,
                  self.strength_weight,self.volume_weight,self.momentum_weight):
            number(v, positive=True)


@dataclass(frozen=True)
class Decision:
    candidate_id: str
    symbol: str
    kind: str
    state: str
    reason: str
    source_ms: int
    level: Decimal
    rvol: Decimal | None
    version: str
    parameters: str = ""
    momentum: tuple = ()
    score: Decimal | None = None


class OBRMathEngine:
    def __init__(self, symbol, session, parameters=None):
        self.symbol, self.session = symbol, session
        self.params = parameters or Parameters()
        self.bars = deque(maxlen=self.params.lookback + 1)
        self.last_end = None
        self.orb = None
        self.orb_emitted = False
        self.continuation_armed = True
        self.cumulative_volume = Decimal(0)
        self.complete = True

    def on_bar(self, bar, now_ms, historical_volumes=(), *, volume_verified=False,
               tradable=False, spread=None, momentum=None):
        bar.validate()
        if bar.symbol != self.symbol:
            raise ValueError("WRONG_SYMBOL")
        if not bar.closed or bar.end_ms >= now_ms:
            return []  # current/incomplete/future candle never enters the reference
        if not self.session.open_ms <= bar.start_ms < bar.end_ms < self.session.close_ms:
            return []
        if (bar.start_ms-self.session.open_ms) % 300000:
            return []
        if self.last_end is not None and bar.end_ms <= self.last_end:
            return []
        expected = self.session.open_ms if self.last_end is None else self.last_end + 1
        if bar.start_ms != expected:
            self.complete = False
        self.cumulative_volume += bar.volume
        decisions = []
        if bar.start_ms == self.session.open_ms:
            self.orb = bar
        elif self.orb and not self.orb_emitted and bar.close > self.orb.high:
            decisions.append(self._decide("ORB", self.orb.high, self.orb.start_ms, bar, now_ms,
                                          historical_volumes, volume_verified, tradable, spread, momentum))
            self.orb_emitted = True
        n = self.params.lookback
        if len(self.bars) >= n + 1:
            past = list(self.bars)
            consolidation = past[-n:]
            level = max(b.high for b in consolidation)
            width = (level-min(b.low for b in consolidation))/level
            trend = consolidation[0].close > past[0].close
            if bar.close <= level:
                self.continuation_armed = True
            elif self.continuation_armed and trend and width <= self.params.max_consolidation:
                decisions.append(self._decide("INTRADAY_CONTINUATION", level, consolidation[0].start_ms,
                                              bar, now_ms, historical_volumes, volume_verified, tradable, spread, momentum))
                self.continuation_armed = False
        self.bars.append(bar)
        self.last_end = bar.end_ms
        return decisions

    def _decide(self, kind, level, structure, bar, now, history, verified, tradable, spread, momentum):
        # Caller supplies only earlier sessions at the identical session progress.
        # Tuples (session_date, elapsed_ms, cumulative_volume) must match progress.
        history = list(history)
        progress = bar.end_ms + 1 - self.session.open_ms
        matched = [(day, v) for day, elapsed, v in history
                   if day < self.session.day and elapsed == progress]
        valid = [number(v) for day, v in matched]
        rvol = None
        if not self.complete:
            reason = "INCOMPLETE_SESSION"
        elif now - bar.end_ms > self.params.max_age_ms:
            reason = "DATA_STALE"
        elif not self.session.can_enter(now):
            reason = "ENTRY_WINDOW_CLOSED"
        elif not verified:
            reason = "DATA_INSUFFICIENT"
        elif len(valid) < self.params.min_history or len({d for d, _ in matched}) != len(valid):
            reason = "COLD_START"
        elif median(valid) <= 0:
            reason = "COLD_START"
        else:
            rvol = self.cumulative_volume / median(valid)
            if rvol < self.params.min_rvol:
                reason = "LOW_RVOL"
            elif self.params.require_momentum and (momentum is None or any(momentum.get(m) is None for m in (1,3,5))):
                reason = "MOMENTUM_DATA_INSUFFICIENT"
            elif self.params.require_momentum and any(momentum[m]<=0 for m in (1,3,5)):
                reason = "WEAK_MOMENTUM"
            elif (bar.close-level)/level > self.params.max_chase:
                reason = "CHASE_LIMIT"
            elif spread is None:
                reason = "NO_QUOTE"
            elif number(spread) > self.params.max_spread:
                reason = "WIDE_SPREAD"
            elif not tradable:
                reason = "TRADABILITY_UNVERIFIED"
            else:
                reason = "RESEARCH_CONFIRMED"
        state = "CONFIRMED" if reason == "RESEARCH_CONFIRMED" else "REJECTED"
        if reason in {"INCOMPLETE_SESSION", "COLD_START", "DATA_INSUFFICIENT", "TRADABILITY_UNVERIFIED", "NO_QUOTE", "MOMENTUM_DATA_INSUFFICIENT"}:
            state = "WATCH_ONLY"
        features=tuple((m,momentum.get(m)) for m in (1,3,5)) if momentum else ()
        score=None
        if rvol is not None and momentum and all(momentum.get(m) is not None for m in (1,3,5)) and spread is not None:
            clamp=lambda x:max(Decimal(0),min(Decimal(1),x))
            strength=clamp((bar.close/level-1)/self.params.max_chase)
            volume=clamp(rvol/(self.params.min_rvol*2))
            trend=clamp(sum(momentum.values())/Decimal("0.015"))
            total=self.params.strength_weight+self.params.volume_weight+self.params.momentum_weight
            score=100*clamp((self.params.strength_weight*strength+self.params.volume_weight*volume+
                             self.params.momentum_weight*trend)/total-Decimal(".2")*clamp(spread/self.params.max_spread))
        identity = f"{self.symbol}|{self.session.day}|{kind}|{structure}|{self.params}"
        return Decision(hashlib.sha256(identity.encode()).hexdigest(), self.symbol, kind, state,
                        reason, bar.end_ms, level, rvol, self.params.version, repr(self.params),features,score)
