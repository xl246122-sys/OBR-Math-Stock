import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, time as dt_time

def run_symbol_backtest(symbol_path: Path):
    files = sorted(symbol_path.rglob("*.parquet"))
    if not files:
        return []
    df = pd.concat([pd.read_parquet(f) for f in files]).sort_values("timestamp_utc").reset_index(drop=True)
    df["dt_et"] = pd.to_datetime(df["timestamp_utc"]).dt.tz_convert("America/New_York")
    df["date_et"] = df["dt_et"].dt.date
    df["time_et"] = df["dt_et"].dt.time
    # regular trading hours 09:30 to 15:59
    df = df[(df["time_et"] >= dt_time(9, 30)) & (df["time_et"] <= dt_time(15, 59))].copy()
    
    symbol = symbol_path.name.replace("symbol=", "")
    days = sorted(df["date_et"].unique())
    
    # Store history for RVOL: progress_idx (0..77) -> list of cumulative volumes
    vol_history = {p: [] for p in range(78)}
    trades = []

    for day_idx, day in enumerate(days):
        day_df = df[df["date_et"] == day].sort_values("time_et").reset_index(drop=True)
        if len(day_df) < 390:
            continue
        
        # 1min bars to 78 5min bars
        bars_5m = []
        cum_v = 0
        for i in range(78):
            chunk = day_df.iloc[i*5 : (i+1)*5]
            o = chunk.iloc[0]["open"]
            h = chunk["high"].max()
            l = chunk["low"].min()
            c = chunk.iloc[-1]["close"]
            v = chunk["volume"].sum()
            cum_v += v
            # momentums
            m1 = (chunk.iloc[-1]["close"] - chunk.iloc[-2]["close"]) / chunk.iloc[-2]["close"] if len(chunk) >= 2 else 0.0
            m3 = (chunk.iloc[-1]["close"] - chunk.iloc[-4]["close"]) / chunk.iloc[-4]["close"] if len(chunk) >= 4 else 0.0
            m5 = (chunk.iloc[-1]["close"] - chunk.iloc[0]["open"]) / chunk.iloc[0]["open"]
            bars_5m.append({
                "bar_idx": i,
                "start_time": chunk.iloc[0]["time_et"],
                "end_time": chunk.iloc[-1]["time_et"],
                "open": o, "high": h, "low": l, "close": c, "volume": v,
                "cum_vol": cum_v,
                "mom_1m": m1, "mom_3m": m3, "mom_5m": m5,
                "1m_chunk": chunk
            })
            
        # Cold start check: need at least 10 historical days for RVOL
        can_trade = (day_idx >= 10)
        
        # ORB level: first 3 bars (09:30-09:45)
        orb_high = max(bars_5m[0]["high"], bars_5m[1]["high"], bars_5m[2]["high"])
        orb_low = min(bars_5m[0]["low"], bars_5m[1]["low"], bars_5m[2]["low"])
        
        entered_today = False
        
        for i in range(3, 73): # 09:45 to 15:35
            b = bars_5m[i]
            cur_cum_vol = b["cum_vol"]
            hist_vols = vol_history[i]
            
            if can_trade and not entered_today:
                if len(hist_vols) >= 10:
                    med_vol = np.median(hist_vols[-10:])
                    rvol = (cur_cum_vol / med_vol) if med_vol > 0 else 0.0
                else:
                    rvol = 0.0
                
                # Check ORB Breakout
                is_orb_breakout = (b["close"] > orb_high) and ((b["close"] - orb_high) / orb_high <= 0.015)
                # Check Intraday Continuation
                is_cont = False
                if not is_orb_breakout and i >= 6:
                    past3 = bars_5m[i-3:i]
                    cont_high = max(p["high"] for p in past3)
                    cont_low = min(p["low"] for p in past3)
                    width = (cont_high - cont_low) / cont_high
                    trend = past3[0]["close"] > bars_5m[i-6]["close"]
                    if b["close"] > cont_high and width <= 0.008 and trend:
                        is_cont = True
                
                mom_ok = (b["mom_1m"] > 0 and b["mom_3m"] > 0 and b["mom_5m"] > 0)
                
                if (is_orb_breakout or is_cont) and rvol >= 1.5 and mom_ok:
                    # ENTER TRADE
                    entry_price = float(b["close"])
                    entry_time = b["end_time"]
                    entry_bar_idx = i
                    signal_type = "ORB" if is_orb_breakout else "CONTINUATION"
                    
                    budget = 300.0
                    fee_rate = 0.001
                    min_fee = 0.10
                    fee_buy = max(min_fee, budget * fee_rate)
                    qty = budget / entry_price
                    total_invested = budget + fee_buy
                    
                    # Target prices for net returns
                    # Net PnL = (qty * P_exit - fee_sell) - total_invested
                    # Net Return = Net PnL / total_invested
                    # For +1.75%: P_exit >= (total_invested * 1.0175 + fee_sell) / qty
                    p_tp = (total_invested * 1.0175 + min_fee) / qty
                    p_sl = (total_invested * (1.0 - 0.0080) + min_fee) / qty
                    
                    # Track through subsequent 1m bars from (i+1)*5 onwards
                    remaining_1m = day_df.iloc[(i+1)*5 : ].reset_index(drop=True)
                    exit_reason = "SESSION_EXIT"
                    exit_price = float(remaining_1m.iloc[-1]["close"]) if len(remaining_1m) else entry_price
                    exit_time = remaining_1m.iloc[-1]["time_et"] if len(remaining_1m) else entry_time
                    
                    for r_idx, r_row in remaining_1m.iterrows():
                        cur_t = r_row["time_et"]
                        h_1m = float(r_row["high"])
                        l_1m = float(r_row["low"])
                        c_1m = float(r_row["close"])
                        
                        # Check TP
                        if h_1m >= p_tp:
                            exit_reason = "TAKE_PROFIT"
                            exit_price = p_tp
                            exit_time = cur_t
                            break
                        # Check SL
                        if l_1m <= p_sl:
                            exit_reason = "STOP_LOSS"
                            exit_price = p_sl
                            exit_time = cur_t
                            break
                        # 15:55 Session Exit
                        if cur_t >= dt_time(15, 55):
                            exit_reason = "SESSION_EXIT"
                            exit_price = c_1m
                            exit_time = cur_t
                            break
                            
                    gross_return = (exit_price - entry_price) / entry_price
                    fee_sell = max(min_fee, qty * exit_price * fee_rate)
                    net_pnl = (qty * exit_price - fee_sell) - total_invested
                    net_return = net_pnl / total_invested
                    
                    trades.append({
                        "symbol": symbol,
                        "date": str(day),
                        "signal_type": signal_type,
                        "entry_time": str(entry_time),
                        "entry_price": round(entry_price, 4),
                        "exit_time": str(exit_time),
                        "exit_price": round(exit_price, 4),
                        "exit_reason": exit_reason,
                        "rvol": round(rvol, 2),
                        "gross_return": round(gross_return * 100, 3),
                        "net_return": round(net_return * 100, 3),
                        "net_pnl": round(net_pnl, 2),
                        "fees": round(fee_buy + fee_sell, 2)
                    })
                    entered_today = True

        # Update volume history after day completes
        for i in range(78):
            vol_history[i].append(bars_5m[i]["cum_vol"])
            
    return trades

if __name__ == "__main__":
    t_nvda = run_symbol_backtest(Path(r"D:\AlpacaData\data_strategy\1min\feed=sip\symbol=NVDA"))
    print("NVDA Trades:", len(t_nvda))
    if t_nvda:
        print(pd.DataFrame(t_nvda).head(5))
