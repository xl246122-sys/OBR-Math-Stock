"""Versioned audit storage; SQLite operations run outside the event loop."""
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_version VALUES (1);
CREATE TABLE IF NOT EXISTS breakout_candidates (
 candidate_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, kind TEXT NOT NULL,
 source_ms INTEGER NOT NULL, received_ms INTEGER NOT NULL,
 provenance TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS signal_decisions (
 candidate_id TEXT PRIMARY KEY REFERENCES breakout_candidates(candidate_id),
 state TEXT NOT NULL, reason TEXT NOT NULL, version TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS candidates_time ON breakout_candidates(source_ms);
CREATE TABLE IF NOT EXISTS system_events (
 id INTEGER PRIMARY KEY, time_ms INTEGER NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS market_bars (
 symbol TEXT NOT NULL, start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
 payload TEXT NOT NULL, PRIMARY KEY(symbol,start_ms));
CREATE TABLE IF NOT EXISTS performance_metrics (
 time_ms INTEGER PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS daily_reports (
 day TEXT PRIMARY KEY, generated_ms INTEGER NOT NULL, markdown TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS universe_snapshots (
 version TEXT NOT NULL, time_ms INTEGER NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(version,time_ms));
CREATE TABLE IF NOT EXISTS paper_state (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS trading_mode (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS paper_configuration (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS signal_forward_outcomes (
 candidate_id TEXT NOT NULL, horizon_minutes INTEGER NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(candidate_id,horizon_minutes));
CREATE INDEX IF NOT EXISTS events_time ON system_events(time_ms);
INSERT OR IGNORE INTO schema_version VALUES (2);
"""

MIGRATIONS = (
    (3, """
    CREATE TABLE IF NOT EXISTS live_state (
     singleton INTEGER PRIMARY KEY CHECK(singleton=1), payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS instrument_metadata (
     symbol TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_ms INTEGER NOT NULL);
    INSERT OR IGNORE INTO schema_version VALUES (3);
    """),
)


class AuditStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        self._apply_migrations()

    def _apply_migrations(self):
        with self.lock, self.db:
            current = self.db.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]
            for version, script in MIGRATIONS:
                if version > current:
                    self.db.executescript(script)

    def schema_version(self):
        with self.lock:
            return self.db.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]

    def write(self, batch):
        with self.lock, self.db:
            for decision, received_ms, provenance in batch:
                if provenance not in {"SYNTHETIC", "RECORDED", "LIVE_OBSERVATION"}:
                    raise ValueError("PROVENANCE_REQUIRED")
                payload = json.dumps(asdict(decision), default=str, sort_keys=True)
                self.db.execute("INSERT OR IGNORE INTO breakout_candidates VALUES (?,?,?,?,?,?,?)",
                                (decision.candidate_id, decision.symbol, decision.kind,
                                 decision.source_ms, received_ms, provenance, payload))
                self.db.execute("INSERT OR IGNORE INTO signal_decisions VALUES (?,?,?,?)",
                                (decision.candidate_id, decision.state, decision.reason, decision.version))

    def decisions(self):
        with self.lock:
            return self.db.execute("SELECT candidate_id,state,reason FROM signal_decisions ORDER BY candidate_id").fetchall()

    def write_events(self, batch):
        with self.lock, self.db:
            for kind, payload, observed_ms in batch:
                encoded = json.dumps(payload, default=str, sort_keys=True)
                if kind == "bar":
                    self.db.execute("INSERT OR IGNORE INTO market_bars VALUES (?,?,?,?)",
                                    (payload["symbol"], payload["start_ms"], payload["end_ms"], encoded))
                elif kind == "metrics":
                    self.db.execute("INSERT OR REPLACE INTO performance_metrics VALUES (?,?)", (observed_ms, encoded))
                elif kind == "universe":
                    self.db.execute("INSERT OR IGNORE INTO universe_snapshots VALUES (?,?,?)",
                                    (payload["version"], observed_ms, encoded))
                elif kind == "signal":
                    self.db.execute("INSERT OR IGNORE INTO breakout_candidates VALUES (?,?,?,?,?,?,?)",
                                    (payload["candidate_id"], payload["symbol"], payload["kind"],
                                     payload["source_ms"], observed_ms, payload["provenance"], encoded))
                    self.db.execute("INSERT OR IGNORE INTO signal_decisions VALUES (?,?,?,?)",
                                    (payload["candidate_id"], payload["state"], payload["reason"], payload["version"]))
                elif kind == "outcome":
                    self.db.execute("INSERT OR IGNORE INTO signal_forward_outcomes VALUES (?,?,?)",
                                    (payload["candidate_id"], payload["horizon_minutes"], encoded))
                elif kind == "alert":
                    self.db.execute("INSERT INTO system_events(time_ms,kind,detail) VALUES (?,?,?)",
                                    (observed_ms, payload["code"], encoded))
                else:
                    raise ValueError("UNKNOWN_AUDIT_EVENT")

    def recent(self, category, limit=100):
        queries = {
            "signals": "SELECT payload FROM breakout_candidates ORDER BY source_ms DESC LIMIT ?",
            "metrics": "SELECT payload FROM performance_metrics ORDER BY time_ms DESC LIMIT ?",
            "alerts": "SELECT detail FROM system_events ORDER BY time_ms DESC LIMIT ?",
            "reports": "SELECT payload FROM daily_reports ORDER BY day DESC LIMIT ?",
            "outcomes": "SELECT payload FROM signal_forward_outcomes ORDER BY rowid DESC LIMIT ?",
        }
        if category not in queries or not 1 <= limit <= 1000:
            raise ValueError("INVALID_QUERY")
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute(queries[category], (limit,))]

    def save_report(self, day, generated_ms, markdown, payload):
        with self.lock, self.db:
            self.db.execute("INSERT OR IGNORE INTO daily_reports VALUES (?,?,?,?)",
                            (day, generated_ms, markdown, json.dumps(payload, default=str)))

    def report(self, day):
        with self.lock:
            row = self.db.execute("SELECT markdown FROM daily_reports WHERE day=?", (day,)).fetchone()
            return None if row is None else row[0]

    def day_counts(self, start_ms, end_ms):
        with self.lock:
            signals = self.db.execute("SELECT state,COUNT(*) FROM breakout_candidates b JOIN signal_decisions d USING(candidate_id) WHERE source_ms>=? AND source_ms<? GROUP BY state", (start_ms,end_ms)).fetchall()
            bars = self.db.execute("SELECT COUNT(*) FROM market_bars WHERE end_ms>=? AND end_ms<?", (start_ms,end_ms)).fetchone()[0]
            return {"signals": dict(signals), "bars": bars}

    def load_paper_state(self):
        with self.lock:
            row = self.db.execute("SELECT payload FROM paper_state WHERE singleton=1").fetchone()
            return None if row is None else json.loads(row[0])

    def load_trading_mode(self):
        with self.lock:
            row = self.db.execute("SELECT payload FROM trading_mode WHERE singleton=1").fetchone()
            return None if row is None else json.loads(row[0])

    def load_paper_configuration(self):
        with self.lock:
            row=self.db.execute("SELECT payload FROM paper_configuration WHERE singleton=1").fetchone()
            return None if row is None else json.loads(row[0])

    def save_paper_configuration(self, configuration, revision, paper_state=None):
        with self.lock, self.db:
            row=self.db.execute("SELECT payload FROM paper_configuration WHERE singleton=1").fetchone()
            actual=json.loads(row[0])["revision"] if row else 0
            if actual!=revision:raise ValueError("CONFIG_REVISION_CONFLICT")
            state={"revision":actual+1,"configuration":configuration}
            self.db.execute("INSERT OR REPLACE INTO paper_configuration VALUES (1,?)",(json.dumps(state),))
            if paper_state is not None:
                self.db.execute("INSERT OR REPLACE INTO paper_state VALUES (1,?)",(json.dumps(paper_state,default=str),))
            self.db.execute("INSERT INTO system_events(time_ms,kind,detail) VALUES (?,?,?)",(time.time_ns()//1000000,
                "PAPER_CONFIG_CHANGED",json.dumps({"code":"PAPER_CONFIG_CHANGED",**state})))
            return state

    def save_trading_mode(self, mode, revision, reason):
        with self.lock, self.db:
            row = self.db.execute("SELECT payload FROM trading_mode WHERE singleton=1").fetchone()
            actual = json.loads(row[0])["revision"] if row else 0
            if actual != revision:
                raise ValueError("MODE_REVISION_CONFLICT")
            state = {"mode": mode, "revision": actual+1, "updated_ms": time.time_ns()//1000000}
            payload = json.dumps(state)
            self.db.execute("INSERT OR REPLACE INTO trading_mode VALUES (1,?)", (payload,))
            self.db.execute("INSERT INTO system_events(time_ms,kind,detail) VALUES (?,?,?)",
                            (state["updated_ms"], "TRADING_MODE_CHANGED", json.dumps({**state,"code":"TRADING_MODE_CHANGED","reason":reason})))
            return state

    def save_paper_state(self, state):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO paper_state VALUES (1,?)", (json.dumps(state, default=str),))

    def load_live_state(self):
        with self.lock:
            row = self.db.execute("SELECT payload FROM live_state WHERE singleton=1").fetchone()
            return None if row is None else json.loads(row[0])

    def save_live_state(self, state):
        if state.get("account_namespace") != "LIVE_EQUITY_MAIN_USDC_CARD":
            raise ValueError("INVALID_LIVE_STATE_NAMESPACE")
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO live_state VALUES (1,?)", (json.dumps(state, default=str),))

    def compact_paper_state(self, *, max_terminal_orders=200, max_fills=500):
        """Bound paper_state snapshot size by archiving older terminal orders and fills to system_events."""
        with self.lock, self.db:
            row = self.db.execute("SELECT payload FROM paper_state WHERE singleton=1").fetchone()
            if row is None:
                return {"compacted": False, "archived_orders": 0, "archived_fills": 0}
            state = json.loads(row[0])
            orders = state.get("orders", [])
            fills = state.get("fills", [])
            active = [o for o in orders if o.get("state") not in {"FILLED", "CANCELED", "EXPIRED"}]
            terminal = [o for o in orders if o.get("state") in {"FILLED", "CANCELED", "EXPIRED"}]
            archived_orders = terminal[:-max_terminal_orders] if max_terminal_orders > 0 and len(terminal) > max_terminal_orders else []
            kept_terminal = terminal[-max_terminal_orders:] if max_terminal_orders > 0 else []
            archived_fills = fills[:-max_fills] if max_fills > 0 and len(fills) > max_fills else []
            kept_fills = fills[-max_fills:] if max_fills > 0 else []
            if not archived_orders and not archived_fills:
                return {"compacted": False, "archived_orders": 0, "archived_fills": 0}
            now_ms = time.time_ns() // 1_000_000
            archive_payload = {
                "code": "PAPER_HISTORY_ARCHIVED",
                "time_ms": now_ms,
                "archived_orders_count": len(archived_orders),
                "archived_fills_count": len(archived_fills),
                "archived_orders": archived_orders,
                "archived_fills": archived_fills,
            }
            state["orders"] = active + kept_terminal
            state["fills"] = kept_fills
            self.db.execute("INSERT INTO system_events(time_ms,kind,detail) VALUES (?,?,?)",
                            (now_ms, "PAPER_HISTORY_ARCHIVED", json.dumps(archive_payload, default=str)))
            self.db.execute("INSERT OR REPLACE INTO paper_state VALUES (1,?)", (json.dumps(state, default=str),))
            return {"compacted": True, "archived_orders": len(archived_orders), "archived_fills": len(archived_fills)}

    def prune_metrics(self, before_ms):
        # Critical candidate/order/report history is intentionally never deleted here.
        with self.lock, self.db:
            self.db.execute("DELETE FROM performance_metrics WHERE time_ms < ?", (before_ms,))
        with self.lock:
            self.db.execute("PRAGMA wal_checkpoint(PASSIVE)")

    def volume_bars(self, since_ms):
        with self.lock:
            rows = self.db.execute("SELECT payload FROM market_bars WHERE start_ms>=? ORDER BY start_ms,symbol LIMIT 100000", (since_ms,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def pending_outcomes(self, since_ms):
        with self.lock:
            rows = self.db.execute("SELECT candidate_id,payload FROM breakout_candidates WHERE source_ms>=? ORDER BY source_ms LIMIT 2000", (since_ms,)).fetchall()
            result = []
            for identity,payload in rows:
                completed = [r[0] for r in self.db.execute("SELECT horizon_minutes FROM signal_forward_outcomes WHERE candidate_id=?", (identity,))]
                if len(completed)<5:
                    result.append((json.loads(payload),completed))
            return result

    def backup(self, target):
        target = Path(target)
        if target.resolve() == self.path.resolve() or target.exists():
            raise ValueError("BACKUP_TARGET_MUST_BE_NEW")
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.lock, sqlite3.connect(target) as destination:
            self.db.backup(destination)
            if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("BACKUP_INTEGRITY_FAILURE")

    def close(self):
        with self.lock:
            self.db.close()


class AuditWriter:
    def __init__(self, store, capacity=1000, batch_size=100):
        if capacity < 1 or batch_size < 1:
            raise ValueError("INVALID_QUEUE_SIZE")
        self.store, self.batch_size = store, batch_size
        self.queue = asyncio.Queue(maxsize=capacity)
        self.failure = None
        self.accepting = True

    @property
    def can_open_positions(self):
        return self.accepting and self.failure is None

    def submit(self, decision, received_ms, provenance):
        if not self.can_open_positions:
            return False
        try:
            self.queue.put_nowait((decision, received_ms, provenance))
            return True
        except asyncio.QueueFull:
            self.failure = "AUDIT_QUEUE_FULL"  # latched; explicit recovery required
            return False

    async def run(self):
        while True:
            item = await self.queue.get()
            if item is None:
                self.queue.task_done()
                return
            batch = [item]
            while len(batch) < self.batch_size and not self.queue.empty():
                next_item = self.queue.get_nowait()
                if next_item is None:
                    self.queue.task_done()
                    break
                batch.append(next_item)
            try:
                await asyncio.to_thread(self.store.write, batch)
            except Exception as exc:
                self.failure = "AUDIT_WRITE_FAILED:" + type(exc).__name__
                raise
            finally:
                for _ in batch:
                    self.queue.task_done()

    async def stop(self, task):
        self.accepting = False
        # Watch the worker as well as queue.join, so a failed disk cannot hang shutdown.
        drain = asyncio.create_task(self.queue.join())
        done, _ = await asyncio.wait({drain, task}, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            drain.cancel()
            await asyncio.gather(drain, return_exceptions=True)
            await task
            return
        await drain
        await self.queue.put(None)
        await task


class EventWriter(AuditWriter):
    def __init__(self, store, **kwargs):
        class Adapter:
            def write(self, batch):
                store.write_events(batch)
        super().__init__(Adapter(), **kwargs)

    def submit_event(self, kind, payload, observed_ms):
        return self.submit(kind, payload, observed_ms)
