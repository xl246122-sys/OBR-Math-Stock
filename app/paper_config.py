"""User-editable paper budgets; fees must come from Binance official schedules."""
from dataclasses import dataclass, asdict
from decimal import Decimal
import json
from app.market import number

@dataclass(frozen=True)
class PaperConfig:
    initial_cash: Decimal = Decimal("600")
    per_order_budget: Decimal = Decimal("300")
    max_positions: int = 2
    fee_policy: str = "BINANCE_OFFICIAL_DYNAMIC"
    max_daily_loss: Decimal | None = None
    max_exposure: Decimal | None = None
    max_daily_symbols: int = 5

    def __post_init__(self):
        for name in ("initial_cash", "per_order_budget"):
            object.__setattr__(self, name, number(getattr(self, name), positive=True))
        if self.per_order_budget > self.initial_cash:
            raise ValueError("ORDER_BUDGET_EXCEEDS_CAPITAL")
        if type(self.max_positions) is not int or not 1 <= self.max_positions <= 5:
            raise ValueError("INVALID_POSITION_LIMIT")
        if self.fee_policy != "BINANCE_OFFICIAL_DYNAMIC":
            raise ValueError("OFFICIAL_DYNAMIC_FEES_REQUIRED")
        for name, default in (("max_daily_loss",self.initial_cash*Decimal(".01")),("max_exposure",self.initial_cash)):
            object.__setattr__(self,name,number(getattr(self,name) if getattr(self,name) is not None else default,positive=True))
        if self.max_exposure>self.initial_cash or self.max_daily_loss>self.initial_cash:
            raise ValueError("RISK_LIMIT_EXCEEDS_CAPITAL")
        if type(self.max_daily_symbols) is not int or not 1<=self.max_daily_symbols<=5:
            raise ValueError("INVALID_DAILY_SYMBOL_LIMIT")

    @classmethod
    def load(cls, path):
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if data.pop("paper_mode", None) is not True or data.pop("live_trading_enabled", None) is not False:
            raise ValueError("PAPER_ONLY_CONFIGURATION_REQUIRED")
        return cls(**data)

    def public(self):
        return {k: str(v) if isinstance(v, Decimal) else v for k, v in asdict(self).items()}


@dataclass(frozen=True)
class LiveConfig:
    allocated_usdc: Decimal = Decimal("600")
    per_order_budget: Decimal = Decimal("300")
    max_positions: int = 2
    max_daily_loss: Decimal | None = None
    max_exposure: Decimal | None = None
    max_daily_symbols: int = 5
    take_profit_pct: Decimal = Decimal("0.0175")
    stop_loss_pct: Decimal = Decimal("0.0080")
    buy_wallet: str = "MAIN"
    quote_asset: str = "USDC"
    sell_settlement_wallet: str = "CARD"

    def __post_init__(self):
        for name in ("allocated_usdc", "per_order_budget", "take_profit_pct", "stop_loss_pct"):
            object.__setattr__(self, name, number(getattr(self, name), positive=True))
        if self.per_order_budget > self.allocated_usdc:
            raise ValueError("ORDER_BUDGET_EXCEEDS_CAPITAL")
        if type(self.max_positions) is not int or not 1 <= self.max_positions <= 5:
            raise ValueError("INVALID_POSITION_LIMIT")
        for name, default in (("max_daily_loss", self.allocated_usdc * Decimal(".01")), ("max_exposure", self.allocated_usdc)):
            object.__setattr__(self, name, number(getattr(self, name) if getattr(self, name) is not None else default, positive=True))
        if self.max_exposure > self.allocated_usdc or self.max_daily_loss > self.allocated_usdc:
            raise ValueError("RISK_LIMIT_EXCEEDS_CAPITAL")
        if type(self.max_daily_symbols) is not int or not 1 <= self.max_daily_symbols <= 5:
            raise ValueError("INVALID_DAILY_SYMBOL_LIMIT")
        if not Decimal("0.001") <= self.take_profit_pct <= Decimal("0.50"):
            raise ValueError("INVALID_TAKE_PROFIT_PCT")
        if not Decimal("0.001") <= self.stop_loss_pct <= Decimal("0.20"):
            raise ValueError("INVALID_STOP_LOSS_PCT")
        if self.buy_wallet != "MAIN" or self.quote_asset != "USDC" or self.sell_settlement_wallet != "CARD":
            raise ValueError("INVALID_WALLET_SCOPE")

    def public(self):
        return {k: str(v) if isinstance(v, Decimal) else v for k, v in asdict(self).items()}
