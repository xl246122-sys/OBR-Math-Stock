import asyncio
import json
import pytest
from app.feed import MarketFeed, stream_url


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
