"""Audited operator mode selection supporting parallel Paper + Live switches sharing one signal."""
import asyncio


class ModeConflict(ValueError):
    pass


class TradingModes:
    VALID_TARGETS = {"OFF", "PAPER", "LIVE", "BOTH", "PAPER_ON", "PAPER_OFF", "LIVE_ON", "LIVE_OFF"}

    def __init__(self, store, *, live_available=False):
        self.store = store
        self.live_available = bool(live_available)
        self.lock = asyncio.Lock()
        self.state = store.load_trading_mode() or {"mode": "PAPER", "revision": 0}
        if not self.live_available and self.state["mode"] in {"LIVE", "BOTH"}:
            fallback = "PAPER" if self.state["mode"] == "BOTH" else "OFF"
            self.state = store.save_trading_mode(fallback, self.state["revision"], "RESTART_REQUIRES_REARM")

    @property
    def paper_enabled(self) -> bool:
        return self.state["mode"] in {"PAPER", "BOTH"}

    @property
    def live_enabled(self) -> bool:
        return self.state["mode"] in {"LIVE", "BOTH"}

    def snapshot(self, live_blockers=()):
        base_blockers = [] if self.live_available else ["LIVE_EXECUTION_NOT_CONNECTED"]
        return {
            **self.state,
            "paper_enabled": self.paper_enabled,
            "live_enabled": self.live_enabled,
            "live_available": self.live_available,
            "shared_signal": True,
            "live_blockers": list(dict.fromkeys([*base_blockers, *live_blockers])),
            "off_behavior": "STOP_NEW_ENTRIES_KEEP_POSITION_PROTECTION",
        }

    def change(self, mode, revision):
        if mode not in self.VALID_TARGETS:
            raise ModeConflict("INVALID_MODE")
        if revision != self.state["revision"]:
            raise ModeConflict("MODE_REVISION_CONFLICT")
        if mode in {"LIVE", "BOTH", "LIVE_ON"} and not self.live_available:
            raise ModeConflict("LIVE_EXECUTION_NOT_CONNECTED")
        paper_on, live_on = self.paper_enabled, self.live_enabled
        if mode == "OFF":
            paper_on, live_on = False, False
        elif mode == "PAPER":
            paper_on, live_on = True, False
        elif mode == "LIVE":
            paper_on, live_on = False, True
        elif mode == "BOTH":
            paper_on, live_on = True, True
        elif mode == "PAPER_ON":
            paper_on = True
        elif mode == "PAPER_OFF":
            paper_on = False
        elif mode == "LIVE_ON":
            live_on = True
        elif mode == "LIVE_OFF":
            live_on = False
        resolved = "BOTH" if (paper_on and live_on) else ("PAPER" if paper_on else ("LIVE" if live_on else "OFF"))
        if resolved == self.state["mode"]:
            return
        self.state = self.store.save_trading_mode(resolved, revision, f"USER_REQUEST:{mode}")
