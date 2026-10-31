import asyncio
from decimal import Decimal
import sqlite3

import pytest
from app.storage import AuditStore, AuditWriter
from app.strategy import Decision


def candidate(key="test"):
    return Decision(key, "TEST", "ORB", "REJECTED", "LOW_RVOL", 100,
                    Decimal(100), Decimal(".8"), "synthetic-test")


def test_wal_rejected_candidate_idempotency_and_restore(tmp_path):
    path = tmp_path / "audit.db"
    store = AuditStore(path)
    batch = [(candidate(), 101, "SYNTHETIC")]
    store.write(batch)
    store.write(batch)
    assert store.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert len(store.decisions()) == 1
    backup = tmp_path / "backup.db"
    store.backup(backup)
    store.close()
    restored = AuditStore(backup)
    assert restored.decisions() == [("test", "REJECTED", "LOW_RVOL")]
    restored.close()
    reopened = AuditStore(path)
    assert len(reopened.decisions()) == 1
    reopened.close()


def test_failed_batch_rolls_back(tmp_path):
    store = AuditStore(tmp_path / "audit.db")
    with pytest.raises(ValueError):
        store.write([(candidate(), 101, "SYNTHETIC"), (candidate("bad"), 102, "UNKNOWN")])
    assert store.decisions() == []
    store.close()


def test_async_drain_and_overflow_latch(tmp_path):
    async def scenario():
        store = AuditStore(tmp_path / "audit.db")
        writer = AuditWriter(store, capacity=1)
        assert writer.submit(candidate(), 101, "SYNTHETIC")
        assert not writer.submit(candidate("overflow"), 102, "SYNTHETIC")
        assert not writer.can_open_positions
        task = asyncio.create_task(writer.run())
        await asyncio.wait_for(writer.stop(task), 2)
        assert len(store.decisions()) == 1
        store.close()
    asyncio.run(scenario())


def test_disk_failure_does_not_hang_shutdown():
    class Broken:
        def write(self, batch):
            raise sqlite3.OperationalError("disk full")
    async def scenario():
        writer = AuditWriter(Broken())
        writer.submit(candidate(), 101, "SYNTHETIC")
        task = asyncio.create_task(writer.run())
        with pytest.raises(sqlite3.OperationalError):
            await asyncio.wait_for(writer.stop(task), 2)
        assert not writer.can_open_positions
    asyncio.run(scenario())


def test_schema_migration_live_state_isolation_and_paper_compaction(tmp_path):
    store = AuditStore(tmp_path / "audit.db")
    assert store.schema_version() == 4
    store.save_paper_state({
        "schema": 1,
        "cash": "600",
        "orders": [
            {"client_id": f"done-{i}", "state": "FILLED"} for i in range(5)
        ] + [{"client_id": "active-1", "state": "ACKNOWLEDGED"}],
        "fills": [{"client_id": f"done-{i}", "price": "100"} for i in range(6)],
    })
    store.save_live_state({
        "schema": 1,
        "account_namespace": "LIVE_EQUITY_MAIN_USDC_CARD",
        "main_usdc_free": "600",
    })
    assert store.load_live_state()["account_namespace"] == "LIVE_EQUITY_MAIN_USDC_CARD"
    result = store.compact_paper_state(max_terminal_orders=2, max_fills=3)
    assert result == {"compacted": True, "archived_orders": 3, "archived_fills": 3}
    compacted = store.load_paper_state()
    assert [o["client_id"] for o in compacted["orders"]] == ["active-1", "done-3", "done-4"]
    assert len(compacted["fills"]) == 3
    alerts = store.recent("alerts")
    assert any(a.get("code") == "PAPER_HISTORY_ARCHIVED" and a.get("archived_orders_count") == 3 for a in alerts)
    store.close()
