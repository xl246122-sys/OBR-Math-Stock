"""Official-page observations, imported after browser verification; no order APIs."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

SOURCE = "https://www.binance.com/en/fee/stocks"
MAX_AGE_MS = 26 * 3600000


def validate(observation, now_ms):
    if observation.get("source") != SOURCE or observation.get("product") != "DIRECT_US_EQUITIES":
        raise ValueError("INVALID_FEE_SOURCE")
    checked = observation.get("checked_ms")
    if type(checked) is not int or not 0 <= now_ms - checked <= MAX_AGE_MS:
        raise ValueError("INVALID_FEE_OBSERVATION_TIME")
    terms = observation.get("terms")
    if not isinstance(terms, dict) or not terms or len(json.dumps(terms)) > 50000:
        raise ValueError("INVALID_FEE_TERMS")
    if not isinstance(terms.get("rules"), list) or not terms["rules"]:
        raise ValueError("MISSING_FEE_RULES")
    ids = set()
    for rule in terms["rules"]:
        if not isinstance(rule.get("id"), str) or rule["id"] in ids:
            raise ValueError("INVALID_FEE_RULE_ID")
        ids.add(rule["id"])
        for name in ("effective_ms", "expires_ms"):
            if rule.get(name) is not None and type(rule[name]) is not int:
                raise ValueError("INVALID_FEE_EFFECTIVE_TIME")
        if rule.get("effective_ms") is not None and rule.get("expires_ms") is not None and rule["expires_ms"] <= rule["effective_ms"]:
            raise ValueError("INVALID_FEE_INTERVAL")
    return observation


def fingerprint(terms):
    return hashlib.sha256(json.dumps(terms, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def active_rules(terms, now_ms):
    return sorted(r["id"] for r in terms["rules"]
                  if (r.get("effective_ms") is None or r["effective_ms"] <= now_ms)
                  and (r.get("expires_ms") is None or now_ms < r["expires_ms"]))


def update(path, observation, now_ms):
    path = Path(path)
    validate(observation, now_ms)
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    if previous and observation["checked_ms"] < previous["observation"]["checked_ms"]:
        raise ValueError("OUT_OF_ORDER_FEE_OBSERVATION")
    digest = fingerprint(observation["terms"])
    active = active_rules(observation["terms"], now_ms)
    changed = previous is not None and (previous["fingerprint"] != digest or previous["active_rules"] != active)
    change = previous.get("change") if previous else None
    if changed:
        change = {"id":f"{now_ms}-{digest[:16]}", "time_ms":now_ms,
                  "kind":"TERMS_CHANGED" if previous["fingerprint"] != digest else "RULE_EFFECTIVE_OR_EXPIRED",
                  "before":previous["observation"]["terms"], "after":observation["terms"],
                  "previous_active_rules":previous["active_rules"], "active_rules":active, "source":SOURCE}
    state = {"schema":1,"observation":observation,"fingerprint":digest,"active_rules":active,"change":change}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return state, changed


def view(path, now_ms):
    try:
        state = json.loads(Path(path).read_text(encoding="utf-8"))
        checked = state["observation"]["checked_ms"]
        stale = not 0 <= now_ms - checked <= MAX_AGE_MS
        return {**state,"status":"STALE" if stale else "CURRENT_PUBLIC_SCHEDULE",
                "account_fee_verified":False,"source":SOURCE,
                "active_rules_now":active_rules(state["observation"]["terms"],now_ms),
                "schedule":"每日北京时间 09:00，由 Codex 定时核查官方页面"}
    except (OSError, ValueError, KeyError, TypeError):
        return {"status":"UNAVAILABLE","account_fee_verified":False,"source":SOURCE,"change":None}
