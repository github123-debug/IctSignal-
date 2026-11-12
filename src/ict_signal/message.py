from __future__ import annotations

from .models import FvgDirection, Signal, TradeDirection


def _display_symbol(symbol: str) -> str:
    for suffix in ("USDT", "USDC", "BUSD"):
        if symbol.endswith(suffix):
            return symbol[: -len(suffix)]
    return symbol


def _price(value: float) -> str:
    if value >= 100:
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return f"{value:,.8f}".rstrip("0").rstrip(".")


def build_signal_message(signal: Signal) -> str:
    emoji = "🟢" if signal.direction == TradeDirection.LONG else "🔴"
    fvg_label = "Bullish" if signal.fvg.direction == FvgDirection.BULL else "Bearish"
    age_ms = max(0, signal.signal_ts - signal.fvg.formed_at)
    if age_ms >= 3_600_000:
        fvg_age = f"{int(age_ms / 3_600_000)}H前"
    else:
        fvg_age = f"{int(age_ms / 60_000)}M前"
    symbol = _display_symbol(signal.symbol)
    return "\n".join(
        [
            f"🔥 ICT SIGNAL | {symbol}",
            "",
            f"方向：{emoji} {signal.direction.value}",
            "",
            f"📍 1H FVG：{fvg_label}",
            f"📍 FVG形成：{fvg_age}",
            f"📍 关键流动性：{signal.liquidity_level}",
            f"📍 15M：{fvg_label} BOS",
            "",
            f"💰 当前价格：{_price(signal.signal_price)}",
            "",
            "⚡ 条件：3/3",
            "",
            f"#{symbol} #ICT",
        ]
    )

