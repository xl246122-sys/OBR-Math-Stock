import asyncio
import json
import pytest
from app.feed import MarketFeed, stream_url, partition_streams


def test_only_public_equity_streams_and_bounded_subscription_count():
    assert "nbstream.binance.com/equity" in stream_url(["price", "AAPL@quote"])
    with pytest.raises(ValueError):
        stream_url(["https://example.com"])
    with pytest.raises(ValueError):
        stream_url([f"TEST{i}@quote" for i in range(21)])


def test_queue_overflow_latches_gap_and_transport_cancels():
    class Socket:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def __aiter__(self):
            return self.messages()
        async def messages(self):
            for _ in range(3):
                yield json.dumps({"stream": "price", "data": {"e": "price", "rates": []}})
            await asyncio.Event().wait()
    async def scenario():
        feed = MarketFeed(["price"], capacity=1, connector=lambda *a, **kw: Socket())
        task = asyncio.create_task(feed.run())
        await asyncio.sleep(.01)
        assert feed.queue.qsize() == 1
        assert feed.dropped == 2 and feed.data_gap
        assert (await feed.queue.get())[0]["e"] == "price"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not feed.connected
    asyncio.run(scenario())


def test_disconnect_triggers_gap_and_reconnect_count():
    class Broken:
        async def __aenter__(self):
            raise OSError("synthetic disconnect")
        async def __aexit__(self, *args):
            pass
    async def scenario():
        feed = MarketFeed(["price"], connector=lambda *a, **kw: Broken())
        task = asyncio.create_task(feed.run())
        await asyncio.sleep(.01)
        assert feed.reconnects == 1 and feed.data_gap
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


def test_partition_streams_and_role_abstraction():
    symbols = [f"SYM{i}" for i in range(25)]
    batches = partition_streams(symbols, ("quote", "kline_5m"))
    assert len(batches) == 3
    assert len(batches[0]) == 20 and len(batches[1]) == 20 and len(batches[2]) == 10
    feed = MarketFeed(batches[0], role="focus_market")
    assert feed.role == "focus_market"


def test_data_gap_continuity_recovery_requires_stability_and_clean_messages():
    feed = MarketFeed(["price"], role="price")
    feed._latch_gap("DISCONNECTED", now_ms=1000)
    assert feed.data_gap
    assert not feed.recover_continuity(10000)  # still disconnected
    feed.connected = True
    feed.connected_since_ms = 2000
    feed.clean_messages_since_gap = 2
    assert not feed.recover_continuity(8000)  # < 3 clean messages
    feed.clean_messages_since_gap = 3
    assert not feed.recover_continuity(5000)  # < 5000ms connected stability
    assert feed.recover_continuity(7500)
    assert not feed.data_gap and feed.gap_since_ms is None
