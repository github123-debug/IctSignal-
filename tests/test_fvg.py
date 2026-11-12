from __future__ import annotations

from dataclasses import replace

from ict_signal.fvg import closest_usable_fvg, detect_fvgs
from ict_signal.models import FvgDirection, HOUR_MS

from conftest import candle


def test_document_definition_and_closed_candle_only(settings):
    bars = [
        candle(0, 105, 110, 100, 106, HOUR_MS),
        candle(HOUR_MS, 102, 105, 97, 99, HOUR_MS),
        candle(2 * HOUR_MS, 95, 99, 90, 92, HOUR_MS),
        candle(3 * HOUR_MS, 90, 94, 88, 91, HOUR_MS, closed=False),
    ]
    found = detect_fvgs(bars, settings, bars[2].close_ts)
    assert len(found) == 1
    gap = found[0]
    assert gap.direction == FvgDirection.BULL
    assert (gap.lower, gap.upper) == (99, 100)
    assert gap.formed_at == HOUR_MS
    assert gap.confirmed_at == bars[2].close_ts
    assert gap.usable


def test_classic_definition_flips_gap_direction(settings):
    settings = replace(settings, fvg_definition="classic")
    bars = [
        candle(0, 105, 110, 100, 106, HOUR_MS),
        candle(HOUR_MS, 102, 105, 97, 99, HOUR_MS),
        candle(2 * HOUR_MS, 95, 99, 90, 92, HOUR_MS),
    ]
    found = detect_fvgs(bars, settings, bars[-1].close_ts)
    assert found[0].direction == FvgDirection.BEAR


def test_close_mitigation_ignores_wick_but_accepts_close(settings):
    base = [
        candle(0, 105, 110, 100, 106, HOUR_MS),
        candle(HOUR_MS, 102, 105, 97, 99, HOUR_MS),
        candle(2 * HOUR_MS, 95, 99, 90, 92, HOUR_MS),
    ]
    wick = candle(3 * HOUR_MS, 101, 102, 98, 100, HOUR_MS)
    assert not detect_fvgs(base + [wick], settings, wick.close_ts)[0].mitigated
    accepted = candle(4 * HOUR_MS, 100, 101, 97, 98, HOUR_MS)
    assert detect_fvgs(base + [wick, accepted], settings, accepted.close_ts)[0].mitigated


def test_expiration_and_emitted_status(settings):
    bars = [
        candle(0, 105, 110, 100, 106, HOUR_MS),
        candle(HOUR_MS, 102, 105, 97, 99, HOUR_MS),
        candle(2 * HOUR_MS, 95, 99, 90, 92, HOUR_MS),
    ]
    found = detect_fvgs(
        bars,
        settings,
        HOUR_MS + settings.fvg_max_age_hours * HOUR_MS,
        {"bull_1H_19700101_0100"},
    )
    assert found[0].expired
    assert found[0].signal_emitted
    assert not found[0].usable


def test_closest_candidate_uses_directional_boundary(settings):
    from conftest import fvg

    near = fvg("near", lower=98, upper=99)
    far = fvg("far", lower=80, upper=90)
    assert closest_usable_fvg([far, near], FvgDirection.BULL, 100) is near

