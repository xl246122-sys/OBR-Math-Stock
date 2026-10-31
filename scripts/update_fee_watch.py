"""Import a browser-verified official observation. Never scrape fallback fee numbers."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.fee_watch import update

parser = argparse.ArgumentParser()
parser.add_argument("observation", nargs="?", type=Path, default=ROOT / "data/fee-observation.json")
parser.add_argument("--state", type=Path, default=ROOT / "var/fee-watch.json")
parser.add_argument("--touch-checked-ms", action="store_true")
args = parser.parse_args()
now_ms = time.time_ns() // 1000000
obs_path = args.observation if args.observation.is_absolute() else (Path.cwd() / args.observation if (Path.cwd() / args.observation).exists() else ROOT / args.observation)
state_path = args.state if args.state.is_absolute() else ROOT / args.state
payload = json.loads(obs_path.read_text(encoding="utf-8-sig"))
if args.touch_checked_ms:
    payload["checked_ms"] = now_ms
    obs_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
state, changed = update(state_path, payload, now_ms)
print(json.dumps({"changed": changed, "fingerprint": state["fingerprint"], "checked_ms": state["observation"]["checked_ms"]}))
