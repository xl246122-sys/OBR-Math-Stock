"""Synthetic core-only benchmark: excludes WS, queues, DB and broker."""
from datetime import date
from decimal import Decimal as D
import json
from pathlib import Path
import platform
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.calendar import Session
from app.market import Bar
from app.strategy import OBRMathEngine


def percentile(values, p):
    values = sorted(values)
    return values[min(len(values)-1, int((len(values)-1)*p))] / 1_000_000


def main():
    result = {"provenance": "SYNTHETIC_CORE_ONLY", "python": sys.version,
              "platform": platform.platform(), "excludes": ["network", "queue", "storage", "broker"], "runs": []}
    session = Session.from_verified_hours(date(2026, 10, 30), source="SYNTHETIC_BENCHMARK")
    for count in (10, 50, 100, 200, 300):
        engines = [OBRMathEngine(f"TEST{i}", session) for i in range(count)]
        durations, candidates = [], 0
        for index in range(78):
            for engine in engines:
                start = session.open_ms + index*300000
                close = D(100) + D(index)/1000
                bar = Bar(engine.symbol, start, start+299999, close, close+D(".01"), close-D(".01"), close, D(100), True)
                before = time.perf_counter_ns()
                decisions = engine.on_bar(bar, bar.end_ms+1)
                durations.append(time.perf_counter_ns()-before)
                candidates += len(decisions)
        result["runs"].append({"symbols": count, "events": len(durations), "candidates": candidates,
                               "p50_ms": percentile(durations,.5), "p95_ms": percentile(durations,.95),
                               "p99_ms": percentile(durations,.99), "max_ms": max(durations)/1e6})
    output = Path(sys.argv[1] if len(sys.argv)>1 else "docs/evidence/synthetic-core-benchmark.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["runs"]))


if __name__ == "__main__":
    main()
