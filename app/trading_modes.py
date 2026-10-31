"""Audited, mutually exclusive operator mode selection.

Live is deliberately unavailable until a verified exchange execution adapter and
account reconciliation are present. Selecting a label never creates a live trade.
"""
import asyncio


class ModeConflict(ValueError):
    pass


class TradingModes:
    def __init__(self, store):
        self.store = store
        self.lock = asyncio.Lock()
        self.state = store.load_trading_mode() or {"mode": "PAPER", "revision": 0}
        if self.state["mode"] == "LIVE":
            # Never automatically re-arm a real account after a process restart.
            self.state = store.save_trading_mode("OFF", self.state["revision"], "RESTART_REQUIRES_REARM")

    def snapshot(self, live_blockers=()):
        return {**self.state, "paper_enabled": self.state["mode"] == "PAPER",
                "live_enabled": self.state["mode"] == "LIVE",
                "live_available": False,
                "live_blockers": list(dict.fromkeys(["LIVE_EXECUTION_NOT_CONNECTED", *live_blockers])),
                "off_behavior": "STOP_NEW_ENTRIES_KEEP_POSITION_PROTECTION"}

    def change(self, mode, revision):
        if mode not in {"OFF", "PAPER", "LIVE"}:
            raise ModeConflict("INVALID_MODE")
        if revision != self.state["revision"]:
            raise ModeConflict("MODE_REVISION_CONFLICT")
        if mode == "LIVE":
            raise ModeConflict("LIVE_EXECUTION_NOT_CONNECTED")
        if mode == self.state["mode"]:
            return
        self.state = self.store.save_trading_mode(mode, revision, "USER_REQUEST")
