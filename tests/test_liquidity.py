from __future__ import annotations

from ict_signal.liquidity import fixed_liquidity_levels, touched
from ict_signal.models import DAY_MS

from conftest import candle


def test_percent_tolerance_touch():
    assert touched(100, 100.1, 99.96, 0.0005)
    assert not touched(100, 99.94, 99.90, 0.0005)


def test_previous_complete_day_and_week_only():
    daily = [
        candle(0, 100, 110, 90, 100, DAY_MS),
        candle(DAY_MS, 100, 120, 80, 110, DAY_MS, closed=False),
    ]
    weekly = [candle(0, 100, 130, 70, 100, 7 * DAY_MS)]
    levels = fixed_liquidity_levels(daily, weekly, DAY_MS + 1)
    values = {level.name: level.price for level in levels}
    assert values == {"PDH": 110, "PDL": 90}

