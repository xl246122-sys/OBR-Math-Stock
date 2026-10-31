from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
import json
import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.calendar import Session
from app.evolution import EvolutionEngine, PERIOD_TYPES, resolve_period_window
from app.runtime import Runtime
from app.storage import AuditStore
from tests.test_runtime import settings


def _seed_signals_outcomes_and_trades(store: AuditStore, day: date):
    session = Session.from_verified_hours(day, source="SYNTHETIC")
    t1 = session.open_ms + 300000
    t2 = session.open_ms + 600000
    t3 = session.open_ms + 900000

    # 1. Confirmed signal that turned into a bad trade (false breakout reversal)
    sig_bad = {
        "candidate_id": "cand-bad-1",
        "symbol": "TEST",
        "kind": "ORB",
        "state": "CONFIRMED",
        "reason": "RESEARCH_CONFIRMED",
        "source_ms": t1,
        "level": "100.00",
        "rvol": "1.80",
        "version": "closed-bar-momentum-v2",
        "score": "62.5",
        "provenance": "LIVE_OBSERVATION",
    }
    outcome_bad = {
        "candidate_id": "cand-bad-1",
        "horizon_minutes": 30,
        "target_ms": t1 + 30 * 60000,
        "sample_ms": t1 + 30 * 60000,
        "return": "-0.0110",
        "sampled_mfe": "0.0020",
        "sampled_mae": "-0.0130",
        "quality": "SAMPLED",
        "samples": 20,
    }

    # 2. Rejected signal due to LOW_RVOL that turned into a missed opportunity (+2.4% MFE)
    sig_missed_1 = {
        "candidate_id": "cand-missed-1",
        "symbol": "TEST",
        "kind": "INTRADAY_CONTINUATION",
        "state": "REJECTED",
        "reason": "LOW_RVOL",
        "source_ms": t2,
        "level": "101.00",
        "rvol": "1.42",
        "version": "closed-bar-momentum-v2",
        "score": "74.0",
        "provenance": "LIVE_OBSERVATION",
    }
    outcome_missed_1 = {
        "candidate_id": "cand-missed-1",
        "horizon_minutes": 30,
        "target_ms": t2 + 30 * 60000,
        "sample_ms": t2 + 30 * 60000,
        "return": "0.0185",
        "sampled_mfe": "0.0240",
        "sampled_mae": "-0.0010",
        "quality": "SAMPLED",
        "samples": 20,
    }
    sig_missed_2 = {
        **sig_missed_1,
        "candidate_id": "cand-missed-2",
        "source_ms": t3,
    }
    outcome_missed_2 = {
        **outcome_missed_1,
        "candidate_id": "cand-missed-2",
        "target_ms": t3 + 30 * 60000,
    }

    store.write_events([
        ("signal", sig_bad, t1),
        ("outcome", outcome_bad, t1 + 30 * 60000),
        ("signal", sig_missed_1, t2),
        ("outcome", outcome_missed_1, t2 + 30 * 60000),
        ("signal", sig_missed_2, t3),
        ("outcome", outcome_missed_2, t3 + 30 * 60000),
    ])

    # Seed paper_state with 1 winning round-trip and 1 losing round-trip
    store.save_paper_state({
        "schema": 1,
        "cash": "605.50",
        "fills": [
            {"symbol": "TEST", "side": "BUY", "quantity": "2", "price": "100.00", "fee": "0.20", "reason": "BREAKOUT", "source_ms": t1},
            {"symbol": "TEST", "side": "SELL", "quantity": "2", "price": "99.00", "fee": "0.20", "reason": "STOP_LOSS", "source_ms": t1 + 180000},
            {"symbol": "NVDA", "side": "BUY", "quantity": "3", "price": "100.00", "fee": "0.30", "reason": "BREAKOUT", "source_ms": t2},
            {"symbol": "NVDA", "side": "SELL", "quantity": "3", "price": "103.00", "fee": "0.30", "reason": "TAKE_PROFIT", "source_ms": t2 + 600000},
        ],
    })


