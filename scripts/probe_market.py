"""Bounded public market probe; no credentials or trading transport."""
import asyncio
import argparse
from collections import deque
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from websockets.asyncio.client import connect


async def probe(stream, seconds=15):
    samples = deque(maxlen=100)
    result = {"stream": stream, "started_utc": datetime.now(timezone.utc).isoformat(), "message_count": 0}
    try:
        async with connect("wss://nbstream.binance.com/equity/ws/" + stream,
                           open_timeout=10, close_timeout=2, max_size=4*1024*1024) as ws:
            result["connected"] = True
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), deadline-time.monotonic())
                except asyncio.TimeoutError:
                    break
                received = time.time_ns() // 1_000_000
                message = json.loads(raw)
                rates = message.get("rates")
                if isinstance(rates, list):
                    message = {"e": message.get("e"), "symbol_count": len(rates),
                               "rates": [r for r in rates if r.get("s") in ("AAPL", "BA", "NBIS", "WDC", "MSTR")]}
                result["message_count"] += 1
                samples.append({"received_utc_ms": received, "message": message})
    except Exception as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)
    result["samples"] = list(samples)
    result["finished_utc"] = datetime.now(timezone.utc).isoformat()
    return result


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=15)
    parser.add_argument("--output", default="docs/evidence/market-probe.json")
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600:
        parser.error("seconds must be between 1 and 3600")
    results = await asyncio.gather(*(probe(s, args.seconds) for s in ("price", "AAPL@quote", "AAPL@kline_5m")))
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    for result in results:
        print(result["stream"], "samples=", len(result["samples"]), result.get("error", ""))


if __name__ == "__main__":
    asyncio.run(main())
