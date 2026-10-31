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


def partition_streams(symbols, stream_types=("quote", "kline_5m"), *, max_streams=20):
    """Split symbol stream subscriptions into bounded batches of at most 20 streams per WS connection."""
    symbols = tuple(dict.fromkeys(symbols))
    stream_types = tuple(dict.fromkeys(stream_types))
    if not stream_types or len(stream_types) > max_streams or max_streams > 20:
        raise ValueError("INVALID_STREAM_PARTITION")
    per_batch = max_streams // len(stream_types)
    batches = []
    for index in range(0, len(symbols), per_batch):
        chunk = symbols[index:index + per_batch]
        batches.append(tuple(f"{symbol}@{stream}" for symbol in chunk for stream in stream_types))
    return tuple(batches)


class MarketFeed:
    def __init__(self, streams, *, capacity=1000, connector=connect, role="generic"):
        if capacity < 1:
            raise ValueError("INVALID_CAPACITY")
        self.streams = tuple(dict.fromkeys(streams))
        self.role = role
        self.url = stream_url(self.streams)
        self.queue = asyncio.Queue(maxsize=capacity)
        self.connector = connector
        self.connected = False
        self.connected_since_ms = None
        self.data_gap = False
        self.gap_since_ms = None
        self.clean_messages_since_gap = 0
        self.reconnects = 0
        self.dropped = 0
        self.last_received_ms = None
        self.last_error = None

    def _latch_gap(self, error_code, now_ms=None):
        now_ms = time.time_ns() // 1_000_000 if now_ms is None else now_ms
        self.data_gap = True
        if self.gap_since_ms is None:
            self.gap_since_ms = now_ms
        self.clean_messages_since_gap = 0
        self.last_error = error_code

    def recover_continuity(self, now_ms, *, min_connected_ms=5000, min_clean_messages=3):
        """Clear latched data_gap only after verified connection stability and clean message continuity."""
        if not self.data_gap:
            return True
        if not self.connected or self.connected_since_ms is None:
            return False
        if now_ms - self.connected_since_ms < min_connected_ms:
            return False
        if self.clean_messages_since_gap < min_clean_messages:
            return False
        if self.queue.qsize() >= self.queue.maxsize:
            return False
        self.data_gap = False
        self.gap_since_ms = None
        return True

    async def run(self):
        failures = 0
        while True:
            try:
                async with self.connector(self.url, open_timeout=10, close_timeout=2,
                                          ping_interval=20, ping_timeout=20,
                                          max_size=4*1024*1024, max_queue=16) as ws:
                    self.connected = True
                    self.connected_since_ms = time.time_ns() // 1_000_000
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
                            self.clean_messages_since_gap += 1
                        except asyncio.QueueFull:
                            self.dropped += 1
                            self._latch_gap("MARKET_QUEUE_FULL", received)
                    # A normal close also creates a continuity gap.
                    self._latch_gap("STREAM_CLOSED")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._latch_gap(type(exc).__name__)
            finally:
                self.connected = False
                self.connected_since_ms = None
            self._latch_gap(self.last_error or "DISCONNECTED")
            self.reconnects += 1
            failures = min(failures+1, 6)
            # Never spin on an endpoint which opens then immediately closes.
            await asyncio.sleep(min(30, 2**(failures-1)) + random.random())
