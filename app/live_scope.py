"""User-approved product and funding boundary, independent of execution readiness."""
from dataclasses import dataclass
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
