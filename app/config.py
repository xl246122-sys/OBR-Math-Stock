import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    api_token: str = field(repr=False)
    runtime_enabled: bool = False
    data_dir: Path = Path("var")
    universe_file: Path = Path("data/universe.json")
    calendar_file: Path = Path("data/calendar.json")
    binance_api_key: str = field(default="", repr=False)
    focus_limit: int = 9
    paper_config_file: Path | None = None
    control_token: str = field(default="", repr=False)

    @classmethod
    def from_env(cls):
        if os.getenv("PAPER_MODE", "true").lower() != "true":
            raise ValueError("PAPER_MODE must remain true")
        if os.getenv("LIVE_TRADING_ENABLED", "false").lower() != "false":
            raise ValueError("Live trading is not implemented or permitted")
        token = os.getenv("OBR_API_TOKEN", "")
        if len(token) < 32:
            raise ValueError("OBR_API_TOKEN must contain at least 32 characters")
        limit = int(os.getenv("OBR_FOCUS_LIMIT", "9"))
        if not 1 <= limit <= 9:
            raise ValueError("Focus limit must be 1..9 until higher subscription loads are validated")
        return cls(token, os.getenv("OBR_RUNTIME_ENABLED", "false").lower() == "true",
                   Path(os.getenv("OBR_DATA_DIR", "var")),
                   Path(os.getenv("OBR_UNIVERSE_FILE", "data/universe.json")),
                   Path(os.getenv("OBR_CALENDAR_FILE", "data/calendar.json")),
                   os.getenv("BINANCE_API_KEY", ""), limit,
                   Path(os.environ["OBR_PAPER_CONFIG_FILE"]) if os.getenv("OBR_PAPER_CONFIG_FILE") else None,
                   os.getenv("OBR_CONTROL_TOKEN", ""))
