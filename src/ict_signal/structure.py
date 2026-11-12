from __future__ import annotations

from collections.abc import Iterable

from .models import BosEvent, Candle, FvgDirection, SwingPoint


def atr_values(candles: list[Candle], period: int = 14) -> list[float | None]:
    if not candles:
        return []
    true_ranges: list[float] = []
    for index, candle in enumerate(candles):
        if index == 0:
            true_ranges.append(candle.high - candle.low)
            continue
        previous_close = candles[index - 1].close
        true_ranges.append(
            max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        )
    result: list[float | None] = [None] * len(candles)
    for index in range(period - 1, len(candles)):
        result[index] = sum(true_ranges[index - period + 1 : index + 1]) / period
    return result


def valid_swings(
    source: Iterable[Candle], window: int = 2, atr_period: int = 14, atr_mult: float = 1.0
) -> tuple[list[SwingPoint], list[SwingPoint]]:
    candles = sorted(
        (candle for candle in source if candle.is_closed), key=lambda candle: candle.ts
    )
    atr = atr_values(candles, atr_period)
    highs: list[SwingPoint] = []
    lows: list[SwingPoint] = []

    for index in range(window, len(candles) - window):
        value = atr[index]
        if value is None:
            continue
        candle = candles[index]
        left = candles[index - window : index]
        right = candles[index + 1 : index + window + 1]
        confirmed_at = right[-1].close_ts

        if all(candle.high > item.high for item in (*left, *right)):
            point = SwingPoint("HIGH", candle.high, candle.ts, confirmed_at, value)
            _append_or_merge(highs, point, value * atr_mult, more_extreme=max)
        if all(candle.low < item.low for item in (*left, *right)):
            point = SwingPoint("LOW", candle.low, candle.ts, confirmed_at, value)
            _append_or_merge(lows, point, value * atr_mult, more_extreme=min)
    return highs, lows


def _append_or_merge(
    points: list[SwingPoint],
    candidate: SwingPoint,
    minimum_distance: float,
    more_extreme,
) -> None:
    if not points or abs(candidate.price - points[-1].price) >= minimum_distance:
        points.append(candidate)
        return
    if more_extreme(candidate.price, points[-1].price) == candidate.price:
        points[-1] = candidate


def latest_bos_event(
    source: Iterable[Candle], window: int = 2, atr_period: int = 14, atr_mult: float = 1.0
) -> BosEvent | None:
    candles = sorted(
        (candle for candle in source if candle.is_closed), key=lambda candle: candle.ts
    )
    if len(candles) < max(atr_period + window * 2, 2):
        return None
    current, previous = candles[-1], candles[-2]
    highs, lows = valid_swings(candles, window, atr_period, atr_mult)
    highs = [point for point in highs if point.confirmed_at < current.close_ts]
    lows = [point for point in lows if point.confirmed_at < current.close_ts]

    if highs:
        swing = highs[-1]
        if previous.close <= swing.price < current.close:
            return BosEvent(
                FvgDirection.BULL,
                current.ts,
                current.close_ts,
                current.close,
                swing,
            )
    if lows:
        swing = lows[-1]
        if previous.close >= swing.price > current.close:
            return BosEvent(
                FvgDirection.BEAR,
                current.ts,
                current.close_ts,
                current.close,
                swing,
            )
    return None
