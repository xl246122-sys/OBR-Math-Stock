"""Live observation pipeline. All strategies remain fail-closed for trading."""
import asyncio
from collections import Counter
from dataclasses import asdict
from datetime import datetime, time as dt_time, timedelta
from decimal import Decimal
import json
import time

from app.calendar import Calendar, NY
from app.exchange import exchange_info
from app.feed import MarketFeed, partition_streams
from app.market import Bar, Quote, QuoteGate
from app.monitoring import Metrics, daily_report
from app.storage import AuditStore, EventWriter
from app.strategy import OBRMathEngine, Parameters
from app.features import Momentum, VolumeHistory, VolumeEvidence, SessionVolumes
from app.research import OutcomeTracker
from app.paper_config import PaperConfig, LiveConfig
from app.paper_runtime import PaperRuntime, readiness
from app.trading_state import TradingState
from app.trading_modes import TradingModes
from app.live_scope import public_scope, InstrumentRegistry
from app.live_execution import LiveLedger, LiveRuntime
from app.universe import select_tiered_focus


def _build_feed(feed_factory, streams, role):
    try:
        feed = feed_factory(list(streams), role=role)
    except TypeError:
        feed = feed_factory(list(streams))
        feed.role = role
    return feed


class Runtime:
    def __init__(self, settings, *, feed_factory=MarketFeed):
        self.settings = settings
        self.paper_config = PaperConfig.load(settings.paper_config_file) if settings.paper_config_file else PaperConfig()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = AuditStore(settings.data_dir/"obr.db")
        saved_config = self.store.load_paper_configuration()
        self.config_revision = saved_config["revision"] if saved_config else 0
        if saved_config:self.paper_config=PaperConfig(**saved_config["configuration"])
        saved_live_config = self.store.load_live_configuration()
        self.live_config_revision = saved_live_config["revision"] if saved_live_config else 0
        self.live_config = LiveConfig(**saved_live_config["configuration"]) if saved_live_config else LiveConfig()
        self.writer = EventWriter(self.store)
        self.universe = json.loads(settings.universe_file.read_text(encoding="utf-8"))
        self.candidates = frozenset(self.universe["symbols"])
        self.rules = self.universe.get("rules", {})
        self.calendar = Calendar.load(settings.calendar_file)
        ordered = [row.get("代码", row.get("symbol")) for row in self.universe.get("source_rows", [])]
        ordered += sorted(self.candidates)
        restored = self.store.load_paper_state() or {}
        pinned = [p["symbol"] for p in restored.get("positions", []) if Decimal(p["quantity"]) > 0]
        pinned += [o["symbol"] for o in restored.get("orders", []) if o["state"] not in {"FILLED","CANCELED","EXPIRED"}]
        self.focus = select_tiered_focus(ordered, self.rules, pinned=pinned, limit=settings.focus_limit)
        self.feeds = [_build_feed(feed_factory, ["price"], "price")]
        for batch in partition_streams(self.focus, ("quote", "kline_5m")):
            self.feeds.append(_build_feed(feed_factory, batch, "focus_market"))
        for batch in partition_streams(self.focus, ("tradability", "tradingStatus")):
            self.feeds.append(_build_feed(feed_factory, batch, "focus_status"))
        self.trading_state = TradingState(self.focus)
        self.paper = PaperRuntime(self.store,self.paper_config)
        self.trading_modes = TradingModes(self.store, live_available=settings.live_control_enabled)
        self.instruments = InstrumentRegistry.load(settings.data_dir/"instrument-evidence.json")
        saved_live = self.store.load_live_state()
        self.live_ledger = LiveLedger.restore(saved_live) if saved_live else None
        self.live = LiveRuntime(self.store, self.live_config, self.live_ledger)
        self.paper_verified = readiness(settings.data_dir,self.now_ms())
        self.gate = QuoteGate(self.focus)
        self.metrics = Metrics()
        self.quotes = {}
        self.momentum = {symbol: Momentum() for symbol in self.focus}
        self.volume_history = VolumeHistory()
        self.session_volumes = SessionVolumes(self.volume_history)
        self.volume_evidence = VolumeEvidence()
        for row in self.store.volume_bars(self.now_ms()-45*86400000):
            if row.get("symbol") not in self.focus:
                continue
            session = self.calendar.sessions.get(datetime.fromtimestamp(row["start_ms"]/1000, NY).date())
            if session:
                bar = Bar(**{name: row[name] for name in Bar.__dataclass_fields__})
                self.session_volumes.observe(bar, session, continuous=row.get("volume_continuity") is True)
        self.engines = {}
        self.seen = set()
        self.phases = {}
        self.tasks = []
        self.writer_task = None
        self.fatal = None
        self.rules_verified = False
        self.rules_checked_ms = None
        self.alert_ticks = Counter()
        self.alerted = set()
        self.last_snapshot = {}
        self.last_day = None
        self.outcomes = OutcomeTracker(lambda payload, observed: self.writer.submit_event("outcome",payload,observed))
        for candidate,completed in self.store.pending_outcomes(self.now_ms()-2*86400000):
            if "reference_price" in candidate and "session_close_ms" in candidate:
                self.outcomes.add({**candidate,"restored":True},candidate["session_close_ms"],completed)

    async def start(self):
        self.writer_task = asyncio.create_task(self.writer.run(), name="audit-writer")
        self.writer.submit_event("universe", {"version": self.universe["version"], "candidates": sorted(self.candidates),
                                             "focus": self.focus, "selection": "source_order_verified_buy_sell"}, self.now_ms())
        for feed in self.feeds:
            self.tasks.extend([asyncio.create_task(feed.run()), asyncio.create_task(self.consume(feed))])
        self.tasks.extend([asyncio.create_task(self.maintenance()), asyncio.create_task(self.refresh_rules()),
                           asyncio.create_task(self.paper_loop(),name="independent-paper-risk")])
        for task in [self.writer_task, *self.tasks]:
            task.add_done_callback(self.task_completed)

    def task_completed(self, task):
        if not task.cancelled() and task.exception() is not None:
            self.fatal = "BACKGROUND_TASK_FAILED:"+type(task.exception()).__name__

    @staticmethod
    def now_ms():
        return time.time_ns()//1_000_000

    def status(self):
        now = self.now_ms()
        local = datetime.fromtimestamp(now/1000, NY)
        session = self.calendar.sessions.get(local.date())
        phase = self.calendar.status(local.date())
        if session:
            phase = "RTH_OPEN" if session.open_ms <= now < session.close_ms else "RTH_CLOSED"
        blockers = list(self.paper_verified["blockers"])
        if not self.trading_modes.paper_enabled:blockers.append("PAPER_MODE_OFF")
        if self.paper_verified["fees"] is None: blockers.append("FEES_NOT_VERIFIED")
        if not set(self.focus)<=self.paper_verified["volume_symbols"]:blockers.append("VOLUME_NOT_VERIFIED")
        if self.paper.failure:blockers.append(self.paper.failure)
        if self.paper.cached.get("daily_halted"):blockers.append("DAILY_LOSS_LIMIT")
        if not all(feed.connected for feed in self.feeds):blockers.append("MARKET_DISCONNECTED")
        if self.last_snapshot.get("disk_free_ratio",1)<.25:blockers.append("DISK_LOW")
        if self.last_snapshot.get("processing",{}).get("p95_ms",0)>100:blockers.append("PROCESSING_LATENCY_HIGH")
        if session:
            progress=max(0,(now-session.open_ms)//300000*300000)
            if any(len(self.volume_history.before(s,session.day,progress))<10 for s in self.focus):
                blockers.append("HISTORICAL_VOLUME_COLD_START")
        if not self.rules_verified or self.rules_checked_ms is None or not 0<=now-self.rules_checked_ms<=20*60000:
            blockers.append("EXCHANGE_RULES_UNVERIFIED_OR_STALE")
        if any(feed.data_gap for feed in self.feeds):
            blockers.append("MARKET_DATA_GAP")
        if self.writer.failure or self.fatal:
            blockers.append(self.writer.failure or self.fatal)
        return {"health": "CRITICAL" if self.writer.failure or self.fatal or self.paper.failure else ("DEGRADED" if blockers else "HEALTHY"),
                "mode": "PAPER_ACTIVE" if not blockers and session and session.can_enter(now) else "WATCH_ONLY", "paper_mode": True, "live_trading_enabled": False, "version": "0.6.0",
                "market_phase": phase, "market_connection": "CONNECTED" if all(f.connected for f in self.feeds) else "CONNECTING",
                "candidate_count": len(self.candidates), "supported_count": len(self.rules),
                "focus_count": len(self.focus), "focus_symbols": self.focus, "observed_symbols": len(self.seen),
                "rules_verified": self.rules_verified, "rules_checked_ms": self.rules_checked_ms,
                "blockers": blockers, "heartbeat_ms": now,
                "paper_config": self.paper_config.public(),
                "live_config": self.live_config.public(),
                "paper_pipeline_connected":True,"paper_account_initialized":self.paper.account is not None,
                "trading_modes":self.mode_status(),
                "momentum_ready_symbols": [s for s,m in self.momentum.items() if all(v is not None for v in m.at(now).values())],
                "volume_quality_failures": dict(self.volume_evidence.failures),
                "feeds": [{"role": getattr(f, "role", "generic"), "connected": f.connected, "data_gap": f.data_gap,
                           "queue": f.queue.qsize(), "dropped": f.dropped,
                           "reconnects": f.reconnects, "last_received_ms": f.last_received_ms} for f in self.feeds]}

    def feeds_by_role(self, role):
        return [f for f in self.feeds if getattr(f, "role", None) == role]

    def status_feeds_healthy(self):
        status_feeds = self.feeds_by_role("focus_status")
        if not status_feeds and len(self.feeds) > 2:
            status_feeds = [self.feeds[2]]
        return bool(status_feeds) and all(f.connected and not f.data_gap for f in status_feeds)

    def recover_feed_continuity(self, now_ms):
        recovered = []
        for feed in self.feeds:
            if feed.data_gap and hasattr(feed, "recover_continuity") and feed.recover_continuity(now_ms):
                role = getattr(feed, "role", "generic")
                recovered.append(role)
                self.alert("FEED_CONTINUITY_RECOVERED", {"role": role, "reconnects": feed.reconnects})
        return recovered

    async def refresh_rules(self):
        while True:
            if self.settings.binance_api_key:
                result = await asyncio.to_thread(exchange_info, self.settings.binance_api_key)
                self.rules_verified = result.get("http_status") == 200 and isinstance(result.get("symbols"), list)
                if self.rules_verified:
                    self.rules = {r["symbol"]: r for r in result["symbols"] if isinstance(r, dict) and r.get("symbol") in self.candidates}
                    self.rules_checked_ms = self.now_ms()
                else:
                    self.alert("EXCHANGE_RULES_REFRESH_FAILED", {k:v for k,v in result.items() if k != "symbols"})
            await asyncio.sleep(900)

    def alert(self, code, detail):
        self.writer.submit_event("alert", {"code": code, "detail": detail, "time_ms": self.now_ms()}, self.now_ms())

    async def consume(self, feed):
        while True:
            message, received, queued_ns = await feed.queue.get()
            started = time.perf_counter_ns()
            self.metrics.queue_ms.append((started-queued_ns)/1e6)
            try:
                self.process(message, received, gap=feed.data_gap)
            except (ValueError, TypeError, KeyError, ArithmeticError):
                self.metrics.counts["INVALID_MESSAGE"] += 1
            except Exception as error:
                self.fatal = "PROCESSOR_FAILED:"+type(error).__name__
                self.alert(self.fatal, {})
                raise
            finally:
                self.metrics.processing_ms.append((time.perf_counter_ns()-started)/1e6)
                feed.queue.task_done()

    def process(self, message, received_ms, *, gap=False):
        self.metrics.counts["messages"] += 1
        event = message.get("e")
        if event in {"tradability","tradingStatus"}:
            self.trading_state.receive(message,received_ms)
            return
        if event == "price":
            for item in message.get("rates", []):
                symbol = item.get("s")
                if symbol in self.candidates:
                    self.seen.add(symbol)
                    self.phases[symbol] = item.get("mp", "UNKNOWN")
                    source = item.get("t")
                    if type(source) is int:
                        self.metrics.source_age_ms.append(received_ms-source)
                        self.outcomes.sample(symbol,item.get("p"),source,received_ms)
                        if symbol in self.momentum:
                            if gap:
                                self.momentum[symbol].samples.clear()
                            else:
                                self.momentum[symbol].add(source,item.get("p"),received_ms)
                    else:
                        self.metrics.counts["UNKNOWN_SOURCE_LATENCY"] += 1
            return
        if event == "quote":
            quote = Quote.parse(message, received_ms)
            verdict = self.gate.check(quote)
            self.metrics.counts[verdict] += 1
            if verdict == "ACCEPTED":
                self.quotes[quote.symbol] = quote
            elif verdict == "EMPTY_BOOK" and quote.symbol in self.focus and quote.source_ms is not None and 0<=received_ms-quote.source_ms<=2000:
                previous=self.quotes.get(quote.symbol)
                if previous is None or quote.source_ms>previous.source_ms:
                    self.quotes[quote.symbol]=quote  # exits may still use a non-empty bid
            return
        if event != "kline":
            return
        bar = Bar.parse(message)
        if bar.start_ms > received_ms or (bar.closed and bar.end_ms >= received_ms):
            return
        if bar.symbol in self.focus and not self.volume_evidence.observe(bar):
            self.metrics.counts["VOLUME_MONOTONICITY_FAILED"] += 1
            return
        if bar.symbol not in self.focus or not bar.closed or bar.end_ms >= received_ms:
            return
        local_day = datetime.fromtimestamp(bar.start_ms/1000, NY).date()
        session = self.calendar.sessions.get(local_day)
        if session is None:
            self.metrics.counts["CALENDAR_UNKNOWN"] += 1
            return
        self.session_volumes.observe(bar,session,continuous=not gap)
        self.writer.submit_event("bar", {**asdict(bar), "source": "BINANCE_EQUITY", "received_ms": received_ms,
                                          "volume_continuity":not gap}, received_ms)
        engine = self.engines.get(bar.symbol)
        if engine is None or engine.session.day != local_day:
            if engine and local_day < engine.session.day:
                return
            engine = self.engines[bar.symbol] = OBRMathEngine(bar.symbol, session, Parameters(require_momentum=True,version="closed-bar-momentum-v2"))
        if gap:
            engine.complete = False
        quote = self.quotes.get(bar.symbol)
        spread = None
        if quote and quote.source_ms is not None and 0 <= received_ms-quote.source_ms <= 2000:
            spread = (quote.ask-quote.bid)/quote.bid
        history = self.volume_history.before(bar.symbol,local_day,bar.end_ms+1-session.open_ms)
        decisions = engine.on_bar(bar, received_ms, historical_volumes=history,
                                  volume_verified=bar.symbol in self.paper_verified["volume_symbols"] and not self.volume_evidence.failures[bar.symbol],
                                  tradable=self.rules_verified and self.trading_state.direction(bar.symbol,self.rules,received_ms) in {"BUY_SELL","BUY"},
                                  spread=spread,momentum=self.momentum[bar.symbol].at(bar.end_ms))
        for decision in decisions:
            self.metrics.counts[decision.reason] += 1
            payload = {**asdict(decision), "provenance": "LIVE_OBSERVATION", "reference_price":str(bar.close),
                       "session_close_ms":session.close_ms}
            if self.writer.submit_event("signal",payload,received_ms):
                self.outcomes.add(payload,session.close_ms)
                if decision.state=="CONFIRMED":
                    if self.trading_modes.paper_enabled:
                        self.paper.submit(decision)
                    if self.trading_modes.live_enabled:
                        self.live.submit(decision)

    def mode_status(self):
        now = self.now_ms()
        live_blockers = []
        if self.live_ledger is None or not self.live_ledger.reconciled:
            live_blockers.append("LIVE_ACCOUNT_NOT_RECONCILED")
        if self.paper_verified["fees"] is None:
            live_blockers.append("LIVE_FEES_NOT_VERIFIED")
        inst_summary = self.instruments.summary(self.focus or self.candidates, now)
        if not inst_summary["all_verified"]:
            live_blockers.append("LIVE_INSTRUMENT_METADATA_NOT_VERIFIED")
        result = self.trading_modes.snapshot(live_blockers)
        result["live_scope"] = public_scope()
        result["control_configured"] = len(self.settings.control_token)>=32 and self.settings.control_token!=self.settings.api_token
        result["live_config"] = self.live_config_status()
        result["live_ledger"] = self.live.status_summary(self.trading_modes.live_enabled)
        return result

    def config_status(self):
        return {"revision":self.config_revision,"configuration":self.paper_config.public(),
                "initial_cash_locked":self.paper.account is not None}

    def live_config_status(self):
        return {"revision": self.live_config_revision, "configuration": self.live_config.public(),
                "live_enabled": self.trading_modes.live_enabled, "paper_enabled": self.trading_modes.paper_enabled,
                "shared_signal": True}

    async def change_live_config(self, config, revision):
        async with self.trading_modes.lock:
            if revision != self.live_config_revision:
                raise ValueError("LIVE_CONFIG_REVISION_CONFLICT")
            if not self.live.is_flat():
                raise ValueError("LIVE_ACCOUNT_MUST_BE_FLAT")
            state = None
            if self.live_ledger is not None:
                state = self.live_ledger.snapshot()
                state["per_order_budget"] = str(config.per_order_budget)
                state["max_positions"] = config.max_positions
            def save():
                saved = self.store.save_live_configuration(config.public(), revision, state)
                if state is not None:
                    self.live_ledger = LiveLedger.restore(state)
                    self.live.ledger = self.live_ledger
                self.live_config = config
                self.live.config = config
                self.live_config_revision = saved["revision"]
                return self.live_config_status()
            worker = asyncio.create_task(asyncio.to_thread(save))
            try:
                return await asyncio.shield(worker)
            except asyncio.CancelledError:
                await worker
                raise

    async def change_paper_config(self, config, revision):
        async with self.trading_modes.lock:
            if self.trading_modes.paper_enabled:raise ValueError("TURN_MODE_OFF_FIRST")
            if revision!=self.config_revision:raise ValueError("CONFIG_REVISION_CONFLICT")
            account=self.paper.account
            state=None
            if account:
                b=account.broker
                if self.paper.failure or account.failure:raise ValueError("ACCOUNT_FAILURE_REQUIRES_REVIEW")
                if any(p.quantity>0 for p in b.positions.values()) or any(o.state not in {"FILLED","CANCELED","EXPIRED"} for o in b.orders.values()):
                    raise ValueError("ACCOUNT_MUST_BE_FLAT")
                if config.initial_cash!=self.paper_config.initial_cash:raise ValueError("INITIAL_CASH_LOCKED")
                state=b.snapshot()
                state.update(per_order_budget=str(config.per_order_budget),max_positions=config.max_positions,
                             max_daily_loss=str(config.max_daily_loss),max_symbols=config.max_daily_symbols)
            def save():
                saved=self.store.save_paper_configuration(config.public(),revision,state)
                if account:
                    from app.execution import PaperBroker
                    account.broker=PaperBroker.restore(state)
                self.paper_config=config;self.paper.config=config;self.config_revision=saved["revision"]
                if account:self.paper.publish()
                else:self.paper.cached={**self.paper.cached,"configuration":config.public()}
                return self.config_status()
            worker=asyncio.create_task(asyncio.to_thread(save))
            try:return await asyncio.shield(worker)
            except asyncio.CancelledError:
                await worker
                raise

    async def change_mode(self, mode, revision):
        async with self.trading_modes.lock:
            worker = asyncio.create_task(asyncio.to_thread(self.trading_modes.change, mode, revision))
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                await worker
                if not self.trading_modes.paper_enabled:
                    self.paper.pending.clear()
                if not self.trading_modes.live_enabled:
                    self.live.pending.clear()
                raise
            if not self.trading_modes.paper_enabled:
                self.paper.pending.clear()
            if not self.trading_modes.live_enabled:
                self.live.pending.clear()
            return self.mode_status()

    async def paper_tick(self, context):
        async with self.trading_modes.lock:
            context = {**context,"healthy":context["healthy"] and self.trading_modes.paper_enabled}
            await self.paper.tick(context)

    async def paper_loop(self):
        while True:
            now=self.now_ms()
            self.paper_verified=await asyncio.to_thread(readiness,self.settings.data_dir,now)
            session=self.calendar.sessions.get(datetime.fromtimestamp(now/1000,NY).date())
            rules_ok=self.rules_verified and self.rules_checked_ms is not None and 0<=now-self.rules_checked_ms<=20*60000
            in_session=session is not None and session.open_ms<=now<session.close_ms
            directions={s:self.trading_state.direction(s,self.rules,now) for s in self.focus}
            status_ok=self.status_feeds_healthy()
            sell={s for s,d in directions.items() if d in {"BUY_SELL","SELL"}} if rules_ok and in_session and status_ok else set()
            buy={s for s,d in directions.items() if d in {"BUY_SELL","BUY"} and s in self.paper_verified["volume_symbols"] and not self.volume_evidence.failures[s]} if rules_ok and in_session and status_ok else set()
            rules={s:{**r,**({"tickSize":str(self.paper_verified["ticks"][s])} if s in self.paper_verified["ticks"] else {})} for s,r in self.rules.items()}
            await self.paper_tick({"now_ms":now,"session":session,"quotes":dict(self.quotes),"rules":rules,
                "fees":self.paper_verified["fees"],"fee_version":self.paper_verified["fee_version"],
                "buy_symbols":buy,"sell_symbols":sell,"max_exposure":self.paper_config.max_exposure,
                "healthy":not self.fatal and not self.writer.failure and all(f.connected and not f.data_gap for f in self.feeds)
                    and self.last_snapshot.get("disk_free_ratio",1)>=.25
                    and self.last_snapshot.get("processing",{}).get("p95_ms",0)<=100})
            await asyncio.sleep(.5)

    async def maintenance(self):
        next_metrics = 0
        while True:
            now = self.now_ms()
            self.outcomes.expire(now)
            self.recover_feed_continuity(now)
            local = datetime.fromtimestamp(now/1000, NY)
            if self.last_day != local.date():
                self.seen.clear()
                self.last_day = local.date()
            if now >= next_metrics:
                self.last_snapshot = self.metrics.snapshot(self.settings.data_dir)
                self.writer.submit_event("metrics", {"time_ms": now, **self.last_snapshot}, now)
                next_metrics = now+30000
            conditions = {"WS_DISCONNECTED": not all(f.connected for f in self.feeds),
                          "DISK_LOW": self.last_snapshot.get("disk_free_ratio",1)<.25,
                          "PROCESSING_LATENCY_HIGH": self.last_snapshot.get("processing",{}).get("p95_ms",0)>100,
                          "AUDIT_FAILURE": self.writer.failure is not None}
            session = self.calendar.sessions.get(local.date())
            if session and session.open_ms+30000 <= now < session.close_ms and time.monotonic()-self.metrics.started>30:
                conditions["RTH_QUOTES_STALE"] = any(
                    s not in self.quotes or self.quotes[s].source_ms is None or now-self.quotes[s].source_ms>2000
                    for s in self.focus)
            for code, active in conditions.items():
                self.alert_ticks[code] = self.alert_ticks[code]+1 if active else 0
                if self.alert_ticks[code] >= 3 and code not in self.alerted:
                    self.alert(code, {"consecutive_checks": self.alert_ticks[code]})
                    self.alerted.add(code)
                if not active:
                    self.alerted.discard(code)
            # Catch up the previous day on startup before the normal 16:15 report time.
            report_day = local.date() if local.time() >= dt_time(16,15) else local.date()-timedelta(days=1)
            try:
                if await asyncio.to_thread(self.store.report, report_day.isoformat()) is None:
                    await asyncio.to_thread(daily_report, self.store, self.settings.data_dir/"reports", report_day,
                                            self.calendar, self.status(), self.last_snapshot, now)
                backup = self.settings.data_dir/"backups"/f"{local.date()}.db"
                if not backup.exists():
                    await asyncio.to_thread(self.store.backup, backup)
                    await asyncio.to_thread(self.store.prune_metrics, now-90*86400000)
                self.alerted.discard("REPORT_OR_BACKUP_FAILED")
            except Exception as error:
                if "REPORT_OR_BACKUP_FAILED" not in self.alerted:
                    self.alert("REPORT_OR_BACKUP_FAILED", {"error_type": type(error).__name__})
                    self.alerted.add("REPORT_OR_BACKUP_FAILED")
            await asyncio.sleep(5)

    async def stop(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        try:
            if self.writer_task:
                await self.writer.stop(self.writer_task)
        finally:
            await asyncio.to_thread(self.store.close)