def test_all_five_review_periods_and_diagnostics(tmp_path):
    store = AuditStore(tmp_path / "evo.db")
    day = date(2026, 10, 30)
    _seed_signals_outcomes_and_trades(store, day)
    engine = EvolutionEngine(store)

    for p_type in PERIOD_TYPES:
        review = engine.generate_review(p_type, ref_day=day, force=True)
        assert review["period_type"] == p_type
        payload = review["payload"]
        # Verify trade metrics (1 win, 1 loss -> 50% win rate, positive net PnL)
        paper = payload["paper_performance"]
        assert paper["closed_trades_count"] == 2
        assert paper["winning_trades_count"] == 1
        assert paper["losing_trades_count"] == 1
        assert Decimal(paper["win_rate"]) == Decimal("0.5000")
        assert Decimal(paper["net_pnl"]) > Decimal("0")
        assert Decimal(paper["max_drawdown"]) > Decimal("0")
        assert len(paper["bad_trades"]) == 1
        assert paper["bad_trades"][0]["diagnosis"] == "IMMEDIATE_FALSE_BREAKOUT_REVERSAL"

        # Verify signal quality, false breakouts, and missed opportunities
        sig_diag = payload["signal_diagnostics"]
        assert sig_diag["total_candidates"] == 3
        assert sig_diag["erroneous_signals_count"] == 1
        assert sig_diag["missed_opportunities_count"] == 2
        assert sig_diag["missed_by_reason"]["LOW_RVOL"] == 2

        # Verify failure causes and optimization suggestions
        assert len(payload["failure_causes"]) >= 1
        assert any(s["target_parameter"] == "min_rvol" for s in payload["optimization_suggestions"])
        assert "OBR Math 自动复盘报告" in review["markdown"]

    store.close()


def test_version_lifecycle_and_strict_out_of_sample_promotion_gate(tmp_path):
    conf = replace(settings(tmp_path), control_token="c" * 32)
    app = create_app(conf)
    r = Runtime(conf)
    app.state.runtime = r
    client = TestClient(app)
    monitor = {"Authorization": "Bearer " + conf.api_token}
    headers = {**monitor, "X-OBR-Control-Token": "c" * 32}

    # 1. External AI fetches full research context
    ctx_resp = client.get("/api/v1/evolution/ai-context", headers=monitor)
    assert ctx_resp.status_code == 200
    ctx = ctx_resp.json()
    assert ctx["schema"] == "obr-math-ai-evolution-v1"
    assert ctx["active_strategy"]["version_id"] == "closed-bar-momentum-v2"
    assert set(ctx["latest_reviews_by_period"].keys()) == set(PERIOD_TYPES)

    # 2. Propose a candidate strategy version
    prop_resp = client.post(
        "/api/v1/evolution/propose",
        headers=headers,
        json={
            "version_id": "candidate-rvol-1.35-v3",
            "parameters": {"min_rvol": "1.35", "max_chase": "0.0045"},
            "notes": "Relax min_rvol from 1.50 to 1.35 based on missed opportunity review",
        },
    )
    assert prop_resp.status_code == 200
    assert prop_resp.json()["status"] == "CANDIDATE"

    # 3. Attempting to promote BEFORE backtest + out-of-sample validation MUST fail with 409!
    premature = client.post(
        "/api/v1/evolution/promote",
        headers=headers,
        json={"version_id": "candidate-rvol-1.35-v3"},
    )
    assert premature.status_code == 409
    assert "UNVALIDATED_STRATEGY_CANNOT_REPLACE_STABLE" in premature.text

    # 4. Run historical + out-of-sample walk-forward validation
    bt_resp = client.post(
        "/api/v1/evolution/backtest",
        headers=headers,
        json={"version_id": "candidate-rvol-1.35-v3", "split_ratio": 0.70},
    )
    assert bt_resp.status_code == 200
    bt_data = bt_resp.json()
    assert bt_data["backtest"]["passed_validation"] is True
    assert bt_data["version"]["status"] == "VALIDATED_READY"
    assert bt_data["backtest"]["out_of_sample_sessions"] >= 1

    # 5. Promote validated version -> succeeds and updates Runtime's active_parameters
    prom_resp = client.post(
        "/api/v1/evolution/promote",
        headers=headers,
        json={"version_id": "candidate-rvol-1.35-v3"},
    )
    assert prom_resp.status_code == 200
    assert prom_resp.json()["status"] == "STABLE_ACTIVE"
    assert r.active_parameters.version == "candidate-rvol-1.35-v3"
    assert r.active_parameters.min_rvol == Decimal("1.35")

    r.store.close()


def test_external_ai_cli_workflow(tmp_path, capsys):
    from app.evolution import cli_main
    db_file = tmp_path / "cli_evo.db"
    assert cli_main(["--db-path", str(db_file), "context"]) == 0
    ctx_out = json.loads(capsys.readouterr().out)
    assert ctx_out["schema"] == "obr-math-ai-evolution-v1"

    assert cli_main(["--db-path", str(db_file), "propose", "--version-id", "cli-cand-v2", "--params-json", '{"min_rvol":"1.40"}']) == 0
    prop_out = json.loads(capsys.readouterr().out)
    assert prop_out["status"] == "CANDIDATE"

    assert cli_main(["--db-path", str(db_file), "backtest", "--version-id", "cli-cand-v2"]) == 0
    bt_out = json.loads(capsys.readouterr().out)
    assert bt_out["backtest"]["passed_validation"] is True

    assert cli_main(["--db-path", str(db_file), "promote", "--version-id", "cli-cand-v2"]) == 0
    prom_out = json.loads(capsys.readouterr().out)
    assert prom_out["status"] == "STABLE_ACTIVE"

