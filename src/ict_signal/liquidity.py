from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from .models import Candle, LiquidityLevel, LiquiditySide


UTC = timezone.utc


def utc_day(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, tz=UTC).date().isoformat()


def day_start_ms(ts: int) -> int:
    value = datetime.fromtimestamp(ts / 1000, tz=UTC)
    return int(value.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)


def week_start_ms(ts: int) -> int:
    value = datetime.fromtimestamp(ts / 1000, tz=UTC)
    start = (value - timedelta(days=value.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return int(start.timestamp() * 1000)


def _last_before(candles: Iterable[Candle], boundary_ts: int) -> Candle | None:
    eligible = [
        candle
        for candle in candles
        if candle.is_closed and candle.close_ts < boundary_ts
    ]
    return max(eligible, key=lambda candle: candle.ts, default=None)


def fixed_liquidity_levels(
    daily: Iterable[Candle], weekly: Iterable[Candle], as_of_ts: int
) -> list[LiquidityLevel]:
    previous_day = _last_before(daily, day_start_ms(as_of_ts))
    previous_week = _last_before(weekly, week_start_ms(as_of_ts))
    levels: list[LiquidityLevel] = []
    if previous_day:
        levels.extend(
            [
                LiquidityLevel("PDH", previous_day.high, LiquiditySide.UPPER),
                LiquidityLevel("PDL", previous_day.low, LiquiditySide.LOWER),
            ]
        )
    if previous_week:
        levels.extend(
            [
                LiquidityLevel("PWH", previous_week.high, LiquiditySide.UPPER),
                LiquidityLevel("PWL", previous_week.low, LiquiditySide.LOWER),
            ]
        )
    return levels


def touched(level: float, candle_high: float, candle_low: float, tolerance: float) -> bool:
    upper_band = level * (1 + tolerance)
    lower_band = level * (1 - tolerance)
    return candle_high >= lower_band and candle_low <= upper_band

