import csv
import hashlib
import io
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class UniverseImport:
    version: str
    symbols: tuple[str, ...]
    errors: tuple[dict, ...]


def import_csv(content):
    """No assumptions about issuer nationality, market cap or tradability."""
    reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")))
    if not reader.fieldnames or not ({"symbol", "代码"} & set(reader.fieldnames)):
        raise ValueError("CSV_REQUIRES_SYMBOL_COLUMN")
    column = "symbol" if "symbol" in reader.fieldnames else "代码"
    seen, errors = set(), []
    for line, row in enumerate(reader, 2):
        symbol = (row.get(column) or "").strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", symbol):
            errors.append({"line": line, "reason": "INVALID_SYMBOL", "value": symbol})
        elif symbol in seen:
            errors.append({"line": line, "reason": "DUPLICATE", "value": symbol})
        else:
            seen.add(symbol)
    return UniverseImport(hashlib.sha256(content.encode()).hexdigest(), tuple(sorted(seen)), tuple(errors))


def prioritize(symbols, verified_rules, scores, limit=300):
    if not 0 <= limit <= 300:
        raise ValueError("INVALID_SUBSCRIPTION_LIMIT")
    eligible = [s for s in set(symbols) if verified_rules.get(s) == "BUY_SELL"]
    return tuple(sorted(eligible, key=lambda s: (-scores.get(s, 0), s))[:limit])
