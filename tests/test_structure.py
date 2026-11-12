from __future__ import annotations

from ict_signal.models import FvgDirection, M15_MS
from ict_signal.structure import latest_bos_event, valid_swings

from conftest import candle


def _series(final_close: float, final_high: float):
    bars = [candle(i * M15_MS, 100, 101, 99, 100, M15_MS) for i in range(14)]
    bars.append(candle(14 * M15_MS, 100, 105, 99, 100, M15_MS))
    bars.extend(
        [
            candle(15 * M15_MS, 100, 101, 99, 100, M15_MS),
            candle(16 * M15_MS, 100, 101, 99, 100, M15_MS),
            candle(17 * M15_MS, 100, 104, 99, 104, M15_MS),
            candle(18 * M15_MS, 104, final_high, 103, final_close, M15_MS),
        ]
    )
    return bars


def test_bos_requires_close_crossing_swing():
    event = latest_bos_event(_series(106, 106))
    assert event is not None
    assert event.direction == FvgDirection.BULL
    assert event.broken_swing.price == 105


def test_wick_through_swing_is_not_bos():
    assert latest_bos_event(_series(104.5, 106)) is None


def test_swing_is_strict_and_confirmed_by_right_window():
    highs, _ = valid_swings(_series(106, 106))
    assert highs[-1].price == 105
    assert highs[-1].confirmed_at == (16 + 1) * M15_MS - 1

