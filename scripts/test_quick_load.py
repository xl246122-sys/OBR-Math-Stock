import os
import sys
import time
from pathlib import Path
from decimal import Decimal
import pandas as pd
import numpy as np
from datetime import datetime, time as dt_time

# Quick test on 5 symbols
ROOT = Path(r"D:\AlpacaData\data_strategy\1min\feed=sip")
symbols = ["NVDA", "AAPL", "MSFT", "AVGO", "AMD"]

for sym in symbols:
    p = ROOT / f"symbol={sym}"
    files = sorted(p.rglob("*.parquet"))
    if not files:
        print(f"No files for {sym}")
        continue
    df = pd.concat([pd.read_parquet(f) for f in files]).sort_values("timestamp_utc").reset_index(drop=True)
    df["dt_et"] = pd.to_datetime(df["timestamp_utc"]).dt.tz_convert("America/New_York")
    df["date_et"] = df["dt_et"].dt.date
    df["time_et"] = df["dt_et"].dt.time
    # filter 09:30 to 15:59
    df = df[(df["time_et"] >= dt_time(9, 30)) & (df["time_et"] <= dt_time(15, 59))].copy()
    days = sorted(df["date_et"].unique())
    print(f"Symbol {sym}: {len(df)} 1m bars across {len(days)} trading days ({days[0]} to {days[-1]})")
