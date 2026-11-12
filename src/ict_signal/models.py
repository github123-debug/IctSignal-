from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


MINUTE_MS = 60_000
M15_MS = 15 * MINUTE_MS
HOUR_MS = 60 * MINUTE_MS
DAY_MS = 24 * HOUR_MS


class FvgDirection(StrEnum):
    BULL = "BULL"
    BEAR = "BEAR"


class TradeDirection(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class LiquiditySide(StrEnum):
    LOWER = "LOWER"
    UPPER = "UPPER"


class MachineState(StrEnum):
    IDLE = "IDLE"
    LIQUIDITY_TOUCHED = "LIQUIDITY_TOUCHED"
    BOS_CONFIRMED = "BOS_CONFIRMED"
    SIGNAL_FIRED = "SIGNAL_FIRED"


@dataclass(frozen=True, slots=True)
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float
    close_ts: int
    is_closed: bool = True
    volume: float = 0.0

    @classmethod
    def from_binance(cls, row: list[Any], now_ms: int) -> "Candle":
        close_ts = int(row[6])
        return cls(
            ts=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
            close_ts=close_ts,
            is_closed=close_ts < now_ms,
        )


@dataclass(slots=True)
class FVG:
    fvg_id: str
    direction: FvgDirection
    lower: float
    upper: float
    formed_at: int
    confirmed_at: int
    a_ts: int
    b_ts: int
    c_ts: int
    mitigated: bool = False
    expired: bool = False
    signal_emitted: bool = False

    @property
    def usable(self) -> bool:
        return not (self.mitigated or self.expired or self.signal_emitted)

    @property
    def trade_direction(self) -> TradeDirection:
        return (
            TradeDirection.LONG
            if self.direction == FvgDirection.BULL
            else TradeDirection.SHORT
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["direction"] = self.direction.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FVG":
        return cls(**{**data, "direction": FvgDirection(data["direction"])})


@dataclass(frozen=True, slots=True)
class LiquidityLevel:
    name: str
    price: float
    side: LiquiditySide


@dataclass(frozen=True, slots=True)
class SwingPoint:
    kind: str
    price: float
    bar_ts: int
    confirmed_at: int
    atr: float


@dataclass(frozen=True, slots=True)
class BosEvent:
    direction: FvgDirection
    bar_ts: int
    close_ts: int
    close: float
    broken_swing: SwingPoint


@dataclass(frozen=True, slots=True)
class Signal:
    fingerprint: str
    symbol: str
    direction: TradeDirection
    fvg: FVG
    liquidity_level: str
    bos_bar_ts: int
    signal_bar_ts: int
    signal_ts: int
    signal_price: float

