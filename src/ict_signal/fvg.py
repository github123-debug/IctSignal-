from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from .config import Settings
from .models import Candle, FVG, FvgDirection, HOUR_MS


def _id(direction: FvgDirection, formed_at: int) -> str:
    stamp = datetime.fromtimestamp(formed_at / 1000, tz=timezone.utc).strftime(
        "%Y%m%d_%H%M"
    )
    return f"{direction.value.lower()}_1H_{stamp}"


def detect_fvgs(
    candles: Iterable[Candle],
    settings: Settings,
    as_of_ts: int,
    emitted_ids: set[str] | None = None,
) -> list[FVG]:
    """Detect and evaluate FVGs using only candles closed by ``as_of_ts``."""
    emitted_ids = emitted_ids or set()
    closed = sorted(
        (c for c in candles if c.is_closed and c.close_ts <= as_of_ts),
        key=lambda c: c.ts,
    )
    result: list[FVG] = []
    seen: set[str] = set()

    for index in range(2, len(closed)):
        a, b, c = closed[index - 2], closed[index - 1], closed[index]
        matches: list[tuple[FvgDirection, float, float]] = []
        if settings.fvg_definition == "document":
            if c.high < a.low:
                matches.append((FvgDirection.BULL, c.high, a.low))
            if c.low > a.high:
                matches.append((FvgDirection.BEAR, a.high, c.low))
        else:
            if c.low > a.high:
                matches.append((FvgDirection.BULL, a.high, c.low))
            if c.high < a.low:
                matches.append((FvgDirection.BEAR, c.high, a.low))

        for direction, lower, upper in matches:
            fvg_id = _id(direction, b.ts)
            if fvg_id in seen:
                continue
            seen.add(fvg_id)
            fvg = FVG(
                fvg_id=fvg_id,
                direction=direction,
                lower=lower,
                upper=upper,
                formed_at=b.ts,
                confirmed_at=c.close_ts,
                a_ts=a.ts,
                b_ts=b.ts,
                c_ts=c.ts,
                signal_emitted=fvg_id in emitted_ids,
            )
            later = [bar for bar in closed if bar.ts > c.ts]
            if direction == FvgDirection.BULL:
                fvg.mitigated = any(
                    (bar.close < lower)
                    if settings.mitigation_use_close
                    else (bar.low < lower)
                    for bar in later
                )
            else:
                fvg.mitigated = any(
                    (bar.close > upper)
                    if settings.mitigation_use_close
                    else (bar.high > upper)
                    for bar in later
                )
            fvg.expired = (
                as_of_ts - fvg.formed_at
                >= settings.fvg_max_age_hours * HOUR_MS
            )
            result.append(fvg)
    return result


def closest_usable_fvg(
    fvgs: Iterable[FVG], direction: FvgDirection, current_price: float
) -> FVG | None:
    candidates = [fvg for fvg in fvgs if fvg.direction == direction and fvg.usable]
    if not candidates:
        return None
    boundary = (
        (lambda item: item.lower)
        if direction == FvgDirection.BULL
        else (lambda item: item.upper)
    )
    return min(candidates, key=lambda item: abs(current_price - boundary(item)))

