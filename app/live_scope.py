"""User-approved product and funding boundary, independent of execution readiness."""
from dataclasses import dataclass, asdict
import json
from pathlib import Path
from urllib.parse import urlsplit


def public_scope():
    return {"buy_wallet":"MAIN", "quote_asset":"USDC", "sell_settlement_wallet":"CARD",
            "settlement_accepted":True, "automatic_transfers":False,
            "listing_country":"US", "security_types":["STOCK","ETF"],
            "instrument_form":"UNDERLYING_SECURITY", "tokenize":False,
            "unverified_instruments":"REJECT"}


@dataclass(frozen=True)
class InstrumentEvidence:
    """Normalized verified metadata; never infer product class from a ticker.

    Obtaining and verifying this evidence is a separate, not-yet-connected input.
    CSV membership or Binance tradability alone is insufficient.
    """
    symbol: str
    security_type: str
    listing_country: str
    instrument_form: str
    source_reference: str
    checked_ms: int
    expires_ms: int

    def require_allowed(self, symbol, now_ms):
        if self.symbol != symbol or self.security_type not in {"STOCK","ETF"} or self.listing_country!="US" or self.instrument_form!="UNDERLYING_SECURITY":
            raise ValueError("INSTRUMENT_OUTSIDE_APPROVED_SCOPE")
        source=urlsplit(self.source_reference)
        if source.scheme!="https" or not source.hostname or source.username or source.password:
            raise ValueError("INSTRUMENT_EVIDENCE_REQUIRED")
        if any(type(v) is not int for v in (now_ms,self.checked_ms,self.expires_ms)) or not self.checked_ms<=now_ms<self.expires_ms<=self.checked_ms+86400000:
            raise ValueError("INSTRUMENT_EVIDENCE_STALE")


class InstrumentRegistry:
    """Fail-closed authoritative US Stock/ETF metadata registry."""

    def __init__(self, records=(), *, source_file=None):
        self.records = {}
        self.source_file = Path(source_file) if source_file else None
        for item in records:
            evidence = item if isinstance(item, InstrumentEvidence) else InstrumentEvidence(**item)
            self.records[evidence.symbol] = evidence

    @classmethod
    def load(cls, path):
        path = Path(path)
        if not path.exists():
            return cls(source_file=path)
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("instruments"), list):
                return cls(source_file=path)
            records = []
            for row in data["instruments"]:
                if isinstance(row, dict):
                    records.append(InstrumentEvidence(
                        symbol=str(row["symbol"]),
                        security_type=str(row["security_type"]),
                        listing_country=str(row["listing_country"]),
                        instrument_form=str(row["instrument_form"]),
                        source_reference=str(row["source_reference"]),
                        checked_ms=row["checked_ms"],
                        expires_ms=row["expires_ms"],
                    ))
            return cls(records, source_file=path)
        except (OSError, ValueError, KeyError, TypeError):
            return cls(source_file=path)

    def get_verified(self, symbol, now_ms):
        evidence = self.records.get(symbol)
        if evidence is None:
            return None
        try:
            evidence.require_allowed(symbol, now_ms)
            return evidence
        except ValueError:
            return None

    def verified_symbols(self, symbols, now_ms):
        return tuple(sorted(s for s in symbols if self.get_verified(s, now_ms) is not None))

    def summary(self, candidates, now_ms):
        candidates = tuple(sorted(set(candidates)))
        verified = self.verified_symbols(candidates, now_ms)
        return {
            "verified_count": len(verified),
            "unverified_count": len(candidates) - len(verified),
            "verified_symbols": list(verified),
            "all_verified": bool(candidates) and len(verified) == len(candidates),
            "status": "VERIFIED" if (candidates and len(verified) == len(candidates)) else (
                "PARTIAL_VERIFIED" if verified else "ISSUER_REGION_AND_MARKET_CAP_NOT_VERIFIED"
            ),
        }
