from __future__ import annotations

from dataclasses import replace

from ict_signal.models import (
    BosEvent,
    FvgDirection,
    LiquidityLevel,
    LiquiditySide,
    M15_MS,
    MachineState,
    SwingPoint,
)
from ict_signal.state_machine import SignalStateMachine
from ict_signal.liquidity import utc_day

from conftest import candle, fvg


def bos(close_ts: int, direction: FvgDirection = FvgDirection.BULL) -> BosEvent:
    swing = SwingPoint("HIGH", 105, close_ts - M15_MS, close_ts - 1, 2)
    return BosEvent(direction, close_ts - M15_MS + 1, close_ts, 106, swing)


def lower(name: str = "PDL", price: float = 100) -> LiquidityLevel:
    return LiquidityLevel(name, price, LiquiditySide.LOWER)


def _machine(settings):
    machine = SignalStateMachine("BTCUSDT", settings)
    machine.runtime.initialized = True
    return machine


def test_strict_touch_then_bos_then_retest_fires(settings):
    machine = _machine(settings)
    gap = fvg()
    touch_bar = candle(60_000, 101, 102, 99.98, 101)
    assert machine.process_bar(touch_bar, [gap], [lower()]) is None
    assert machine.runtime.state == MachineState.LIQUIDITY_TOUCHED

    bos_bar = candle(120_000, 101, 106, 100, 106)
    assert machine.process_bar(
        bos_bar, [gap], [lower()], bos(bos_bar.close_ts), True
    ) is None
    assert machine.runtime.state == MachineState.BOS_CONFIRMED

    entry = candle(180_000, 96, 97, 93, 94)
    signal = machine.process_bar(entry, [gap], [lower()])
    assert signal is not None
    assert signal.direction.value == "LONG"
    assert signal.liquidity_level == "PDL"
    assert machine.runtime.state == MachineState.SIGNAL_FIRED


def test_bos_before_touch_does_not_count(settings):
    machine = _machine(settings)
    gap = fvg()
    first = candle(60_000, 101, 106, 100.2, 106)
    machine.process_bar(first, [gap], [lower()], bos(first.close_ts), True)
    assert machine.runtime.state == MachineState.IDLE

    touch_bar = candle(120_000, 101, 102, 99.98, 101)
    machine.process_bar(touch_bar, [gap], [lower()])
    entry = candle(180_000, 96, 97, 93, 94)
    assert machine.process_bar(entry, [gap], [lower()]) is None
    assert machine.runtime.state == MachineState.LIQUIDITY_TOUCHED


def test_mitigated_fvg_resets_active_sequence(settings):
    machine = _machine(settings)
    gap = fvg()
    touch_bar = candle(60_000, 101, 102, 99.98, 101)
    machine.process_bar(touch_bar, [gap], [lower()])
    bos_bar = candle(120_000, 101, 106, 100, 106)
    machine.process_bar(bos_bar, [gap], [lower()], bos(bos_bar.close_ts), True)
    gap.mitigated = True
    entry = candle(180_000, 96, 97, 93, 94)
    assert machine.process_bar(entry, [gap], [lower()]) is None
    assert machine.runtime.state == MachineState.IDLE


def test_liquidity_timeout_at_16_bars(settings):
    machine = _machine(settings)
    gap = fvg()
    touch_bar = candle(60_000, 101, 102, 99.98, 101)
    machine.process_bar(touch_bar, [gap], [lower()])
    for index in range(1, 17):
        ts = 60_000 + index * M15_MS
        bar = candle(ts, 101, 102, 100.2, 101)
        machine.process_bar(bar, [gap], [lower()], is_15m_close=True)
    assert machine.runtime.state == MachineState.IDLE


def test_bos_on_17th_bar_cannot_bypass_timeout(settings):
    machine = _machine(settings)
    machine.runtime.day_key = utc_day(0)
    machine.runtime.day_low = 50
    gap = fvg()
    touch_bar = candle(60_000, 101, 102, 99.98, 101)
    machine.process_bar(touch_bar, [gap], [lower()])
    for index in range(1, 17):
        ts = 60_000 + index * M15_MS
        bar = candle(ts, 101, 102, 100.2, 101)
        machine.process_bar(bar, [gap], [lower()], is_15m_close=True)
    seventeenth = candle(60_000 + 17 * M15_MS, 101, 106, 100, 106)
    machine.process_bar(
        seventeenth,
        [gap],
        [lower()],
        bos(seventeenth.close_ts),
        is_15m_close=True,
    )
    assert machine.runtime.state == MachineState.IDLE


def test_entry_timeout_at_8_bars(settings):
    machine = _machine(settings)
    gap = fvg()
    touch_bar = candle(60_000, 101, 102, 99.98, 101)
    machine.process_bar(touch_bar, [gap], [lower()])
    bos_bar = candle(120_000, 101, 106, 100, 106)
    machine.process_bar(bos_bar, [gap], [lower()], bos(bos_bar.close_ts), True)
    for index in range(1, 9):
        ts = 120_000 + index * M15_MS
        neutral = candle(ts, 101, 102, 96, 101)
        machine.process_bar(neutral, [gap], [lower()], is_15m_close=True)
    assert machine.runtime.state == MachineState.IDLE


def test_cooldown_suppresses_new_completed_sequence(settings):
    settings = replace(settings, cooldown_bars_15m=3)
    machine = _machine(settings)
    gap1 = fvg("first")
    touch1 = candle(60_000, 101, 102, 99.98, 101)
    machine.process_bar(touch1, [gap1], [lower("PDL")])
    bos1 = candle(120_000, 101, 106, 100, 106)
    machine.process_bar(bos1, [gap1], [lower("PDL")], bos(bos1.close_ts), True)
    entry1 = candle(180_000, 96, 97, 93, 94)
    assert machine.process_bar(entry1, [gap1], [lower("PDL")]) is not None
    machine.acknowledge_signal()

    gap2 = fvg("second")
    touch2 = candle(240_000, 101, 102, 97.98, 101)
    machine.process_bar(touch2, [gap2], [lower("PWL", 98)])
    bos2 = candle(300_000, 101, 106, 100, 106)
    machine.process_bar(
        bos2, [gap2], [lower("PWL", 98)], bos(bos2.close_ts), True
    )
    blocked = candle(360_000, 96, 97, 93, 94)
    assert machine.process_bar(blocked, [gap2], [lower("PWL", 98)]) is None

    for index in range(3):
        ts = 420_000 + index * M15_MS
        neutral = candle(ts, 96, 97, 95.5, 96)
        machine.process_bar(
            neutral, [gap2], [lower("PWL", 98)], is_15m_close=True
        )
    final_entry = candle(3_200_000, 96, 97, 93, 94)
    assert machine.process_bar(final_entry, [gap2], [lower("PWL", 98)]) is not None


def test_same_level_touches_only_once_per_utc_day(settings):
    machine = _machine(settings)
    gap = fvg()
    first = candle(60_000, 101, 102, 99.98, 101)
    machine.runtime.day_key = utc_day(first.close_ts)
    machine.runtime.day_low = 50
    machine.process_bar(first, [gap], [lower()])
    assert "PDL" in machine.runtime.touched_levels
    machine._reset_sequence()
    second = candle(120_000, 101, 102, 99.98, 101)
    machine.process_bar(second, [gap], [lower()])
    assert machine.runtime.state == MachineState.IDLE

