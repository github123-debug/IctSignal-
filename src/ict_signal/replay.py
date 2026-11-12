from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import Settings
from .exchange import create_market_data_client
from .fvg import detect_fvgs
from .liquidity import day_start_ms, fixed_liquidity_levels
from .models import Signal
from .state_machine import SignalStateMachine
from .structure import latest_bos_event


UTC = timezone.utc


def parse_utc(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.astimezone(UTC).timestamp() * 1000)


@dataclass(slots=True)
class ReplayResult:
    symbol: str
    start_ts: int
    end_ts: int
    signals: list[Signal]


async def replay_from_market(
    settings: Settings, symbol: str, start_ts: int, end_ts: int
) -> ReplayResult:
    day_ms = 86_400_000
    m1_start = day_start_ms(start_ts)
    async with create_market_data_client(settings) as client:
        m1, m15, h1, d1, w1 = await asyncio.gather(
            client.fetch_klines_range(symbol, "1m", m1_start, end_ts),
            client.fetch_klines_range(symbol, "15m", start_ts - 2 * day_ms, end_ts),
            client.fetch_klines_range(symbol, "1h", start_ts - 3 * day_ms, end_ts),
            client.fetch_klines_range(symbol, "1d", start_ts - 7 * day_ms, end_ts),
            client.fetch_klines_range(symbol, "1w", start_ts - 28 * day_ms, end_ts),
        )

    engine = SignalStateMachine(symbol, settings)
    # Build the current UTC day's extremes up to (but not including) the replay.
    baseline = [bar for bar in m1 if bar.is_closed and bar.close_ts < start_ts]
    if baseline:
        engine.bootstrap(baseline)
    else:
        engine.runtime.day_key = datetime.fromtimestamp(
            start_ts / 1000, UTC
        ).date().isoformat()
        engine.runtime.initialized = True
        engine.runtime.last_1m_ts = start_ts - 60_000
    signals: list[Signal] = []
    emitted_ids: set[str] = set()

    for bar in m1:
        if not bar.is_closed or not start_ts <= bar.close_ts <= end_ts:
            continue
        fvgs = detect_fvgs(h1, settings, bar.close_ts, emitted_ids)
        levels = fixed_liquidity_levels(d1, w1, bar.close_ts)
        available_m15 = [item for item in m15 if item.is_closed and item.close_ts <= bar.close_ts]
        matching = bool(available_m15 and available_m15[-1].close_ts == bar.close_ts)
        bos = (
            latest_bos_event(
                available_m15,
                settings.bos_swing_window,
                settings.bos_atr_period,
                settings.bos_min_atr_mult,
            )
            if matching
            else None
        )
        signal = engine.process_bar(bar, fvgs, levels, bos, matching)
        if signal:
            signals.append(signal)
            emitted_ids.add(signal.fvg.fvg_id)
            engine.acknowledge_signal()
    return ReplayResult(symbol, start_ts, end_ts, signals)


# Backward-compatible import for callers using the original name.
replay_from_binance = replay_from_market

