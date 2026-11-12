from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from ict_signal.exchange import GateUsdtClient, MarketDataError
from ict_signal.models import MINUTE_MS


def test_gate_contract_and_candle_conversion():
    assert GateUsdtClient._contract("BTCUSDT") == "BTC_USDT"
    assert GateUsdtClient._contract("BTC_USDT") == "BTC_USDT"
    assert GateUsdtClient._symbol("1000PEPE_USDT") == "1000PEPEUSDT"
    row = {
        "t": 1_700_000_000,
        "o": "100",
        "h": "105",
        "l": "99",
        "c": "104",
        "v": "25",
        "sum": "2600",
    }
    candle = GateUsdtClient._candle(
        row, "1m", now_ms=1_700_000_000_000 + MINUTE_MS
    )
    assert candle.ts == 1_700_000_000_000
    assert candle.close_ts == candle.ts + MINUTE_MS - 1
    assert candle.volume == 2600
    assert candle.is_closed


@pytest.mark.asyncio
async def test_gate_discovery_filters_active_contracts_and_ranks_volume():
    client = GateUsdtClient("https://example.test")
    client._get = AsyncMock(
        side_effect=[
            [
                {"name": "BTC_USDT", "status": "trading", "contract_type": ""},
                {"name": "ETH_USDT", "status": "trading", "contract_type": ""},
                {"name": "OLD_USDT", "status": "delisted", "contract_type": ""},
                {"name": "BTC_USD", "status": "trading", "contract_type": ""},
                {"name": "NVDA_USDT", "status": "trading", "contract_type": "stocks"},
            ],
            [
                {"contract": "ETH_USDT", "volume_24h_quote": "20000000"},
                {"contract": "BTC_USDT", "volume_24h_quote": "50000000"},
                {"contract": "OLD_USDT", "volume_24h_quote": "90000000"},
                {"contract": "NVDA_USDT", "volume_24h_quote": "80000000"},
            ],
        ]
    )
    try:
        symbols = await client.discover_symbols(10, 10_000_000)
    finally:
        await client.close()
    assert symbols == ["NVDAUSDT", "BTCUSDT", "ETHUSDT"]


@pytest.mark.asyncio
async def test_gate_timeout_error_includes_exception_type(monkeypatch):
    client = GateUsdtClient("https://example.test")
    client.client.get = AsyncMock(side_effect=httpx.ReadTimeout(""))
    monkeypatch.setattr("ict_signal.exchange.asyncio.sleep", AsyncMock())
    try:
        with pytest.raises(MarketDataError, match="ReadTimeout"):
            await client._get("/candlesticks")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gate_retryable_status_is_reported(monkeypatch):
    client = GateUsdtClient("https://example.test")
    request = httpx.Request("GET", "https://example.test/candlesticks")
    client.client.get = AsyncMock(return_value=httpx.Response(503, request=request))
    monkeypatch.setattr("ict_signal.exchange.asyncio.sleep", AsyncMock())
    try:
        with pytest.raises(MarketDataError, match="HTTP 503"):
            await client._get("/candlesticks")
    finally:
        await client.close()

