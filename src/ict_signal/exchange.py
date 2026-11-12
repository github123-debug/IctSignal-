from __future__ import annotations

import asyncio
import time
from typing import Any, Protocol

import httpx

from .models import Candle


INTERVAL_MS = {
    "1m": 60_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}


class MarketDataError(RuntimeError):
    pass


def _request_error_summary(error: Exception | None) -> str:
    if error is None:
        return "unknown error"
    detail = str(error).strip()
    return f"{error.__class__.__name__}: {detail}" if detail else error.__class__.__name__


class MarketDataClient(Protocol):
    async def ping(self) -> None: ...

    async def close(self) -> None: ...

    async def fetch_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[Candle]: ...

    async def fetch_klines_range(
        self, symbol: str, interval: str, start_time: int, end_time: int
    ) -> list[Candle]: ...

    async def discover_symbols(
        self, top_n: int, min_quote_volume: float
    ) -> list[str]: ...


class BinanceUsdmClient:
    def __init__(self, base_url: str, timeout: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers={"User-Agent": "ict-signal-scanner/0.1"},
        )

    async def __aenter__(self) -> "BinanceUsdmClient":
        return self

    async def __aexit__(self, *_args) -> None:
        await self.close()

    async def close(self) -> None:
        await self.client.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                response = await self.client.get(path, params=params)
                if response.status_code == 451:
                    raise MarketDataError(
                        "Binance returned HTTP 451 (regional access restriction). "
                        "Run on a server that can access Binance or configure another adapter."
                    )
                if response.status_code in {418, 429} or response.status_code >= 500:
                    retry_after = float(response.headers.get("Retry-After", 2**attempt))
                    await asyncio.sleep(min(retry_after, 15))
                    continue
                response.raise_for_status()
                return response.json()
            except MarketDataError:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < 3:
                    await asyncio.sleep(2**attempt)
        raise MarketDataError(f"Binance request failed: {last_error}")

    async def ping(self) -> None:
        await self._get("/fapi/v1/ping")

    async def fetch_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[Candle]:
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": min(limit, 1500),
        }
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        rows = await self._get("/fapi/v1/klines", params)
        now_ms = int(time.time() * 1000)
        return [Candle.from_binance(row, now_ms) for row in rows]

    async def fetch_klines_range(
        self, symbol: str, interval: str, start_time: int, end_time: int
    ) -> list[Candle]:
        if interval not in INTERVAL_MS:
            raise ValueError(f"Unsupported interval: {interval}")
        cursor = start_time
        result: list[Candle] = []
        while cursor <= end_time:
            batch = await self.fetch_klines(
                symbol, interval, limit=1500, start_time=cursor, end_time=end_time
            )
            if not batch:
                break
            result.extend(batch)
            next_cursor = batch[-1].ts + INTERVAL_MS[interval]
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if len(batch) < 1500:
                break
            await asyncio.sleep(0.08)
        deduplicated = {bar.ts: bar for bar in result}
        return [deduplicated[key] for key in sorted(deduplicated)]

    async def discover_symbols(
        self, top_n: int, min_quote_volume: float
    ) -> list[str]:
        exchange_info, tickers = await asyncio.gather(
            self._get("/fapi/v1/exchangeInfo"),
            self._get("/fapi/v1/ticker/24hr"),
        )
        eligible = {
            item["symbol"]
            for item in exchange_info.get("symbols", [])
            if item.get("status") == "TRADING"
            and item.get("contractType") == "PERPETUAL"
            and item.get("quoteAsset") == "USDT"
        }
        ranked = sorted(
            (
                (str(item.get("symbol")), float(item.get("quoteVolume", 0)))
                for item in tickers
                if item.get("symbol") in eligible
                and float(item.get("quoteVolume", 0)) >= min_quote_volume
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        return [symbol for symbol, _volume in ranked[:top_n]]


class GateUsdtClient:
    """Gate USDT perpetual public market-data adapter."""

    def __init__(self, base_url: str, timeout: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        # A scan fetches five timeframes per symbol. Limit the aggregate Gate
        # fan-out so transient latency does not turn into connection-pool timeouts.
        self._request_semaphore = asyncio.Semaphore(12)
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            limits=httpx.Limits(
                max_connections=16,
                max_keepalive_connections=8,
                keepalive_expiry=15,
            ),
            headers={
                "Accept": "application/json",
                "User-Agent": "ict-signal-scanner/0.1",
            },
        )

    async def __aenter__(self) -> "GateUsdtClient":
        return self

    async def __aexit__(self, *_args) -> None:
        await self.close()

    async def close(self) -> None:
        await self.client.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                async with self._request_semaphore:
                    response = await self.client.get(path, params=params)
                if response.status_code in {429, 500, 502, 503, 504}:
                    last_error = RuntimeError(f"HTTP {response.status_code}")
                    retry_after = float(response.headers.get("Retry-After", 2**attempt))
                    await asyncio.sleep(min(retry_after, 15))
                    continue
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict) and payload.get("label"):
                    raise MarketDataError(
                        f"Gate rejected request: {payload.get('label')}: "
                        f"{payload.get('message', '')}"
                    )
                return payload
            except MarketDataError:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < 3:
                    await asyncio.sleep(2**attempt)
        raise MarketDataError(
            "Gate request failed after 4 attempts: "
            f"{_request_error_summary(last_error)}"
        )

    @staticmethod
    def _contract(symbol: str) -> str:
        value = symbol.strip().upper()
        if "_" in value:
            return value
        if value.endswith("USDT"):
            return f"{value[:-4]}_USDT"
        return value

    @staticmethod
    def _symbol(contract: str) -> str:
        return contract.replace("_", "").upper()

    @staticmethod
    def _candle(row: dict[str, Any], interval: str, now_ms: int) -> Candle:
        interval_ms = INTERVAL_MS[interval]
        timestamp = int(float(row["t"]) * 1000)
        close_ts = timestamp + interval_ms - 1
        return Candle(
            ts=timestamp,
            open=float(row["o"]),
            high=float(row["h"]),
            low=float(row["l"]),
            close=float(row["c"]),
            volume=float(row.get("sum") or row.get("v") or 0),
            close_ts=close_ts,
            is_closed=close_ts < now_ms,
        )

    async def ping(self) -> None:
        await self._get("/api/v4/futures/usdt/contracts/BTC_USDT")

    async def fetch_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[Candle]:
        if interval not in INTERVAL_MS:
            raise ValueError(f"Unsupported interval: {interval}")
        params: dict[str, Any] = {
            "contract": self._contract(symbol),
            "interval": interval,
            "timezone": "utc0",
        }
        if start_time is None and end_time is None:
            params["limit"] = min(limit, 2000)
        else:
            if start_time is not None:
                params["from"] = start_time // 1000
            if end_time is not None:
                params["to"] = end_time // 1000
            elif start_time is not None:
                params["to"] = int(time.time())
        rows = await self._get("/api/v4/futures/usdt/candlesticks", params)
        if not isinstance(rows, list):
            raise MarketDataError("Gate candlestick response is not a list")
        now_ms = int(time.time() * 1000)
        result = [self._candle(row, interval, now_ms) for row in rows]
        return sorted(result, key=lambda candle: candle.ts)

    async def fetch_klines_range(
        self, symbol: str, interval: str, start_time: int, end_time: int
    ) -> list[Candle]:
        if interval not in INTERVAL_MS:
            raise ValueError(f"Unsupported interval: {interval}")
        interval_ms = INTERVAL_MS[interval]
        cursor = start_time
        result: list[Candle] = []
        while cursor <= end_time:
            chunk_end = min(end_time, cursor + 1999 * interval_ms)
            batch = await self.fetch_klines(
                symbol, interval, start_time=cursor, end_time=chunk_end
            )
            result.extend(batch)
            if chunk_end >= end_time:
                break
            cursor = chunk_end + interval_ms
            await asyncio.sleep(0.08)
        deduplicated = {bar.ts: bar for bar in result}
        return [deduplicated[key] for key in sorted(deduplicated)]

    async def discover_symbols(
        self, top_n: int, min_quote_volume: float
    ) -> list[str]:
        contracts, tickers = await asyncio.gather(
            self._get("/api/v4/futures/usdt/contracts"),
            self._get("/api/v4/futures/usdt/tickers"),
        )
        eligible = {
            item.get("name")
            for item in contracts
            if item.get("status") == "trading"
            and str(item.get("name", "")).endswith("_USDT")
        }
        ranked: list[tuple[str, float]] = []
        for item in tickers:
            contract = str(item.get("contract", ""))
            if contract not in eligible:
                continue
            volume = float(
                item.get("volume_24h_quote")
                or item.get("volume_24h_usd")
                or item.get("volume_24h")
                or 0
            )
            if volume >= min_quote_volume:
                ranked.append((self._symbol(contract), volume))
        ranked.sort(key=lambda item: item[1], reverse=True)
        return [symbol for symbol, _volume in ranked[:top_n]]


def create_market_data_client(settings) -> BinanceUsdmClient | GateUsdtClient:
    if settings.market_data_source == "gate":
        return GateUsdtClient(settings.gate_base_url)
    return BinanceUsdmClient(settings.binance_base_url)

