"""Standardized External AI CLI Bridge for OBR Math (Codex / Antigravity / Research Agents).

Allows external AI tools to inspect automated reviews, read signal/trade diagnostics,
propose candidate strategy parameters, run historical + Out-of-Sample backtests,
and promote validated strategy versions either against a local SQLite DB or remote HTTPS server.
"""
import argparse
from datetime import date
import json
from pathlib import Path
import ssl
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.calendar import Calendar
from app.evolution import EvolutionEngine, PERIOD_TYPES
from app.storage import AuditStore


def _local_engine(db_path: Path, calendar_path: Path | None = None) -> EvolutionEngine:
    store = AuditStore(db_path)
    cal = Calendar.load(calendar_path) if calendar_path and calendar_path.exists() else None
    return EvolutionEngine(store, cal, db_path.parent)


def _remote_request(server: str, path: str, token: str, method: str = "GET", payload: dict | None = None, control_token: str = ""):
    url = server.rstrip("/") + "/api/v1/" + path.lstrip("/")
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        if control_token:
            headers["X-OBR-Control-Token"] = control_token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    ctx = ssl._create_unverified_context() if url.startswith("https://") else None
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        return json.load(resp)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="OBR Math External AI Research & Self-Evolution CLI")
    parser.add_argument("--db-path", type=Path, default=ROOT / "var/obr.db", help="Local SQLite DB path")
    parser.add_argument("--calendar-file", type=Path, default=ROOT / "data/calendar.json", help="Trading calendar JSON")
    parser.add_argument("--server", type=str, default="", help="Optional remote HTTPS server (e.g. https://43.163.203.127)")
    parser.add_argument("--api-token", type=str, default="", help="Bearer API token for remote mode")
    parser.add_argument("--control-token", type=str, default="", help="Control token for remote write actions")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("context", help="Fetch full AI research context bundle (reviews, versions, signals, suggestions)")

    rev_p = sub.add_parser("review", help="Generate or view periodic automated review")
    rev_p.add_argument("--period", choices=PERIOD_TYPES, default="DAILY")
    rev_p.add_argument("--day", type=str, default="", help="Reference date YYYY-MM-DD")
    rev_p.add_argument("--markdown", action="store_true", help="Print Markdown report instead of JSON")

    prop_p = sub.add_parser("propose", help="Propose a candidate strategy & math model version")
    prop_p.add_argument("--version-id", required=True, help="Unique candidate version ID")
    prop_p.add_argument("--params-json", required=True, help="JSON string of parameter overrides")
    prop_p.add_argument("--notes", default="", help="Rationale / optimization notes")

    bt_p = sub.add_parser("backtest", help="Run historical + out-of-sample walk-forward validation on a version")
    bt_p.add_argument("--version-id", required=True, help="Target version ID")
    bt_p.add_argument("--split-ratio", type=float, default=0.70, help="In-sample split ratio (0.40 - 0.90)")

    prom_p = sub.add_parser("promote", help="Promote a validated version to STABLE_ACTIVE")
    prom_p.add_argument("--version-id", required=True, help="Validated version ID")

    args = parser.parse_args(argv)

    if args.server:
        if args.command == "context":
            out = _remote_request(args.server, "evolution/ai-context", args.api_token)
        elif args.command == "review":
            out = _remote_request(
                args.server,
                "evolution/review",
                args.api_token,
                method="POST",
                payload={"period_type": args.period, "ref_day": args.day or None, "force": True},
                control_token=args.control_token,
            )
            if args.markdown:
                print(out.get("markdown", ""))
                return 0
        elif args.command == "propose":
            out = _remote_request(
                args.server,
                "evolution/propose",
                args.api_token,
                method="POST",
                payload={"version_id": args.version_id, "parameters": json.loads(args.params_json), "notes": args.notes},
                control_token=args.control_token,
            )
        elif args.command == "backtest":
            out = _remote_request(
                args.server,
                "evolution/backtest",
                args.api_token,
                method="POST",
                payload={"version_id": args.version_id, "split_ratio": args.split_ratio},
                control_token=args.control_token,
            )
        elif args.command == "promote":
            out = _remote_request(
                args.server,
                "evolution/promote",
                args.api_token,
                method="POST",
                payload={"version_id": args.version_id},
                control_token=args.control_token,
            )
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    engine = _local_engine(args.db_path, args.calendar_file)
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
        engine.store.close()


if __name__ == "__main__":
    raise SystemExit(main())
