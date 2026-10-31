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
    (4, """
    CREATE TABLE IF NOT EXISTS live_configuration (
     singleton INTEGER PRIMARY KEY CHECK(singleton=1), payload TEXT NOT NULL);
    INSERT OR IGNORE INTO schema_version VALUES (4);
    """),
    (5, """
    CREATE TABLE IF NOT EXISTS evolution_reviews (
     review_id TEXT PRIMARY KEY,
     period_type TEXT NOT NULL,
     period_key TEXT NOT NULL,
     start_ms INTEGER NOT NULL,
     end_ms INTEGER NOT NULL,
     generated_ms INTEGER NOT NULL,
     markdown TEXT NOT NULL,
     payload TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS evolution_reviews_period ON evolution_reviews(period_type, end_ms DESC);
    CREATE TABLE IF NOT EXISTS strategy_versions (
     version_id TEXT PRIMARY KEY,
     status TEXT NOT NULL,
     parent_version TEXT,
     created_ms INTEGER NOT NULL,
     updated_ms INTEGER NOT NULL,
     parameters TEXT NOT NULL,
     validation_evidence TEXT NOT NULL,
     notes TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS backtest_runs (
     run_id TEXT PRIMARY KEY,
     version_id TEXT NOT NULL,
     created_ms INTEGER NOT NULL,
     start_ms INTEGER NOT NULL,
     end_ms INTEGER NOT NULL,
     split_ratio TEXT NOT NULL,
     passed_validation INTEGER NOT NULL,
     payload TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS backtest_runs_version ON backtest_runs(version_id, created_ms DESC);
    INSERT OR IGNORE INTO schema_version VALUES (5);
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

    def load_live_configuration(self):
        with self.lock:
            row = self.db.execute("SELECT payload FROM live_configuration WHERE singleton=1").fetchone()
            return None if row is None else json.loads(row[0])

    def save_live_configuration(self, configuration, revision, live_state=None):
        with self.lock, self.db:
            row = self.db.execute("SELECT payload FROM live_configuration WHERE singleton=1").fetchone()
            actual = json.loads(row[0])["revision"] if row else 0
            if actual != revision:
                raise ValueError("LIVE_CONFIG_REVISION_CONFLICT")
            state = {"revision": actual + 1, "configuration": configuration}
            self.db.execute("INSERT OR REPLACE INTO live_configuration VALUES (1,?)", (json.dumps(state),))
            if live_state is not None:
                self.db.execute("INSERT OR REPLACE INTO live_state VALUES (1,?)", (json.dumps(live_state, default=str),))
            self.db.execute(
                "INSERT INTO system_events(time_ms,kind,detail) VALUES (?,?,?)",
                (time.time_ns() // 1000000, "LIVE_CONFIG_CHANGED", json.dumps({"code": "LIVE_CONFIG_CHANGED", **state})),
            )
            return state

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

    def window_signals_and_outcomes(self, start_ms, end_ms, limit=5000):
        with self.lock:
            rows = self.db.execute(
                "SELECT b.candidate_id, b.payload, d.state, d.reason, d.version "
                "FROM breakout_candidates b JOIN signal_decisions d USING(candidate_id) "
                "WHERE b.source_ms >= ? AND b.source_ms < ? ORDER BY b.source_ms ASC LIMIT ?",
                (start_ms, end_ms, limit),
            ).fetchall()
            result = []
            for cid, raw_payload, state, reason, version in rows:
                cand = json.loads(raw_payload)
                cand.update(state=state, reason=reason, version=version)
                outcomes = {}
                for h, op in self.db.execute(
                    "SELECT horizon_minutes, payload FROM signal_forward_outcomes WHERE candidate_id=?",
                    (cid,),
                ):
                    outcomes[str(h)] = json.loads(op)
                cand["forward_outcomes"] = outcomes
                result.append(cand)
            return result

    def window_bars(self, start_ms, end_ms, limit=50000):
        with self.lock:
            rows = self.db.execute(
                "SELECT payload FROM market_bars WHERE start_ms >= ? AND end_ms <= ? ORDER BY start_ms ASC, symbol ASC LIMIT ?",
                (start_ms, end_ms, limit),
            ).fetchall()
            return [json.loads(r[0]) for r in rows]

    def window_events(self, start_ms, end_ms, limit=2000):
        with self.lock:
            rows = self.db.execute(
                "SELECT time_ms, kind, detail FROM system_events WHERE time_ms >= ? AND time_ms < ? ORDER BY time_ms ASC LIMIT ?",
                (start_ms, end_ms, limit),
            ).fetchall()
            return [{"time_ms": t, "kind": k, "detail": json.loads(d)} for t, k, d in rows]

    def save_evolution_review(self, review_id, period_type, period_key, start_ms, end_ms, generated_ms, markdown, payload):
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO evolution_reviews VALUES (?,?,?,?,?,?,?,?)",
                (review_id, period_type, period_key, start_ms, end_ms, generated_ms, markdown, json.dumps(payload, default=str)),
            )

    def load_evolution_review(self, review_id):
        with self.lock:
            row = self.db.execute(
                "SELECT review_id, period_type, period_key, start_ms, end_ms, generated_ms, markdown, payload "
                "FROM evolution_reviews WHERE review_id=?",
                (review_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "review_id": row[0],
                "period_type": row[1],
                "period_key": row[2],
                "start_ms": row[3],
                "end_ms": row[4],
                "generated_ms": row[5],
                "markdown": row[6],
                "payload": json.loads(row[7]),
            }

    def list_evolution_reviews(self, period_type=None, limit=50):
        if not 1 <= limit <= 500:
            raise ValueError("INVALID_LIMIT")
        with self.lock:
            if period_type:
                rows = self.db.execute(
                    "SELECT review_id, period_type, period_key, start_ms, end_ms, generated_ms, markdown, payload "
                    "FROM evolution_reviews WHERE period_type=? ORDER BY end_ms DESC LIMIT ?",
                    (period_type, limit),
                ).fetchall()
            else:
                rows = self.db.execute(
                    "SELECT review_id, period_type, period_key, start_ms, end_ms, generated_ms, markdown, payload "
                    "FROM evolution_reviews ORDER BY end_ms DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [
                {
                    "review_id": r[0],
                    "period_type": r[1],
                    "period_key": r[2],
                    "start_ms": r[3],
                    "end_ms": r[4],
                    "generated_ms": r[5],
                    "markdown": r[6],
                    "payload": json.loads(r[7]),
                }
                for r in rows
            ]

    def save_strategy_version(self, version_id, status, parent_version, created_ms, updated_ms, parameters, validation_evidence, notes=""):
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO strategy_versions VALUES (?,?,?,?,?,?,?,?)",
                (
                    version_id,
                    status,
                    parent_version,
                    created_ms,
                    updated_ms,
                    json.dumps(parameters, default=str),
                    json.dumps(validation_evidence, default=str),
                    notes,
                ),
            )

    def load_strategy_version(self, version_id):
        with self.lock:
            row = self.db.execute(
                "SELECT version_id, status, parent_version, created_ms, updated_ms, parameters, validation_evidence, notes "
                "FROM strategy_versions WHERE version_id=?",
                (version_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "version_id": row[0],
                "status": row[1],
                "parent_version": row[2],
                "created_ms": row[3],
                "updated_ms": row[4],
                "parameters": json.loads(row[5]),
                "validation_evidence": json.loads(row[6]),
                "notes": row[7],
            }

    def list_strategy_versions(self, limit=50):
        with self.lock:
            rows = self.db.execute(
                "SELECT version_id, status, parent_version, created_ms, updated_ms, parameters, validation_evidence, notes "
                "FROM strategy_versions ORDER BY updated_ms DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                {
                    "version_id": r[0],
                    "status": r[1],
                    "parent_version": r[2],
                    "created_ms": r[3],
                    "updated_ms": r[4],
                    "parameters": json.loads(r[5]),
                    "validation_evidence": json.loads(r[6]),
                    "notes": r[7],
                }
                for r in rows
            ]

    def save_backtest_run(self, run_id, version_id, created_ms, start_ms, end_ms, split_ratio, passed_validation, payload):
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO backtest_runs VALUES (?,?,?,?,?,?,?,?)",
                (run_id, version_id, created_ms, start_ms, end_ms, str(split_ratio), 1 if passed_validation else 0, json.dumps(payload, default=str)),
            )

    def list_backtest_runs(self, version_id=None, limit=50):
        with self.lock:
            if version_id:
                rows = self.db.execute(
                    "SELECT run_id, version_id, created_ms, start_ms, end_ms, split_ratio, passed_validation, payload "
                    "FROM backtest_runs WHERE version_id=? ORDER BY created_ms DESC LIMIT ?",
                    (version_id, limit),
                ).fetchall()
            else:
                rows = self.db.execute(
                    "SELECT run_id, version_id, created_ms, start_ms, end_ms, split_ratio, passed_validation, payload "
                    "FROM backtest_runs ORDER BY created_ms DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [
                {
                    "run_id": r[0],
                    "version_id": r[1],
                    "created_ms": r[2],
                    "start_ms": r[3],
                    "end_ms": r[4],
                    "split_ratio": r[5],
                    "passed_validation": bool(r[6]),
                    "payload": json.loads(r[7]),
                }
                for r in rows
            ]

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
