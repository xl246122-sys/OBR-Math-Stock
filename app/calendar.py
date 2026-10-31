"""Explicit, externally verified sessions; unknown dates fail closed."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
import json

NY = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Session:
    day: date
    open_ms: int
    close_ms: int
    source: str

    @classmethod
    def from_verified_hours(cls, day, close=time(16), source=""):
        if not source:
            raise ValueError("CALENDAR_SOURCE_REQUIRED")
        opening = datetime.combine(day, time(9, 30), NY)
        closing = datetime.combine(day, close, NY)
        if closing <= opening:
            raise ValueError("INVALID_SESSION")
        return cls(day, int(opening.timestamp()*1000), int(closing.timestamp()*1000), source)

    def can_enter(self, now_ms):
        return self.open_ms + 300000 <= now_ms < self.close_ms - 20*60000

    def should_exit(self, now_ms):
        return now_ms >= self.close_ms - 5*60000


class Calendar:
    def __init__(self, sessions=(), closed_days=()):
        self.sessions = {s.day: s for s in sessions}
        self.closed_days = frozenset(closed_days)
        if self.closed_days.intersection(self.sessions):
            raise ValueError("CONFLICTING_CALENDAR")

    def status(self, day):
        if day in self.sessions:
            return "VERIFIED_SESSION"
        if day in self.closed_days:
            return "MARKET_CLOSED"
        return "CALENDAR_UNKNOWN"

    @classmethod
    def load(cls, path):
        data = json.loads(path.read_text(encoding="utf-8"))
        sessions = [Session(date.fromisoformat(row["day"]), row["open_ms"], row["close_ms"], data["source"])
                    for row in data["sessions"]]
        return cls(sessions, [date.fromisoformat(d) for d in data["closed_days"]])
