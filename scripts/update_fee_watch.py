"""Import a browser-verified official observation. Never scrape fallback fee numbers."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.fee_watch import update

parser = argparse.ArgumentParser()
parser.add_argument("observation", type=Path)
parser.add_argument("--state", type=Path, default=Path("var/fee-watch.json"))
args = parser.parse_args()
state, changed = update(args.state, json.loads(args.observation.read_text(encoding="utf-8-sig")),time.time_ns()//1000000)
print(json.dumps({"changed":changed,"fingerprint":state["fingerprint"],"checked_ms":state["observation"]["checked_ms"]}))
