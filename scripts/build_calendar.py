"""Development-time export; pandas is not installed on the production server."""
from datetime import date, timedelta
import json
from pathlib import Path
import exchange_calendars as xc

calendar = xc.get_calendar("XNYS", start="2026-01-01", end="2027-12-31")
sessions = [{"day": str(index.date()), "open_ms": int(row["open"].timestamp()*1000),
             "close_ms": int(row["close"].timestamp()*1000)} for index, row in calendar.schedule.iterrows()]
known = {row["day"] for row in sessions}
day, closed = date(2026,1,1), []
while day <= date(2027,12,31):
    if day.isoformat() not in known:
        closed.append(day.isoformat())
    day += timedelta(days=1)
data = {"source": f"exchange_calendars {xc.__version__} XNYS; scheduled calendar, not halt authority",
        "reference": "https://www.nyse.com/markets/hours-calendars",
        "generated_for": "2026-2027", "sessions": sessions, "closed_days": closed}
path = Path("data/calendar.json")
path.parent.mkdir(exist_ok=True)
path.write_text(json.dumps(data, indent=2), encoding="utf-8")
print("Exported sessions:", len(sessions))
