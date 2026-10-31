"""Post-decision outcomes never feed back into strategy state."""
from collections import defaultdict
from decimal import Decimal
from app.market import number


class OutcomeTracker:
    HORIZONS = (5,15,30,60)

    def __init__(self, emit, capacity=2000):
        self.emit, self.capacity = emit, capacity
        self.pending = defaultdict(dict)
        self.count = 0

    def add(self, candidate, close_ms, completed=()):
        identity, symbol = candidate["candidate_id"],candidate["symbol"]
        if identity in self.pending[symbol]:
            return
        targets = {m:candidate["source_ms"]+m*60000 for m in self.HORIZONS}
        targets[0] = close_ms
        targets = {m:t for m,t in targets.items() if m not in completed}
        if not targets:
            return
        if self.count >= self.capacity:
            raise ValueError("OUTCOME_CAPACITY_EXCEEDED")
        price = number(candidate["reference_price"],positive=True)
        self.pending[symbol][identity] = {"start":candidate["source_ms"],"price":price,"targets":targets,
                                           "low":price,"high":price,"last":candidate["source_ms"],"samples":0,
                                           "restored": bool(candidate.get("restored"))}
        self.count += 1

    def sample(self, symbol, price, source_ms, received_ms):
        if type(source_ms) is not int or source_ms > received_ms:
            return
        price = number(price,positive=True)
        for identity, state in list(self.pending.get(symbol,{}).items()):
            if source_ms <= state["last"]:
                continue
            state["last"] = source_ms
            state["samples"] += 1
            state["low"],state["high"] = min(state["low"],price),max(state["high"],price)
            for horizon,target in list(state["targets"].items()):
                if source_ms >= target:
                    valid = source_ms <= target+60000
                    self.emit({"candidate_id":identity,"horizon_minutes":horizon,"target_ms":target,
                               "sample_ms":source_ms if valid else None,
                               "return":str(price/state["price"]-1) if valid else None,
                               "sampled_mfe":str(state["high"]/state["price"]-1) if valid else None,
                               "sampled_mae":str(state["low"]/state["price"]-1) if valid else None,
                               "quality":"PARTIAL_AFTER_RESTART" if valid and state["restored"] else "SAMPLED" if valid else "MISSING",
                               "samples":state["samples"]},received_ms)
                    del state["targets"][horizon]
            self._remove_if_finished(symbol,identity,state)

    def expire(self, now_ms):
        for symbol, candidates in list(self.pending.items()):
            for identity,state in list(candidates.items()):
                for horizon,target in list(state["targets"].items()):
                    if now_ms > target+60000:
                        self.emit({"candidate_id":identity,"horizon_minutes":horizon,"target_ms":target,
                                   "sample_ms":None,"return":None,"quality":"MISSING"},now_ms)
                        del state["targets"][horizon]
                self._remove_if_finished(symbol,identity,state)

    def _remove_if_finished(self,symbol,identity,state):
        if not state["targets"]:
            del self.pending[symbol][identity]
            self.count -= 1
            if not self.pending[symbol]:
                del self.pending[symbol]
