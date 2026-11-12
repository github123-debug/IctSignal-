from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


@dataclass(frozen=True, slots=True)
class Settings:
    market_data_source: str = "binance"
    binance_base_url: str = "https://fapi.binance.com"
    gate_base_url: str = "https://api.gateio.ws"
    symbols: tuple[str, ...] = ()
    top_n: int = 50
    min_quote_volume_usdt: float = 10_000_000
    max_concurrency: int = 8
    poll_seconds: int = 60

    fvg_definition: str = "document"
    fvg_max_age_hours: int = 24
    mitigation_use_close: bool = True
    liquidity_tolerance_pct: float = 0.0005
    bos_swing_window: int = 2
    bos_atr_period: int = 14
    bos_min_atr_mult: float = 1.0
    bos_timeout_bars_15m: int = 16
    entry_timeout_bars_15m: int = 8
    cooldown_bars_15m: int = 5

    database_path: Path = Path("data/ict_signal.db")
    stale_signal_minutes: int = 5
    telegram_enabled: bool = False
    tg_bot_token: str = ""
    tg_chat_id: str = ""
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> "Settings":
        load_dotenv(env_file, override=False)
        raw_symbols = os.getenv("SYMBOLS", "")
        settings = cls(
            market_data_source=os.getenv("MARKET_DATA_SOURCE", "binance").lower(),
            binance_base_url=os.getenv(
                "BINANCE_BASE_URL", "https://fapi.binance.com"
            ).rstrip("/"),
            gate_base_url=os.getenv(
                "GATE_BASE_URL", "https://api.gateio.ws"
            ).rstrip("/"),
            symbols=tuple(
                item.strip().upper() for item in raw_symbols.split(",") if item.strip()
            ),
            top_n=_int("TOP_N", 50),
            min_quote_volume_usdt=_float(
                "MIN_QUOTE_VOLUME_USDT", 10_000_000
            ),
            max_concurrency=_int("MAX_CONCURRENCY", 8),
            poll_seconds=_int("POLL_SECONDS", 60),
            fvg_definition=os.getenv("FVG_DEFINITION", "document").lower(),
            fvg_max_age_hours=_int("FVG_MAX_AGE_HOURS", 24),
            mitigation_use_close=_bool("MITIGATION_USE_CLOSE", True),
            liquidity_tolerance_pct=_float(
                "LIQUIDITY_TOLERANCE_PCT", 0.0005
            ),
            bos_swing_window=_int("BOS_SWING_WINDOW", 2),
            bos_atr_period=_int("BOS_ATR_PERIOD", 14),
            bos_min_atr_mult=_float("BOS_MIN_ATR_MULT", 1.0),
            bos_timeout_bars_15m=_int("BOS_TIMEOUT_BARS_15M", 16),
            entry_timeout_bars_15m=_int("ENTRY_TIMEOUT_BARS_15M", 8),
            cooldown_bars_15m=_int("COOLDOWN_BARS_15M", 5),
            database_path=Path(os.getenv("DATABASE_PATH", "data/ict_signal.db")),
            stale_signal_minutes=_int("STALE_SIGNAL_MINUTES", 5),
            telegram_enabled=_bool("TELEGRAM_ENABLED", False),
            tg_bot_token=os.getenv("TG_BOT_TOKEN", "").strip(),
            tg_chat_id=os.getenv("TG_CHAT_ID", "").strip(),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        ranges = {
            "fvg_max_age_hours": (self.fvg_max_age_hours, 6, 48),
            "liquidity_tolerance_pct": (
                self.liquidity_tolerance_pct,
                0.0001,
                0.002,
            ),
            "bos_swing_window": (self.bos_swing_window, 1, 3),
            "bos_min_atr_mult": (self.bos_min_atr_mult, 0.5, 2.0),
            "bos_timeout_bars_15m": (self.bos_timeout_bars_15m, 8, 32),
            "entry_timeout_bars_15m": (self.entry_timeout_bars_15m, 4, 16),
            "cooldown_bars_15m": (self.cooldown_bars_15m, 3, 20),
        }
        for name, (value, minimum, maximum) in ranges.items():
            if not minimum <= value <= maximum:
                raise ValueError(f"{name} must be between {minimum} and {maximum}")
        if self.fvg_definition not in {"document", "classic"}:
            raise ValueError("FVG_DEFINITION must be 'document' or 'classic'")
        if self.market_data_source not in {"binance", "gate"}:
            raise ValueError("MARKET_DATA_SOURCE must be 'binance' or 'gate'")
        if self.bos_atr_period != 14:
            raise ValueError("BOS_ATR_PERIOD is fixed at 14 by the specification")
        if self.top_n < 1 or self.max_concurrency < 1 or self.poll_seconds < 5:
            raise ValueError("TOP_N/MAX_CONCURRENCY must be positive; POLL_SECONDS >= 5")
        if self.telegram_enabled and not (self.tg_bot_token and self.tg_chat_id):
            raise ValueError(
                "TELEGRAM_ENABLED=true requires TG_BOT_TOKEN and TG_CHAT_ID"
            )

