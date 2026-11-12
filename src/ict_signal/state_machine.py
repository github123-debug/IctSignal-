from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from .config import Settings
from .fvg import closest_usable_fvg
from .liquidity import touched, utc_day
from .models import (
    BosEvent,
    Candle,
    FVG,
    FvgDirection,
    LiquidityLevel,
    LiquiditySide,
    MachineState,
    Signal,
)


@dataclass(slots=True)
class RuntimeState:
    symbol: str
    state: MachineState = MachineState.IDLE
    trigger_fvg: FVG | None = None
    trigger_liquidity_level: str | None = None
    touch_bar_ts: int | None = None
    touch_ts: int | None = None
    bos_bar_ts: int | None = None
    bos_ts: int | None = None
    liquidity_wait_bars: int = 0
    entry_wait_bars: int = 0
    cooldown_bars_remaining: int = 0
    day_key: str | None = None
    day_high: float | None = None
    day_low: float | None = None
    touched_levels: set[str] = field(default_factory=set)
    invalidated_levels: set[str] = field(default_factory=set)
    last_1m_ts: int = 0
    initialized: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        data["trigger_fvg"] = self.trigger_fvg.to_dict() if self.trigger_fvg else None
        data["touched_levels"] = sorted(self.touched_levels)
        data["invalidated_levels"] = sorted(self.invalidated_levels)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuntimeState":
        values = dict(data)
        values["state"] = MachineState(values["state"])
        if values.get("trigger_fvg"):
            values["trigger_fvg"] = FVG.from_dict(values["trigger_fvg"])
        values["touched_levels"] = set(values.get("touched_levels", []))
        values["invalidated_levels"] = set(values.get("invalidated_levels", []))
        return cls(**values)


