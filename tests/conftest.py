from __future__ import annotations

import pytest

from ict_signal.config import Settings
from ict_signal.models import Candle, FVG, FvgDirection


@pytest.fixture
def settings(tmp_path):
    return Settings(database_path=tmp_path / "signals.db")


def candle(
    ts: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    interval_ms: int = 60_000,
    closed: bool = True,
) -> Candle:
    return Candle(
        ts=ts,
        open=open_,
        high=high,
        low=low,
        close=close,
        close_ts=ts + interval_ms - 1,
        is_closed=closed,
    )


def fvg(
    fvg_id: str = "bull_1H_20260101_0100",
    direction: FvgDirection = FvgDirection.BULL,
    lower: float = 90,
    upper: float = 95,
    confirmed_at: int = 1,
) -> FVG:
    return FVG(
        fvg_id=fvg_id,
        direction=direction,
        lower=lower,
        upper=upper,
        formed_at=0,
        confirmed_at=confirmed_at,
        a_ts=0,
        b_ts=3_600_000,
        c_ts=7_200_000,
    )

