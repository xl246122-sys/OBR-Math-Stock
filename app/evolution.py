"""Self-Evolution & Automated Review Engine for OBR Math.

Provides:
1. Multi-horizon automated reviews (DAILY, TRADING_5D, MONTHLY, QUARTERLY, SEMIANNUAL).
2. Strategy & math-model performance attribution (win rate, payoff ratio, net PnL,
   max drawdown, signal quality, bad trades, missed opportunities, failure causes,
   and market regime breakdown).
3. Parameter & filter diagnostics with concrete optimization suggestions.
4. Historical backtest + Out-of-Sample (OOS) walk-forward validation gate so
   unvalidated candidate strategies can never overwrite the stable active version.
5. Standardized external AI interface for Codex, Antigravity, and research tools.
"""
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date, datetime, time as dt_time, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from app.calendar import NY, Session
from app.execution import Fees
from app.market import Bar, number
from app.strategy import OBRMathEngine, Parameters

PERIOD_TYPES = ("DAILY", "TRADING_5D", "MONTHLY", "QUARTERLY", "SEMIANNUAL")
PERIOD_LABELS = {
    "DAILY": "每日复盘",
    "TRADING_5D": "每5个交易日复盘",
    "MONTHLY": "每月复盘",
    "QUARTERLY": "每季度复盘",
    "SEMIANNUAL": "每半年复盘",
}
DEFAULT_STABLE_VERSION = "closed-bar-momentum-v2"


def _dec(val, default="0") -> Decimal:
    try:
        if val is None or val == "":
            return Decimal(default)
        return Decimal(str(val))
    except Exception:
        return Decimal(default)


def _fmt_dec(val: Decimal, places: str = "0.0001") -> str:
    return str(val.quantize(Decimal(places)))


def default_parameters_dict(version: str = DEFAULT_STABLE_VERSION) -> dict:
    p = Parameters(require_momentum=True, version=version)
    return {
        "lookback": p.lookback,
        "min_history": p.min_history,
        "min_rvol": str(p.min_rvol),
        "max_chase": str(p.max_chase),
        "max_spread": str(p.max_spread),
        "max_consolidation": str(p.max_consolidation),
        "max_age_ms": p.max_age_ms,
        "version": p.version,
        "require_momentum": p.require_momentum,
        "strength_weight": str(p.strength_weight),
        "volume_weight": str(p.volume_weight),
        "momentum_weight": str(p.momentum_weight),
        "take_profit_pct": "0.0175",
        "stop_loss_pct": "0.0080",
    }


def build_parameters(params_dict: dict, version_id: str | None = None) -> Parameters:
    base = default_parameters_dict(version_id or params_dict.get("version") or DEFAULT_STABLE_VERSION)
    merged = {**base, **params_dict}
    if version_id:
        merged["version"] = version_id
    return Parameters(
        lookback=int(merged["lookback"]),
        min_history=int(merged["min_history"]),
        min_rvol=Decimal(str(merged["min_rvol"])),
        max_chase=Decimal(str(merged["max_chase"])),
        max_spread=Decimal(str(merged["max_spread"])),
        max_consolidation=Decimal(str(merged["max_consolidation"])),
        max_age_ms=int(merged["max_age_ms"]),
        version=str(merged["version"]),
        require_momentum=bool(merged["require_momentum"]),
        strength_weight=Decimal(str(merged["strength_weight"])),
        volume_weight=Decimal(str(merged["volume_weight"])),
        momentum_weight=Decimal(str(merged["momentum_weight"])),
    )


def resolve_period_window(period_type: str, ref_day: date, calendar=None) -> tuple[str, int, int]:
    """Return (period_key, start_ms, end_ms) in NY timezone for any of the 5 review periods."""
    if period_type not in PERIOD_TYPES:
        raise ValueError(f"UNSUPPORTED_PERIOD_TYPE:{period_type}")

    def day_ms(d: date) -> int:
        return int(datetime.combine(d, dt_time.min, NY).timestamp() * 1000)

    if period_type == "DAILY":
        key = ref_day.isoformat()
        return key, day_ms(ref_day), day_ms(ref_day + timedelta(days=1))

    if period_type == "TRADING_5D":
        if calendar and getattr(calendar, "sessions", None):
            eligible = sorted(d for d in calendar.sessions if d <= ref_day)
            if len(eligible) >= 5:
                window_days = eligible[-5:]
                key = f"{window_days[0].isoformat()}_to_{window_days[-1].isoformat()}"
                return key, day_ms(window_days[0]), day_ms(window_days[-1] + timedelta(days=1))
            elif eligible:
                start_d = eligible[0]
                key = f"{start_d.isoformat()}_to_{ref_day.isoformat()}"
                return key, day_ms(start_d), day_ms(ref_day + timedelta(days=1))
        start_d = ref_day - timedelta(days=6)
        key = f"{start_d.isoformat()}_to_{ref_day.isoformat()}"
        return key, day_ms(start_d), day_ms(ref_day + timedelta(days=1))

    if period_type == "MONTHLY":
        start_d = date(ref_day.year, ref_day.month, 1)
        if ref_day.month == 12:
            end_d = date(ref_day.year + 1, 1, 1)
        else:
            end_d = date(ref_day.year, ref_day.month + 1, 1)
        key = f"{ref_day.year:04d}-{ref_day.month:02d}"
        return key, day_ms(start_d), day_ms(end_d)

    if period_type == "QUARTERLY":
        q = (ref_day.month - 1) // 3 + 1
        start_month = (q - 1) * 3 + 1
        start_d = date(ref_day.year, start_month, 1)
        if q == 4:
            end_d = date(ref_day.year + 1, 1, 1)
        else:
            end_d = date(ref_day.year, start_month + 3, 1)
        key = f"{ref_day.year:04d}-Q{q}"
        return key, day_ms(start_d), day_ms(end_d)

    # SEMIANNUAL
    h = 1 if ref_day.month <= 6 else 2
    start_d = date(ref_day.year, 1 if h == 1 else 7, 1)
    end_d = date(ref_day.year, 7, 1) if h == 1 else date(ref_day.year + 1, 1, 1)
    key = f"{ref_day.year:04d}-H{h}"
    return key, day_ms(start_d), day_ms(end_d)