class SignalStateMachine:
    def __init__(
        self, symbol: str, settings: Settings, runtime: RuntimeState | None = None
    ) -> None:
        self.settings = settings
        self.runtime = runtime or RuntimeState(symbol=symbol)

    def bootstrap(self, candles_1m: Iterable[Candle]) -> None:
        closed = sorted(
            (bar for bar in candles_1m if bar.is_closed), key=lambda bar: bar.ts
        )
        if not closed:
            return
        latest = closed[-1]
        day = utc_day(latest.close_ts)
        same_day = [bar for bar in closed if utc_day(bar.close_ts) == day]
        self.runtime.day_key = day
        self.runtime.day_high = max(bar.high for bar in same_day)
        self.runtime.day_low = min(bar.low for bar in same_day)
        self.runtime.last_1m_ts = latest.ts
        self.runtime.initialized = True

    def process_bar(
        self,
        bar: Candle,
        fvgs: Iterable[FVG],
        fixed_levels: Iterable[LiquidityLevel],
        bos_event: BosEvent | None = None,
        is_15m_close: bool = False,
    ) -> Signal | None:
        if not bar.is_closed or bar.ts <= self.runtime.last_1m_ts:
            return None
        self._rotate_day(bar.close_ts)
        current_fvgs = {fvg.fvg_id: fvg for fvg in fvgs}
        self._refresh_active_fvg(current_fvgs)

        levels = list(fixed_levels)
        self._invalidate_fixed_levels(bar, levels)
        if self.runtime.state == MachineState.IDLE:
            self._try_start_sequence(bar, current_fvgs.values(), levels)

        just_confirmed_bos = False
        if (
            self.runtime.state == MachineState.LIQUIDITY_TOUCHED
            and bos_event is not None
            and self.runtime.trigger_fvg is not None
            and bos_event.direction == self.runtime.trigger_fvg.direction
            and self.runtime.touch_ts is not None
            and bos_event.close_ts > self.runtime.touch_ts
            and self.runtime.liquidity_wait_bars
            < self.settings.bos_timeout_bars_15m
        ):
            self.runtime.state = MachineState.BOS_CONFIRMED
            self.runtime.bos_bar_ts = bos_event.bar_ts
            self.runtime.bos_ts = bos_event.close_ts
            self.runtime.entry_wait_bars = 0
            just_confirmed_bos = True

        signal = None
        if not just_confirmed_bos:
            signal = self._try_fire_signal(bar, current_fvgs)

        if is_15m_close and signal is None:
            if self.runtime.cooldown_bars_remaining > 0:
                self.runtime.cooldown_bars_remaining -= 1
            self._advance_timeouts(bar.close_ts, just_confirmed_bos)

        self._update_day_extremes(bar)
        self.runtime.last_1m_ts = bar.ts
        return signal

    def acknowledge_signal(self) -> None:
        if self.runtime.state == MachineState.SIGNAL_FIRED:
            self._reset_sequence()

    def _rotate_day(self, timestamp: int) -> None:
        day = utc_day(timestamp)
        if day == self.runtime.day_key:
            return
        self.runtime.day_key = day
        self.runtime.day_high = None
        self.runtime.day_low = None
        self.runtime.touched_levels.clear()
        self.runtime.invalidated_levels.clear()

    def _refresh_active_fvg(self, by_id: dict[str, FVG]) -> None:
        if self.runtime.trigger_fvg is None:
            return
        refreshed = by_id.get(self.runtime.trigger_fvg.fvg_id)
        if refreshed is None or not refreshed.usable:
            self._reset_sequence()
            return
        self.runtime.trigger_fvg = refreshed

    def _invalidate_fixed_levels(
        self, bar: Candle, levels: Iterable[LiquidityLevel]
    ) -> None:
        tolerance = self.settings.liquidity_tolerance_pct
        for level in levels:
            if level.side == LiquiditySide.LOWER:
                invalid = bar.close < level.price * (1 - tolerance)
            else:
                invalid = bar.close > level.price * (1 + tolerance)
            if invalid:
                self.runtime.invalidated_levels.add(level.name)

    def _try_start_sequence(
        self, bar: Candle, fvgs: Iterable[FVG], fixed_levels: list[LiquidityLevel]
    ) -> None:
        levels = list(fixed_levels)
        if self.runtime.day_low is not None:
            levels.append(
                LiquidityLevel("Day Low", self.runtime.day_low, LiquiditySide.LOWER)
            )
        if self.runtime.day_high is not None:
            levels.append(
                LiquidityLevel("Day High", self.runtime.day_high, LiquiditySide.UPPER)
            )

        options: list[tuple[float, FVG, LiquidityLevel]] = []
        for direction, side in (
            (FvgDirection.BULL, LiquiditySide.LOWER),
            (FvgDirection.BEAR, LiquiditySide.UPPER),
        ):
            candidate = closest_usable_fvg(fvgs, direction, bar.close)
            if candidate is None or candidate.confirmed_at >= bar.close_ts:
                continue
            for level in levels:
                if level.side != side:
                    continue
                if level.name in self.runtime.touched_levels:
                    continue
                if level.name in self.runtime.invalidated_levels:
                    continue
                if touched(
                    level.price,
                    bar.high,
                    bar.low,
                    self.settings.liquidity_tolerance_pct,
                ):
                    # A 1M OHLC bar cannot reveal ordering if both sides are hit.
                    # Distance from the open is the deterministic tie-breaker.
                    options.append((abs(bar.open - level.price), candidate, level))
        if not options:
            return
        _, fvg, level = min(
            options,
            key=lambda item: (item[0], item[1].confirmed_at, item[2].name),
        )
        self.runtime.state = MachineState.LIQUIDITY_TOUCHED
        self.runtime.trigger_fvg = fvg
        self.runtime.trigger_liquidity_level = level.name
        self.runtime.touch_bar_ts = bar.ts
        self.runtime.touch_ts = bar.close_ts
        self.runtime.liquidity_wait_bars = 0
        self.runtime.touched_levels.add(level.name)

    def _try_fire_signal(
        self, bar: Candle, current_fvgs: dict[str, FVG]
    ) -> Signal | None:
        runtime = self.runtime
        if (
            runtime.state != MachineState.BOS_CONFIRMED
            or runtime.trigger_fvg is None
            or runtime.bos_ts is None
            or bar.close_ts <= runtime.bos_ts
        ):
            return None
        if runtime.entry_wait_bars >= self.settings.entry_timeout_bars_15m:
            self._reset_sequence()
            return None
        fvg = current_fvgs.get(runtime.trigger_fvg.fvg_id)
        if fvg is None or not fvg.usable:
            self._reset_sequence()
            return None
        if fvg.direction == FvgDirection.BULL:
            entered = bar.low <= fvg.upper and bar.low >= fvg.lower
        else:
            entered = bar.high >= fvg.lower and bar.high <= fvg.upper
        if not entered or runtime.cooldown_bars_remaining > 0:
            return None

        direction = fvg.trade_direction
        fingerprint = (
            f"{runtime.symbol}_{direction.value}_{fvg.fvg_id}_"
            f"{runtime.trigger_liquidity_level}_{bar.ts // 900_000}"
        )
        signal = Signal(
            fingerprint=fingerprint,
            symbol=runtime.symbol,
            direction=direction,
            fvg=fvg,
            liquidity_level=runtime.trigger_liquidity_level or "UNKNOWN",
            bos_bar_ts=runtime.bos_bar_ts or runtime.bos_ts,
            signal_bar_ts=bar.ts,
            signal_ts=bar.close_ts,
            signal_price=bar.close,
        )
        runtime.state = MachineState.SIGNAL_FIRED
        runtime.cooldown_bars_remaining = self.settings.cooldown_bars_15m
        return signal

    def _advance_timeouts(self, close_ts: int, just_confirmed_bos: bool) -> None:
        runtime = self.runtime
        if (
            runtime.state == MachineState.LIQUIDITY_TOUCHED
            and runtime.touch_ts is not None
            and close_ts > runtime.touch_ts
        ):
            runtime.liquidity_wait_bars += 1
            if runtime.liquidity_wait_bars >= self.settings.bos_timeout_bars_15m:
                self._reset_sequence()
        elif (
            runtime.state == MachineState.BOS_CONFIRMED
            and not just_confirmed_bos
            and runtime.bos_ts is not None
            and close_ts > runtime.bos_ts
        ):
            runtime.entry_wait_bars += 1
            if runtime.entry_wait_bars >= self.settings.entry_timeout_bars_15m:
                self._reset_sequence()

    def _update_day_extremes(self, bar: Candle) -> None:
        self.runtime.day_high = (
            bar.high
            if self.runtime.day_high is None
            else max(self.runtime.day_high, bar.high)
        )
        self.runtime.day_low = (
            bar.low
            if self.runtime.day_low is None
            else min(self.runtime.day_low, bar.low)
        )

    def _reset_sequence(self) -> None:
        runtime = self.runtime
        runtime.state = MachineState.IDLE
        runtime.trigger_fvg = None
        runtime.trigger_liquidity_level = None
        runtime.touch_bar_ts = None
        runtime.touch_ts = None
        runtime.bos_bar_ts = None
        runtime.bos_ts = None
        runtime.liquidity_wait_bars = 0
        runtime.entry_wait_bars = 0

