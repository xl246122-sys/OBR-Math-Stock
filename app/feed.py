"""Bounded public-equity WS transport, intentionally without trade endpoints."""
import asyncio
import json
import random
import re
import time
from websockets.asyncio.client import connect


def stream_url(streams):
    streams = tuple(dict.fromkeys(streams))
    if not 1 <= len(streams) <= 20:
        raise ValueError("PROBE_SUBSCRIPTION_LIMIT")
    for stream in streams:
        if stream != "price" and not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}@(quote|kline_5m|tradability|tradingStatus)", stream):
            raise ValueError("INVALID_PUBLIC_STREAM")
    return "wss://nbstream.binance.com/equity/stream?streams=" + "/".join(streams)


class MarketFeed:
    def __init__(self, streams, *, capacity=1000, connector=connect):
        if capacity < 1:
            raise ValueError("INVALID_CAPACITY")
        self.url = stream_url(streams)
        self.queue = asyncio.Queue(maxsize=capacity)
        self.connector = connector
        self.connected = False
        self.data_gap = False
        self.reconnects = 0
        self.dropped = 0
        self.last_received_ms = None
        self.last_error = None

    async def run(self):
        failures = 0
        while True:
            try:
                async with self.connector(self.url, open_timeout=10, close_timeout=2,
                                          ping_interval=20, ping_timeout=20,
                                          max_size=4*1024*1024, max_queue=16) as ws:
                    self.connected = True
                    async for raw in ws:
                        payload = json.loads(raw)
                        if not isinstance(payload, dict):
                            raise ValueError("INVALID_MESSAGE")
                        data = payload.get("data", payload)
                        if not isinstance(data, dict):
                            raise ValueError("INVALID_MESSAGE")
                        received = time.time_ns()//1_000_000
                        self.last_received_ms = received
                        try:
                            self.queue.put_nowait((data, received, time.perf_counter_ns()))
                        except asyncio.QueueFull:
                            self.dropped += 1
                            self.data_gap = True
                            self.last_error = "MARKET_QUEUE_FULL"
                    # A normal close also creates a continuity gap.
                    self.last_error = "STREAM_CLOSED"
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = type(exc).__name__
            finally:
                self.connected = False
            self.data_gap = True
            self.reconnects += 1
            failures = min(failures+1, 6)
            # Never spin on an endpoint which opens then immediately closes.
            await asyncio.sleep(min(30, 2**(failures-1)) + random.random())