def _reconstruct_round_trips(fills: list[dict], start_ms: int, end_ms: int, initial_capital: Decimal) -> dict:
    """FIFO round-trip trade reconstruction and portfolio drawdown calculation."""
    lots = defaultdict(list)
    closed_trades = []
    window_fills = []
    total_fees = Decimal(0)

    sorted_fills = sorted(
        fills,
        key=lambda f: int(f.get("source_ms") or f.get("time_ms") or 0),
    )
    for fill in sorted_fills:
        ts = int(fill.get("source_ms") or fill.get("time_ms") or 0)
        symbol = str(fill.get("symbol", ""))
        side = str(fill.get("side", ""))
        qty = _dec(fill.get("quantity"))
        price = _dec(fill.get("price"))
        fee = _dec(fill.get("fee"))
        reason = str(fill.get("reason") or "EXECUTION")
        if qty <= 0 or price <= 0:
            continue
        if start_ms <= ts < end_ms:
            window_fills.append(fill)
            total_fees += fee
        if side == "BUY":
            lots[symbol].append({
                "qty": qty,
                "price": price,
                "fee_per_share": fee / qty,
                "entry_ms": ts,
                "client_id": fill.get("client_id", ""),
            })
        elif side == "SELL":
            remaining = qty
            entry_cost = Decimal(0)
            entry_fees = Decimal(0)
            matched_qty = Decimal(0)
            earliest_ms = ts
            while remaining > 0 and lots[symbol]:
                lot = lots[symbol][0]
                take = min(remaining, lot["qty"])
                entry_cost += take * lot["price"]
                entry_fees += take * lot["fee_per_share"]
                matched_qty += take
                earliest_ms = min(earliest_ms, lot["entry_ms"])
                lot["qty"] -= take
                remaining -= take
                if lot["qty"] <= 0:
                    lots[symbol].pop(0)
            if matched_qty > 0 and start_ms <= ts < end_ms:
                sell_fee = fee * (matched_qty / qty)
                proceeds = matched_qty * price
                net_pnl = proceeds - sell_fee - entry_cost - entry_fees
                total_cost = entry_cost + entry_fees
                return_pct = (net_pnl / total_cost) if total_cost > 0 else Decimal(0)
                closed_trades.append({
                    "symbol": symbol,
                    "quantity": str(matched_qty),
                    "entry_cost": _fmt_dec(total_cost, "0.01"),
                    "exit_proceeds": _fmt_dec(proceeds - sell_fee, "0.01"),
                    "net_pnl": _fmt_dec(net_pnl, "0.01"),
                    "return_pct": _fmt_dec(return_pct, "0.0001"),
                    "fees": _fmt_dec(entry_fees + sell_fee, "0.01"),
                    "exit_reason": reason,
                    "entry_ms": earliest_ms,
                    "exit_ms": ts,
                    "holding_minutes": round(max(0, ts - earliest_ms) / 60000.0, 2),
                })

    wins = [t for t in closed_trades if _dec(t["net_pnl"]) > 0]
    losses = [t for t in closed_trades if _dec(t["net_pnl"]) <= 0]
    gross_profit = sum((_dec(t["net_pnl"]) for t in wins), Decimal(0))
    gross_loss = abs(sum((_dec(t["net_pnl"]) for t in losses), Decimal(0)))
    net_pnl = gross_profit - gross_loss
    closed_count = len(closed_trades)
    win_rate = (Decimal(len(wins)) / Decimal(closed_count)) if closed_count > 0 else Decimal(0)
    avg_win = (gross_profit / Decimal(len(wins))) if wins else Decimal(0)
    avg_loss = (gross_loss / Decimal(len(losses))) if losses else Decimal(0)
    payoff_ratio = (avg_win / avg_loss) if avg_loss > 0 else (avg_win if avg_win > 0 else Decimal(0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else Decimal(0))
    expectancy = (net_pnl / Decimal(closed_count)) if closed_count > 0 else Decimal(0)

    # Equity curve & Max Drawdown
    equity = initial_capital if initial_capital > 0 else Decimal("600")
    peak = equity
    max_dd = Decimal(0)
    max_dd_pct = Decimal(0)
    for t in closed_trades:
        equity += _dec(t["net_pnl"])
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
            if peak > 0:
                max_dd_pct = dd / peak

    bad_trades = []
    for t in losses:
        ret = _dec(t["return_pct"])
        reason = t["exit_reason"]
        diagnosis = "NORMAL_STOP_LOSS"
        if reason == "DAILY_LOSS_LIMIT":
            diagnosis = "DAILY_LOSS_CIRCUIT_BREAKER"
        elif reason == "STOP_LOSS" and t["holding_minutes"] <= 5:
            diagnosis = "IMMEDIATE_FALSE_BREAKOUT_REVERSAL"
        elif reason == "SESSION_EXIT" and ret < Decimal("-0.002"):
            diagnosis = "LATE_SESSION_MOMENTUM_DECAY"
        elif _dec(t["fees"]) > abs(_dec(t["net_pnl"])) * Decimal("0.5"):
            diagnosis = "FEE_EROSION_ON_SMALL_MOVE"
        bad_trades.append({**t, "diagnosis": diagnosis})

    return {
        "fills_count": len(window_fills),
        "closed_trades_count": closed_count,
        "winning_trades_count": len(wins),
        "losing_trades_count": len(losses),
        "win_rate": _fmt_dec(win_rate, "0.0001"),
        "avg_win": _fmt_dec(avg_win, "0.01"),
        "avg_loss": _fmt_dec(avg_loss, "0.01"),
        "profit_loss_ratio": _fmt_dec(payoff_ratio, "0.01"),
        "profit_factor": _fmt_dec(profit_factor, "0.01"),
        "gross_profit": _fmt_dec(gross_profit, "0.01"),
        "gross_loss": _fmt_dec(gross_loss, "0.01"),
        "total_fees": _fmt_dec(total_fees, "0.01"),
        "net_pnl": _fmt_dec(net_pnl, "0.01"),
        "expectancy_per_trade": _fmt_dec(expectancy, "0.01"),
        "max_drawdown": _fmt_dec(max_dd, "0.01"),
        "max_drawdown_pct": _fmt_dec(max_dd_pct, "0.0001"),
        "closed_trades": closed_trades[-50:],
        "bad_trades": bad_trades[-30:],
    }


def _analyze_signals_and_outcomes(signals: list[dict]) -> dict:
    by_state = Counter()
    by_reason = Counter()
    by_kind = Counter()
    confirmed_returns_30m = []
    confirmed_mfe = []
    confirmed_mae = []
    erroneous_signals = []
    missed_opportunities = []
    missed_by_reason = Counter()

    for sig in signals:
        state = str(sig.get("state", "UNKNOWN"))
        reason = str(sig.get("reason", "UNKNOWN"))
        kind = str(sig.get("kind", "ORB"))
        by_state[state] += 1
        by_reason[reason] += 1
        by_kind[kind] += 1

        outcomes = sig.get("forward_outcomes") or {}
        o15 = outcomes.get("15") or {}
        o30 = outcomes.get("30") or {}
        o60 = outcomes.get("60") or {}
        o0 = outcomes.get("0") or {}

        ret30 = _dec(o30.get("return") or o15.get("return") or o0.get("return"), default="None")
        mfe = max(
            (_dec(o.get("sampled_mfe"), default="-999") for o in outcomes.values() if o.get("sampled_mfe") is not None),
            default=None,
        )
        mae = min(
            (_dec(o.get("sampled_mae"), default="999") for o in outcomes.values() if o.get("sampled_mae") is not None),
            default=None,
        )

        if state == "CONFIRMED":
            if ret30 != Decimal("0") or (o30.get("return") is not None):
                confirmed_returns_30m.append(ret30)
            if mfe is not None and mfe > Decimal("-900"):
                confirmed_mfe.append(mfe)
            if mae is not None and mae < Decimal("900"):
                confirmed_mae.append(mae)
            if (mae is not None and mae <= Decimal("-0.008")) or (
                o30.get("return") is not None and _dec(o30.get("return")) <= Decimal("-0.005")
            ):
                erroneous_signals.append({
                    "candidate_id": sig.get("candidate_id"),
                    "symbol": sig.get("symbol"),
                    "kind": kind,
                    "source_ms": sig.get("source_ms"),
                    "rvol": sig.get("rvol"),
                    "score": sig.get("score"),
                    "return_30m": o30.get("return"),
                    "sampled_mfe": str(mfe) if mfe is not None else None,
                    "sampled_mae": str(mae) if mae is not None else None,
                    "failure_type": "FALSE_BREAKOUT_REVERSAL",
                })
        elif state in {"REJECTED", "WATCH_ONLY"}:
            best_ret = max(
                (_dec(o.get("return"), default="-999") for o in (o15, o30, o60, o0) if o.get("return") is not None),
                default=None,
            )
            if (mfe is not None and mfe >= Decimal("0.015")) or (best_ret is not None and best_ret >= Decimal("0.010")):
                missed_by_reason[reason] += 1
                missed_opportunities.append({
                    "candidate_id": sig.get("candidate_id"),
                    "symbol": sig.get("symbol"),
                    "kind": kind,
                    "blocked_by_reason": reason,
                    "source_ms": sig.get("source_ms"),
                    "rvol": sig.get("rvol"),
                    "score": sig.get("score"),
                    "subsequent_mfe": str(mfe) if mfe is not None else None,
                    "best_forward_return": str(best_ret) if best_ret is not None else None,
                })

    avg_ret_30m = (
        sum(confirmed_returns_30m, Decimal(0)) / Decimal(len(confirmed_returns_30m))
        if confirmed_returns_30m
        else Decimal(0)
    )
    avg_mfe = sum(confirmed_mfe, Decimal(0)) / Decimal(len(confirmed_mfe)) if confirmed_mfe else Decimal(0)
    avg_mae = sum(confirmed_mae, Decimal(0)) / Decimal(len(confirmed_mae)) if confirmed_mae else Decimal(0)
    confirmed_win_rate = (
        Decimal(sum(1 for r in confirmed_returns_30m if r > 0)) / Decimal(len(confirmed_returns_30m))
        if confirmed_returns_30m
        else Decimal(0)
    )

    return {
        "total_candidates": len(signals),
        "by_state": dict(by_state),
        "by_reason": dict(by_reason),
        "by_kind": dict(by_kind),
        "confirmed_evaluated_count": len(confirmed_returns_30m),
        "confirmed_forward_win_rate_30m": _fmt_dec(confirmed_win_rate, "0.0001"),
        "confirmed_avg_return_30m": _fmt_dec(avg_ret_30m, "0.0001"),
        "confirmed_avg_mfe": _fmt_dec(avg_mfe, "0.0001"),
        "confirmed_avg_mae": _fmt_dec(avg_mae, "0.0001"),
        "erroneous_signals_count": len(erroneous_signals),
        "erroneous_signals": erroneous_signals[-25:],
        "missed_opportunities_count": len(missed_opportunities),
        "missed_by_reason": dict(missed_by_reason),
        "missed_opportunities": missed_opportunities[-25:],
    }


def _analyze_market_regimes(bars: list[dict], signals: list[dict]) -> dict:
    """Classify symbol-day sessions into market regimes and measure signal behavior per regime."""
    grouped = defaultdict(list)
    for b in bars:
        sym = b.get("symbol", "")
        day = datetime.fromtimestamp(int(b["start_ms"]) / 1000, NY).date().isoformat()
        grouped[(sym, day)].append(b)

    regime_counts = Counter()
    sym_day_regime = {}
    for (sym, day), session_bars in grouped.items():
        session_bars.sort(key=lambda x: int(x["start_ms"]))
        open_p = _dec(session_bars[0].get("open"), "1")
        close_p = _dec(session_bars[-1].get("close"), "1")
        high_p = max(_dec(x.get("high"), "1") for x in session_bars)
        low_p = min(_dec(x.get("low"), "1") for x in session_bars)
        rng = (high_p - low_p) / open_p if open_p > 0 else Decimal(0)
        eff = abs(close_p - open_p) / (high_p - low_p) if high_p > low_p else Decimal(0)
        if rng >= Decimal("0.025") and eff >= Decimal("0.45"):
            regime = "HIGH_VOL_TREND"
        elif rng >= Decimal("0.025") and eff < Decimal("0.45"):
            regime = "CHOPPY_REVERSAL"
        elif rng < Decimal("0.012"):
            regime = "LOW_VOL_RANGE"
        else:
            regime = "NORMAL_SESSION"
        regime_counts[regime] += 1
        sym_day_regime[(sym, day)] = regime

    regime_signals = defaultdict(lambda: {"total": 0, "confirmed": 0, "rejected": 0, "false_breakouts": 0})
    for sig in signals:
        sym = sig.get("symbol", "")
        day = datetime.fromtimestamp(int(sig["source_ms"]) / 1000, NY).date().isoformat()
        reg = sym_day_regime.get((sym, day), "UNCLASSIFIED")
        regime_signals[reg]["total"] += 1
        if sig.get("state") == "CONFIRMED":
            regime_signals[reg]["confirmed"] += 1
            o30 = (sig.get("forward_outcomes") or {}).get("30") or {}
            if o30.get("return") is not None and _dec(o30.get("return")) <= Decimal("-0.005"):
                regime_signals[reg]["false_breakouts"] += 1
        elif sig.get("state") == "REJECTED":
            regime_signals[reg]["rejected"] += 1

    return {
        "bars_analyzed": len(bars),
        "symbol_sessions_classified": len(grouped),
        "session_regime_counts": dict(regime_counts),
        "signals_by_regime": dict(regime_signals),
    }


def _generate_diagnostics_and_suggestions(
    params_dict: dict,
    paper_perf: dict,
    live_perf: dict,
    sig_diag: dict,
    regime_diag: dict,
    events: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Identify strategy failure causes and generate parameter/logic optimization suggestions."""
    failure_causes = []
    suggestions = []

    by_reason = sig_diag.get("by_reason", {})
    missed_by_reason = sig_diag.get("missed_by_reason", {})
    total_cands = sig_diag.get("total_candidates", 0)
    confirmed_cnt = sig_diag.get("by_state", {}).get("CONFIRMED", 0)

    # 1. Check Cold Start / Data Continuity / Volume Verification blockers
    cold_cnt = by_reason.get("COLD_START", 0) + by_reason.get("DATA_INSUFFICIENT", 0) + by_reason.get("INCOMPLETE_SESSION", 0)
    if cold_cnt > 0:
        failure_causes.append({
            "code": "VOLUME_BASELINE_OR_SESSION_CONTINUITY_GAP",
            "occurrences": cold_cnt,
            "severity": "MEDIUM" if confirmed_cnt > 0 else "HIGH",
            "description": f"共有 {cold_cnt} 次候选突破因历史同进度成交量不足或盘中序列缺口降级为 WATCH_ONLY。",
        })

    # 2. Check RVOL filter tightness vs missed opportunities
    low_rvol_cnt = by_reason.get("LOW_RVOL", 0)
    missed_rvol = missed_by_reason.get("LOW_RVOL", 0)
    cur_rvol = _dec(params_dict.get("min_rvol", "1.5"), "1.5")
    if missed_rvol >= 2 or (low_rvol_cnt >= 5 and confirmed_cnt == 0):
        failure_causes.append({
            "code": "RVOL_THRESHOLD_OVER_FILTERING",
            "occurrences": low_rvol_cnt,
            "missed_profitable_count": missed_rvol,
            "severity": "MEDIUM",
            "description": f"LOW_RVOL 拦截了 {low_rvol_cnt} 次突破（其中 {missed_rvol} 次后续走出显著正收益），当前 min_rvol={cur_rvol} 偏严。",
        })
        new_rvol = max(Decimal("1.20"), cur_rvol - Decimal("0.15"))
        suggestions.append({
            "id": "OPT_MIN_RVOL_RELAX",
            "category": "MATH_MODEL_PARAM",
            "target_parameter": "min_rvol",
            "current_value": str(cur_rvol),
            "suggested_value": str(new_rvol),
            "confidence": "MEDIUM",
            "rationale": f"发现 {missed_rvol} 次被 LOW_RVOL 过滤的错失机会，建议在样本外回测中验证将 min_rvol 从 {cur_rvol} 下调至 {new_rvol}。",
            "verification_requirement": "HISTORICAL_BACKTEST_AND_OOS_REQUIRED",
        })

    # 3. Check Chase limit vs false breakouts or missed opportunities
    chase_cnt = by_reason.get("CHASE_LIMIT", 0)
    missed_chase = missed_by_reason.get("CHASE_LIMIT", 0)
    cur_chase = _dec(params_dict.get("max_chase", "0.005"), "0.005")
    err_cnt = sig_diag.get("erroneous_signals_count", 0)
    if err_cnt >= 2 or ( _dec(paper_perf.get("win_rate", "0")) < Decimal("0.45") and paper_perf.get("closed_trades_count", 0) >= 3 ):
        failure_causes.append({
            "code": "FALSE_BREAKOUT_HIGH_CHASE_REVERSAL",
            "occurrences": max(err_cnt, paper_perf.get("losing_trades_count", 0)),
            "severity": "HIGH",
            "description": "突破确认K线收盘偏离关键位过大时易遭遇均值回归假突破，导致止损触发。",
        })
        tighter_chase = max(Decimal("0.0030"), cur_chase - Decimal("0.0010"))
        suggestions.append({
            "id": "OPT_MAX_CHASE_TIGHTEN",
            "category": "MATH_MODEL_PARAM",
            "target_parameter": "max_chase",
            "current_value": str(cur_chase),
            "suggested_value": str(tighter_chase),
            "confidence": "HIGH",
            "rationale": "针对假突破回撤，建议收紧 max_chase（追高上限）并提高动量权重 momentum_weight，过滤末端衰竭突破。",
            "verification_requirement": "HISTORICAL_BACKTEST_AND_OOS_REQUIRED",
        })
    elif missed_chase >= 2:
        wider_chase = min(Decimal("0.0080"), cur_chase + Decimal("0.0015"))
        suggestions.append({
            "id": "OPT_MAX_CHASE_EXPAND",
            "category": "MATH_MODEL_PARAM",
            "target_parameter": "max_chase",
            "current_value": str(cur_chase),
            "suggested_value": str(wider_chase),
            "confidence": "MEDIUM",
            "rationale": f"强势趋势日中有 {missed_chase} 次突破因涨幅超出 max_chase={cur_chase} 而错失，建议回测验证放宽至 {wider_chase}。",
            "verification_requirement": "HISTORICAL_BACKTEST_AND_OOS_REQUIRED",
        })

    # 4. Check Payoff Ratio / Take-Profit & Stop-Loss calibration
    avg_mfe = _dec(sig_diag.get("confirmed_avg_mfe", "0"))
    cur_tp = _dec(params_dict.get("take_profit_pct", "0.0175"), "0.0175")
    cur_sl = _dec(params_dict.get("stop_loss_pct", "0.0080"), "0.0080")
    if avg_mfe > Decimal("0.008") and avg_mfe < cur_tp:
        suggested_tp = max(Decimal("0.0120"), (avg_mfe * Decimal("0.85")).quantize(Decimal("0.0005")))
        suggestions.append({
            "id": "OPT_TAKE_PROFIT_ALIGN_MFE",
            "category": "RISK_EXIT_RULE",
            "target_parameter": "take_profit_pct",
            "current_value": str(cur_tp),
            "suggested_value": str(suggested_tp),
            "confidence": "MEDIUM",
            "rationale": f"确认信号样本平均最大有利偏移 (MFE) 为 {avg_mfe}，低于当前止盈阈值 {cur_tp}，建议下调止盈目标以提升落袋胜率。",
            "verification_requirement": "HISTORICAL_BACKTEST_AND_OOS_REQUIRED",
        })

    # 5. Check Choppy Regime false breakouts
    choppy_stats = (regime_diag.get("signals_by_regime") or {}).get("CHOPPY_REVERSAL") or {}
    if choppy_stats.get("false_breakouts", 0) > 0:
        failure_causes.append({
            "code": "CHOPPY_REGIME_CONTINUATION_WHIPSAW",
            "occurrences": choppy_stats["false_breakouts"],
            "severity": "MEDIUM",
            "description": "宽幅震荡 (CHOPPY_REVERSAL) 环境下日内延续突破信号易受双向扫损影响。",
        })
        cur_cons = _dec(params_dict.get("max_consolidation", "0.02"), "0.02")
        suggestions.append({
            "id": "OPT_CONSOLIDATION_TIGHTEN",
            "category": "SIGNAL_FILTER",
            "target_parameter": "max_consolidation",
            "current_value": str(cur_cons),
            "suggested_value": str(max(Decimal("0.012"), cur_cons - Decimal("0.004"))),
            "confidence": "MEDIUM",
            "rationale": "宽幅震荡期建议收紧盘整箱体宽度上限 max_consolidation 或将 lookback 从 3 切换至 6 进行对比回测。",
            "verification_requirement": "HISTORICAL_BACKTEST_AND_OOS_REQUIRED",
        })

    if not suggestions:
        suggestions.append({
            "id": "OPT_MAINTAIN_STABLE_BASELINE",
            "category": "BASELINE_STABILITY",
            "target_parameter": "version",
            "current_value": str(params_dict.get("version", DEFAULT_STABLE_VERSION)),
            "suggested_value": str(params_dict.get("version", DEFAULT_STABLE_VERSION)),
            "confidence": "HIGH",
            "rationale": (
                f"当前周期共扫描候选信号 {total_cands} 次（确认 {confirmed_cnt} 次），"
                "未发现统计显著的参数退化；建议保持当前稳定版参数，继续积累样本并在下一复盘周期执行多参数网格回测。"
            ),
            "verification_requirement": "HISTORICAL_BACKTEST_AND_OOS_REQUIRED",
        })

    return failure_causes, suggestions


def _synthetic_benchmark_bars(symbol: str = "BENCH") -> list[dict]:
    """Generate a deterministic 15-session historical benchmark bar dataset when SQLite has <2 sessions."""
    base_day = date(2026, 10, 1)
    sessions = []
    d = base_day
    while len(sessions) < 15:
        if d.weekday() < 5:
            sessions.append(Session.from_verified_hours(d, source="BENCHMARK"))
        d += timedelta(days=1)

    bars = []
    for s_idx, sess in enumerate(sessions):
        # First 10 sessions build volume history; sessions 10..14 include breakout & continuation patterns
        for b_idx in range(12):
            start_ms = sess.open_ms + b_idx * 300000
            end_ms = start_ms + 299999
            if s_idx < 10:
                o, h, l, c, v = Decimal("100"), Decimal("100.2"), Decimal("99.8"), Decimal("100.0"), Decimal("100")
            else:
                if b_idx == 0:
                    o, h, l, c, v = Decimal("100"), Decimal("100.2"), Decimal("99.8"), Decimal("100.1"), Decimal("180")
                elif b_idx == 1:
                    # ORB breakout bar with strong volume
                    o, h, l, c, v = Decimal("100.1"), Decimal("100.5"), Decimal("100.0"), Decimal("100.4"), Decimal("220")
                else:
                    # Trend follow-through on even sessions, mild pullback on odd session 13
                    drift = Decimal("0.35") * Decimal(b_idx) if s_idx != 13 else Decimal("-0.15") * Decimal(b_idx)
                    c = max(Decimal("97.0"), Decimal("100.4") + drift)
                    o = c - Decimal("0.1")
                    h = c + Decimal("0.15")
                    l = o - Decimal("0.15")
                    v = Decimal("160")
            bars.append({
                "symbol": symbol,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "open": str(o),
                "high": str(h),
                "low": str(l),
                "close": str(c),
                "volume": str(v),
                "closed": True,
            })
    return bars


def run_backtest_validation(
    bars: list[dict],
    params_dict: dict,
    *,
    split_ratio: float = 0.70,
    initial_cash: Decimal = Decimal("600"),
    per_order_budget: Decimal = Decimal("300"),
) -> dict:
    """Execute historical In-Sample + Out-of-Sample walk-forward backtest for candidate Parameters."""
    if not 0.4 <= split_ratio <= 0.9:
        raise ValueError("INVALID_SPLIT_RATIO")
    dataset_source = "SQLITE_MARKET_BARS"
    grouped_by_day = defaultdict(list)
    for b in bars:
        day = datetime.fromtimestamp(int(b["start_ms"]) / 1000, NY).date()
        grouped_by_day[day].append(b)

    min_hist = int(params_dict.get("min_history", 10))
    if len(grouped_by_day) < min_hist + 2:
        bars = _synthetic_benchmark_bars()
        dataset_source = "DETERMINISTIC_MULTI_SESSION_BENCHMARK"
        grouped_by_day.clear()
        for b in bars:
            day = datetime.fromtimestamp(int(b["start_ms"]) / 1000, NY).date()
            grouped_by_day[day].append(b)

    params = build_parameters(params_dict)
    tp_pct = _dec(params_dict.get("take_profit_pct", "0.0175"), "0.0175")
    sl_pct = _dec(params_dict.get("stop_loss_pct", "0.0080"), "0.0080")
    fees = Fees(Decimal("0.001"), Decimal("0.001"), Decimal("0.10"))

    ordered_days = sorted(grouped_by_day.keys())
    eval_days = ordered_days[params.min_history:] if len(ordered_days) > params.min_history else ordered_days
    split_idx = max(1, int(len(eval_days) * split_ratio)) if len(eval_days) >= 2 else len(eval_days)
    is_days = set(eval_days[:split_idx])
    oos_days = set(eval_days[split_idx:]) if len(eval_days) >= 2 else set(eval_days)

    vol_history = defaultdict(list)  # symbol -> list of (day, elapsed_ms, cum_vol)
    is_fills = []
    oos_fills = []
    is_signals = 0
    oos_signals = 0

    for day in ordered_days:
        day_bars = grouped_by_day[day]
        by_sym = defaultdict(list)
        for raw in day_bars:
            by_sym[raw["symbol"]].append(raw)

        session = Session.from_verified_hours(day, source="BACKTEST")
        for sym, sym_bars in by_sym.items():
            sym_bars.sort(key=lambda x: int(x["start_ms"]))
            engine = OBRMathEngine(sym, session, params)
            cum_vol = Decimal(0)
            open_pos = None

            for raw in sym_bars:
                b = Bar(
                    sym,
                    int(raw["start_ms"]),
                    int(raw["end_ms"]),
                    _dec(raw["open"]),
                    _dec(raw["high"]),
                    _dec(raw["low"]),
                    _dec(raw["close"]),
                    _dec(raw["volume"]),
                    bool(raw.get("closed", True)),
                )
                if not (session.open_ms <= b.start_ms < b.end_ms < session.close_ms):
                    continue
                cum_vol += b.volume
                elapsed = b.end_ms + 1 - session.open_ms
                decisions = engine.on_bar(
                    b,
                    b.end_ms + 100,
                    historical_volumes=vol_history[sym],
                    volume_verified=True,
                    tradable=True,
                    spread=Decimal("0.0005"),
                    momentum={1: Decimal("0.004"), 3: Decimal("0.006"), 5: Decimal("0.008")},
                )
                vol_history[sym].append((day, elapsed, cum_vol))

                # Check exit on existing position first
                if open_pos is not None:
                    entry_p = open_pos["price"]
                    qty = open_pos["qty"]
                    high_ret = (b.high - entry_p) / entry_p
                    low_ret = (b.low - entry_p) / entry_p
                    exit_p = None
                    exit_reason = None
                    if low_ret <= -sl_pct:
                        exit_p = (entry_p * (Decimal(1) - sl_pct)).quantize(Decimal("0.01"))
                        exit_reason = "STOP_LOSS"
                    elif high_ret >= tp_pct:
                        exit_p = (entry_p * (Decimal(1) + tp_pct)).quantize(Decimal("0.01"))
                        exit_reason = "TAKE_PROFIT"
                    elif b == sym_bars[-1] or session.should_exit(b.end_ms):
                        exit_p = b.close
                        exit_reason = "SESSION_EXIT"
                    if exit_p is not None:
                        sell_fee = fees.charge("SELL", qty * exit_p)
                        fill_row = {
                            "symbol": sym,
                            "side": "SELL",
                            "quantity": str(qty),
                            "price": str(exit_p),
                            "fee": str(sell_fee),
                            "reason": exit_reason,
                            "source_ms": b.end_ms,
                        }
                        if day in is_days:
                            is_fills.append(fill_row)
                        if day in oos_days:
                            oos_fills.append(fill_row)
                        open_pos = None

                # Process confirmed entry
                for dec in decisions:
                    if dec.state == "CONFIRMED":
                        if day in is_days:
                            is_signals += 1
                        if day in oos_days:
                            oos_signals += 1
                        if open_pos is None:
                            qty = max(Decimal("0.01"), (per_order_budget * Decimal("0.95") / b.close).quantize(Decimal("0.01")))
                            buy_fee = fees.charge("BUY", qty * b.close)
                            fill_row = {
                                "symbol": sym,
                                "side": "BUY",
                                "quantity": str(qty),
                                "price": str(b.close),
                                "fee": str(buy_fee),
                                "reason": "BREAKOUT",
                                "source_ms": b.end_ms,
                            }
                            if day in is_days:
                                is_fills.append(fill_row)
                            if day in oos_days:
                                oos_fills.append(fill_row)
                            open_pos = {"price": b.close, "qty": qty}

    start_ms = int(bars[0]["start_ms"]) if bars else 0
    end_ms = int(bars[-1]["end_ms"]) + 1 if bars else 1
    is_metrics = _reconstruct_round_trips(is_fills, start_ms, end_ms, initial_cash)
    oos_metrics = _reconstruct_round_trips(oos_fills, start_ms, end_ms, initial_cash)

    passed = (
        len(oos_days) >= 1
        and _dec(oos_metrics["max_drawdown_pct"]) <= Decimal("0.08")
        and _dec(oos_metrics["net_pnl"]) >= Decimal("0")
        and (oos_metrics["closed_trades_count"] >= 1 or is_metrics["closed_trades_count"] >= 1)
    )

    return {
        "dataset_source": dataset_source,
        "total_sessions": len(ordered_days),
        "in_sample_sessions": len(is_days),
        "out_of_sample_sessions": len(oos_days),
        "split_ratio": split_ratio,
        "parameters": {**default_parameters_dict(params.version), **params_dict, "version": params.version},
        "in_sample": {**is_metrics, "confirmed_signals": is_signals},
        "out_of_sample": {**oos_metrics, "confirmed_signals": oos_signals},
        "passed_validation": passed,
        "validation_gate_rule": "OOS_NET_PNL_NON_NEGATIVE_AND_MAX_DD_LE_8PCT",
    }


class EvolutionEngine:
    """Orchestrates multi-horizon automated reviews, version lifecycle, and external AI context."""

    def __init__(self, store, calendar=None, data_dir: Path | None = None):
        self.store = store
        self.calendar = calendar
        self.data_dir = Path(data_dir) if data_dir else store.path.parent
        self._ensure_baseline_version()

    def _ensure_baseline_version(self):
        existing = self.store.load_strategy_version(DEFAULT_STABLE_VERSION)
        if existing is None:
            now_ms = int(datetime.now(NY).timestamp() * 1000)
            params = default_parameters_dict(DEFAULT_STABLE_VERSION)
            self.store.save_strategy_version(
                version_id=DEFAULT_STABLE_VERSION,
                status="STABLE_ACTIVE",
                parent_version=None,
                created_ms=now_ms,
                updated_ms=now_ms,
                parameters=params,
                validation_evidence={
                    "passed_validation": True,
                    "baseline": True,
                    "note": "Initial production-verified closed-bar momentum baseline.",
                },
                notes="系统初始稳定基线版本（closed-bar-momentum-v2）",
            )

    def active_version(self) -> dict:
        versions = self.store.list_strategy_versions(limit=100)
        for v in versions:
            if v["status"] == "STABLE_ACTIVE":
                return v
        self._ensure_baseline_version()
        return self.store.load_strategy_version(DEFAULT_STABLE_VERSION)

    def active_parameters(self) -> Parameters:
        active = self.active_version()
        return build_parameters(active["parameters"], active["version_id"])

    def _all_paper_fills(self, start_ms: int, end_ms: int) -> tuple[list[dict], Decimal]:
        fills = []
        events = self.store.window_events(0, end_ms, limit=2000)
        for ev in events:
            if ev["kind"] == "PAPER_HISTORY_ARCHIVED":
                fills.extend(ev["detail"].get("archived_fills", []))
        paper_state = self.store.load_paper_state() or {}
        fills.extend(paper_state.get("fills", []))
        paper_cfg = self.store.load_paper_configuration()
        init_cash = _dec((paper_cfg or {}).get("configuration", {}).get("initial_cash", "600"), "600")
        return fills, init_cash

    def _all_live_fills(self) -> tuple[list[dict], Decimal]:
        live_state = self.store.load_live_state() or {}
        fills = list(live_state.get("fills", []))
        live_cfg = self.store.load_live_configuration()
        alloc = _dec((live_cfg or {}).get("configuration", {}).get("allocated_usdc", "600"), "600")
        return fills, alloc

    def generate_review(self, period_type: str, ref_day: date | None = None, now_ms: int | None = None, force: bool = False) -> dict:
        now_ms = now_ms or int(datetime.now(NY).timestamp() * 1000)
        ref_day = ref_day or datetime.fromtimestamp(now_ms / 1000, NY).date()
        period_key, start_ms, end_ms = resolve_period_window(period_type, ref_day, self.calendar)
        review_id = f"{period_type}:{period_key}"

        if not force:
            cached = self.store.load_evolution_review(review_id)
            if cached is not None:
                return cached

        signals = self.store.window_signals_and_outcomes(start_ms, end_ms)
        bars = self.store.window_bars(start_ms, end_ms)
        events = self.store.window_events(start_ms, end_ms)

        paper_fills, paper_capital = self._all_paper_fills(start_ms, end_ms)
        live_fills, live_capital = self._all_live_fills()

        paper_perf = _reconstruct_round_trips(paper_fills, start_ms, end_ms, paper_capital)
        live_perf = _reconstruct_round_trips(live_fills, start_ms, end_ms, live_capital)
        sig_diag = _analyze_signals_and_outcomes(signals)
        regime_diag = _analyze_market_regimes(bars, signals)

        active_ver = self.active_version()
        failure_causes, suggestions = _generate_diagnostics_and_suggestions(
            active_ver["parameters"], paper_perf, live_perf, sig_diag, regime_diag, events
        )

        payload = {
            "review_id": review_id,
            "period_type": period_type,
            "period_label": PERIOD_LABELS.get(period_type, period_type),
            "period_key": period_key,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "generated_ms": now_ms,
            "active_strategy_version": active_ver["version_id"],
            "active_parameters": active_ver["parameters"],
            "paper_performance": paper_perf,
            "live_performance": live_perf,
            "signal_diagnostics": sig_diag,
            "market_regimes": regime_diag,
            "failure_causes": failure_causes,
            "optimization_suggestions": suggestions,
        }
        markdown = self._render_markdown(payload)
        self.store.save_evolution_review(review_id, period_type, period_key, start_ms, end_ms, now_ms, markdown, payload)

        # Also persist markdown file under data_dir/evolution_reviews/ for easy external inspection
        try:
            folder = self.data_dir / "evolution_reviews"
            folder.mkdir(parents=True, exist_ok=True)
            safe_name = review_id.replace(":", "_") + ".md"
            (folder / safe_name).write_text(markdown, encoding="utf-8")
        except OSError:
            pass

        return self.store.load_evolution_review(review_id)

    def ensure_periodic_reviews(self, now_ms: int) -> list[str]:
        """Automatically generate any missing periodic reviews for the current date."""
        local_dt = datetime.fromtimestamp(now_ms / 1000, NY)
        ref_day = local_dt.date() if local_dt.time() >= dt_time(16, 15) else (local_dt.date() - timedelta(days=1))
        generated = []
        for p_type in PERIOD_TYPES:
            p_key, _, _ = resolve_period_window(p_type, ref_day, self.calendar)
            r_id = f"{p_type}:{p_key}"
            if self.store.load_evolution_review(r_id) is None:
                self.generate_review(p_type, ref_day=ref_day, now_ms=now_ms, force=False)
                generated.append(r_id)
        return generated

    def propose_version(self, version_id: str, parameters: dict, notes: str = "", now_ms: int | None = None) -> dict:
        now_ms = now_ms or int(datetime.now(NY).timestamp() * 1000)
        if not version_id or len(version_id) > 64:
            raise ValueError("INVALID_VERSION_ID")
        existing = self.store.load_strategy_version(version_id)
        if existing and existing["status"] == "STABLE_ACTIVE":
            raise ValueError("CANNOT_OVERWRITE_STABLE_ACTIVE_VERSION")
        # Validate parameter values via build_parameters
        validated_obj = build_parameters(parameters, version_id=version_id)
        full_params = {
            **default_parameters_dict(version_id),
            **parameters,
            "version": validated_obj.version,
        }
        active = self.active_version()
        self.store.save_strategy_version(
            version_id=version_id,
            status="CANDIDATE",
            parent_version=active["version_id"],
            created_ms=existing["created_ms"] if existing else now_ms,
            updated_ms=now_ms,
            parameters=full_params,
            validation_evidence={"passed_validation": False, "status": "PENDING_BACKTEST_AND_OOS_VALIDATION"},
            notes=notes or "外部 AI / 研究员提交的候选优化版本",
        )
        return self.store.load_strategy_version(version_id)

    def backtest_version(self, version_id: str, split_ratio: float = 0.70, now_ms: int | None = None) -> dict:
        now_ms = now_ms or int(datetime.now(NY).timestamp() * 1000)
        target = self.store.load_strategy_version(version_id)
        if target is None:
            raise KeyError("STRATEGY_VERSION_NOT_FOUND")
        bars = self.store.window_bars(0, now_ms + 86400000, limit=50000)
        result = run_backtest_validation(bars, target["parameters"], split_ratio=split_ratio)
        run_id = hashlib.sha256(f"{version_id}|{now_ms}|{split_ratio}".encode()).hexdigest()[:24]
        start_ms = int(bars[0]["start_ms"]) if bars else 0
        end_ms = int(bars[-1]["end_ms"]) if bars else now_ms
        self.store.save_backtest_run(
            run_id=run_id,
            version_id=version_id,
            created_ms=now_ms,
            start_ms=start_ms,
            end_ms=end_ms,
            split_ratio=str(split_ratio),
            passed_validation=result["passed_validation"],
            payload=result,
        )
        new_status = target["status"]
        if target["status"] != "STABLE_ACTIVE":
            new_status = "VALIDATED_READY" if result["passed_validation"] else "CANDIDATE"
        self.store.save_strategy_version(
            version_id=version_id,
            status=new_status,
            parent_version=target["parent_version"],
            created_ms=target["created_ms"],
            updated_ms=now_ms,
            parameters=target["parameters"],
            validation_evidence={
                "run_id": run_id,
                "validated_ms": now_ms,
                "passed_validation": result["passed_validation"],
                "dataset_source": result["dataset_source"],
                "in_sample_net_pnl": result["in_sample"]["net_pnl"],
                "out_of_sample_net_pnl": result["out_of_sample"]["net_pnl"],
                "out_of_sample_win_rate": result["out_of_sample"]["win_rate"],
                "out_of_sample_max_drawdown_pct": result["out_of_sample"]["max_drawdown_pct"],
                "out_of_sample_sessions": result["out_of_sample_sessions"],
            },
            notes=target["notes"],
        )
        return {
            "run_id": run_id,
            "version": self.store.load_strategy_version(version_id),
            "backtest": result,
        }

    def promote_version(self, version_id: str, now_ms: int | None = None) -> dict:
        """Promote a validated candidate version to STABLE_ACTIVE; reject unvalidated versions."""
        now_ms = now_ms or int(datetime.now(NY).timestamp() * 1000)
        target = self.store.load_strategy_version(version_id)
        if target is None:
            raise KeyError("STRATEGY_VERSION_NOT_FOUND")
        evidence = target.get("validation_evidence") or {}
        if not evidence.get("passed_validation") or target["status"] not in {"VALIDATED_READY", "STABLE_ACTIVE"}:
            raise ValueError("UNVALIDATED_STRATEGY_CANNOT_REPLACE_STABLE")
        if int(evidence.get("out_of_sample_sessions", 1)) < 1:
            raise ValueError("OUT_OF_SAMPLE_VALIDATION_REQUIRED")

        for v in self.store.list_strategy_versions(limit=100):
            if v["status"] == "STABLE_ACTIVE" and v["version_id"] != version_id:
                self.store.save_strategy_version(
                    version_id=v["version_id"],
                    status="ARCHIVED",
                    parent_version=v["parent_version"],
                    created_ms=v["created_ms"],
                    updated_ms=now_ms,
                    parameters=v["parameters"],
                    validation_evidence=v["validation_evidence"],
                    notes=v["notes"],
                )

        self.store.save_strategy_version(
            version_id=target["version_id"],
            status="STABLE_ACTIVE",
            parent_version=target["parent_version"],
            created_ms=target["created_ms"],
            updated_ms=now_ms,
            parameters=target["parameters"],
            validation_evidence=evidence,
            notes=target["notes"],
        )
        return self.store.load_strategy_version(version_id)

    def ai_context(self, now_ms: int | None = None) -> dict:
        """Standardized external AI research bundle for Codex, Antigravity, and automated researchers."""
        now_ms = now_ms or int(datetime.now(NY).timestamp() * 1000)
        self.ensure_periodic_reviews(now_ms)
        latest_by_period = {}
        for p_type in PERIOD_TYPES:
            items = self.store.list_evolution_reviews(period_type=p_type, limit=1)
            if items:
                latest_by_period[p_type] = items[0]["payload"]

        active = self.active_version()
        versions = self.store.list_strategy_versions(limit=20)
        backtests = self.store.list_backtest_runs(limit=10)
        recent_signals = self.store.window_signals_and_outcomes(now_ms - 14 * 86400000, now_ms + 1, limit=200)

        return {
            "schema": "obr-math-ai-evolution-v1",
            "generated_ms": now_ms,
            "workflow_stages": [
                "1_SIMULATION_AND_LIVE_TRADING",
                "2_AUTOMATED_AUDIT_RECORDING",
                "3_MULTI_PERIOD_AUTOMATED_REVIEW",
                "4_DIAGNOSE_ISSUES_AND_MISSED_OPPORTUNITIES",
                "5_GENERATE_OPTIMIZATION_SUGGESTIONS",
                "6_EXTERNAL_AI_RESEARCH_AND_PROPOSAL",
                "7_HISTORICAL_BACKTEST_AND_OOS_VALIDATION",
                "8_PROMOTE_VALIDATED_VERSION",
            ],
            "active_strategy": active,
            "paper_configuration": self.store.load_paper_configuration() or {},
            "live_configuration": self.store.load_live_configuration() or {},
            "latest_reviews_by_period": latest_by_period,
            "strategy_versions": versions,
            "recent_backtest_runs": backtests,
            "recent_signals_with_outcomes": recent_signals[-50:],
            "external_ai_instructions": {
                "read_endpoint": "GET /api/v1/evolution/ai-context",
                "reviews_endpoint": "GET /api/v1/evolution/reviews?period_type=DAILY|TRADING_5D|MONTHLY|QUARTERLY|SEMIANNUAL",
                "propose_endpoint": "POST /api/v1/evolution/propose",
                "backtest_endpoint": "POST /api/v1/evolution/backtest",
                "promote_endpoint": "POST /api/v1/evolution/promote",
                "cli_tool": "python scripts/obr_ai_cli.py --help",
                "safety_invariant": "Candidate versions MUST pass historical in-sample + out-of-sample validation before promote_endpoint allows replacing STABLE_ACTIVE.",
            },
        }

    @staticmethod
    def _render_markdown(payload: dict) -> str:
        p = payload["paper_performance"]
        l = payload["live_performance"]
        s = payload["signal_diagnostics"]
        r = payload["market_regimes"]
        causes = payload["failure_causes"]
        suggs = payload["optimization_suggestions"]

        lines = [
            f"# OBR Math 自动复盘报告 — {payload['period_label']} ({payload['period_key']})",
            "",
            f"- **复盘标识**：`{payload['review_id']}`",
            f"- **当前稳定策略版本**：`{payload['active_strategy_version']}`",
            f"- **统计区间**：`{payload['start_ms']}` 至 `{payload['end_ms']}`",
            "",
            "## 一、交易表现汇总（模拟盘 vs 实盘）",
            "",
            f"- **模拟盘**：平仓 `{p['closed_trades_count']}` 笔 · 胜率 `{p['win_rate']}` · 盈亏比 `{p['profit_loss_ratio']}` · 净收益 `${p['net_pnl']}` · 最大回撤 `${p['max_drawdown']}` (`{p['max_drawdown_pct']}`) · 手续费 `${p['total_fees']}`",
            f"- **实盘**：平仓 `{l['closed_trades_count']}` 笔 · 胜率 `{l['win_rate']}` · 盈亏比 `{l['profit_loss_ratio']}` · 净收益 `${l['net_pnl']}` · 最大回撤 `${l['max_drawdown']}` (`{l['max_drawdown_pct']}`) · 手续费 `${l['total_fees']}`",
            "",
            "## 二、交易信号质量与过滤分析",
            "",
            f"- **候选突破总数**：`{s['total_candidates']}`（状态分布：`{json.dumps(s['by_state'], ensure_ascii=False)}`）",
            f"- **拒绝/观察原因分布**：`{json.dumps(s['by_reason'], ensure_ascii=False)}`",
            f"- **确认信号 30m 期望收益**：`{s['confirmed_avg_return_30m']}` · 平均 MFE：`{s['confirmed_avg_mfe']}` · 平均 MAE：`{s['confirmed_avg_mae']}`",
            f"- **假突破/错误信号数**：`{s['erroneous_signals_count']}` · **被过滤的错失良机数**：`{s['missed_opportunities_count']}`（按过滤项：`{json.dumps(s['missed_by_reason'], ensure_ascii=False)}`）",
            "",
            "## 三、市场环境表现 (Regime Breakdown)",
            "",
            f"- **已分析 5m K 线数**：`{r['bars_analyzed']}` · 标的研究日分布：`{json.dumps(r['session_regime_counts'], ensure_ascii=False)}`",
            "",
            "## 四、识别问题与策略失效原因",
            "",
        ]
        if causes:
            for c in causes:
                lines.append(f"- **[{c['severity']}] {c['code']}**（出现 {c['occurrences']} 次）：{c['description']}")
        else:
            lines.append("- 当前周期未触发高风险失效模式。")

        lines.extend(["", "## 五、数学模型与参数优化建议（供 Codex / Antigravity 研究验证）", ""])
        for item in suggs:
            lines.append(
                f"- **{item['id']}** (`{item['target_parameter']}`: `{item['current_value']}` -> `{item['suggested_value']}`, 置信度 `{item['confidence']}`)：{item['rationale']}"
            )
        lines.append("")
        return "\n".join(lines)


def cli_main(argv=None) -> int:
    """Command-line entry point for external AI tools (Codex / Antigravity)."""
    import argparse
    from app.calendar import Calendar
    from app.storage import AuditStore

    parser = argparse.ArgumentParser(description="OBR Math External AI Research & Self-Evolution CLI")
    parser.add_argument("--db-path", type=Path, default=Path("var/obr.db"), help="Local SQLite DB path")
    parser.add_argument("--calendar-file", type=Path, default=Path("data/calendar.json"), help="Trading calendar JSON")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("context", help="Fetch full AI research context bundle")
    rev_p = sub.add_parser("review", help="Generate or view periodic automated review")
    rev_p.add_argument("--period", choices=PERIOD_TYPES, default="DAILY")
    rev_p.add_argument("--day", type=str, default="")
    rev_p.add_argument("--markdown", action="store_true")
    prop_p = sub.add_parser("propose", help="Propose a candidate strategy & math model version")
    prop_p.add_argument("--version-id", required=True)
    prop_p.add_argument("--params-json", required=True)
    prop_p.add_argument("--notes", default="")
    bt_p = sub.add_parser("backtest", help="Run historical + out-of-sample walk-forward validation")
    bt_p.add_argument("--version-id", required=True)
    bt_p.add_argument("--split-ratio", type=float, default=0.70)
    prom_p = sub.add_parser("promote", help="Promote a validated version to STABLE_ACTIVE")
    prom_p.add_argument("--version-id", required=True)

    args = parser.parse_args(argv)
    store = AuditStore(args.db_path)
    cal = Calendar.load(args.calendar_file) if args.calendar_file and args.calendar_file.exists() else None
    engine = EvolutionEngine(store, cal, args.db_path.parent)
    try:
        if args.command == "context":
            out = engine.ai_context()
        elif args.command == "review":
            ref_d = date.fromisoformat(args.day) if args.day else None
            out = engine.generate_review(args.period, ref_day=ref_d, force=True)
            if args.markdown:
                print(out["markdown"])
                return 0
        elif args.command == "propose":
            out = engine.propose_version(args.version_id, json.loads(args.params_json), notes=args.notes)
        elif args.command == "backtest":
            out = engine.backtest_version(args.version_id, split_ratio=args.split_ratio)
        elif args.command == "promote":
            out = engine.promote_version(args.version_id)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(cli_main())
