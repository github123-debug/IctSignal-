from __future__ import annotations

from ict_signal.message import build_signal_message
from ict_signal.models import Signal, TradeDirection
from ict_signal.state_machine import RuntimeState
from ict_signal.storage import SignalStore

from conftest import fvg


def _signal() -> Signal:
    gap = fvg()
    return Signal(
        fingerprint="BTCUSDT_LONG_gap_PDL_1",
        symbol="BTCUSDT",
        direction=TradeDirection.LONG,
        fvg=gap,
        liquidity_level="PDL",
        bos_bar_ts=100,
        signal_bar_ts=200,
        signal_ts=6 * 3_600_000,
        signal_price=78_520,
    )


def test_message_matches_required_fields():
    message = build_signal_message(_signal())
    assert "🔥 ICT SIGNAL | BTC" in message
    assert "方向：🟢 LONG" in message
    assert "FVG形成：6H前" in message
    assert "关键流动性：PDL" in message
    assert "当前价格：78,520" in message
    assert "#BTC #ICT" in message


def test_fingerprint_and_runtime_survive_restart(tmp_path):
    path = tmp_path / "signals.db"
    signal = _signal()
    message = build_signal_message(signal)
    with SignalStore(path) as first:
        assert first.record_signal(signal, message)
        assert not first.record_signal(signal, message)
        runtime = RuntimeState(symbol="BTCUSDT", initialized=True, last_1m_ts=123)
        runtime.touched_levels.add("PDL")
        first.save_runtime(runtime)

    with SignalStore(path) as second:
        assert signal.fvg.fvg_id in second.emitted_fvg_ids("BTCUSDT")
        loaded = second.load_runtime("BTCUSDT")
        assert loaded is not None
        assert loaded.last_1m_ts == 123
        assert loaded.touched_levels == {"PDL"}

