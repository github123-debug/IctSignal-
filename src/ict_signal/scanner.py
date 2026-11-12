from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from .config import Settings
from .exchange import MarketDataClient, MarketDataError, create_market_data_client
from .fvg import detect_fvgs
from .liquidity import fixed_liquidity_levels
from .message import build_signal_message
from .state_machine import SignalStateMachine
from .storage import SignalStore
from .structure import latest_bos_event
from .telegram import TelegramSender


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class MarketSnapshot:
    m1: list
    m15: list
    h1: list
    d1: list
    w1: list


class LiveScanner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = SignalStore(settings.database_path)
        self.engines: dict[str, SignalStateMachine] = {}
        self.sender = (
            TelegramSender(settings.tg_bot_token, settings.tg_chat_id)
            if settings.telegram_enabled
            else None
        )

    async def run(self, once: bool = False) -> None:
        async with create_market_data_client(self.settings) as client:
            await client.ping()
            symbols = await self._symbols(client)
            if not symbols:
                raise RuntimeError("No symbols matched the configured scanner universe")
            LOGGER.info("Scanning %d symbols: %s", len(symbols), ", ".join(symbols))
            while True:
                started = time.monotonic()
                semaphore = asyncio.Semaphore(self.settings.max_concurrency)

                async def guarded(symbol: str) -> None:
                    async with semaphore:
                        try:
                            await self._scan_symbol(client, symbol)
                        except MarketDataError as exc:
                            LOGGER.warning(
                                "Market data temporarily unavailable for %s; "
                                "skipped this cycle: %s",
                                symbol,
                                exc,
                            )
                        except Exception:
                            LOGGER.exception("Scan failed for %s", symbol)

                await asyncio.gather(*(guarded(symbol) for symbol in symbols))
                if once:
                    return
                elapsed = time.monotonic() - started
                await asyncio.sleep(max(1, self.settings.poll_seconds - elapsed))

    async def _symbols(self, client: MarketDataClient) -> list[str]:
        if self.settings.symbols:
            return list(self.settings.symbols)
        return await client.discover_symbols(
            self.settings.top_n, self.settings.min_quote_volume_usdt
        )

    def _engine(self, symbol: str) -> SignalStateMachine:
        if symbol not in self.engines:
            runtime = self.store.load_runtime(symbol)
            self.engines[symbol] = SignalStateMachine(
                symbol, self.settings, runtime=runtime
            )
        return self.engines[symbol]

    async def _fetch_snapshot(
        self, client: MarketDataClient, symbol: str, engine: SignalStateMachine
    ) -> MarketSnapshot:
        runtime = engine.runtime
        if runtime.initialized and runtime.last_1m_ts:
            m1_request = client.fetch_klines_range(
                symbol,
                "1m",
                runtime.last_1m_ts + 60_000,
                int(time.time() * 1000),
            )
        else:
            m1_request = client.fetch_klines(symbol, "1m", limit=1500)
        m1, m15, h1, d1, w1 = await asyncio.gather(
            m1_request,
            client.fetch_klines(symbol, "15m", limit=200),
            client.fetch_klines(symbol, "1h", limit=60),
            client.fetch_klines(symbol, "1d", limit=5),
            client.fetch_klines(symbol, "1w", limit=5),
        )
        return MarketSnapshot(m1=m1, m15=m15, h1=h1, d1=d1, w1=w1)

    async def _scan_symbol(
        self, client: MarketDataClient, symbol: str
    ) -> None:
        engine = self._engine(symbol)
        snapshot = await self._fetch_snapshot(client, symbol, engine)
        closed_m1 = [bar for bar in snapshot.m1 if bar.is_closed]
        if not closed_m1:
            return
        if not engine.runtime.initialized:
            engine.bootstrap(closed_m1)
            self.store.save_runtime(engine.runtime)
            LOGGER.info("%s baseline initialized at %d", symbol, engine.runtime.last_1m_ts)
            return

        emitted_ids = self.store.emitted_fvg_ids(symbol)
        for bar in sorted(closed_m1, key=lambda item: item.ts):
            if bar.ts <= engine.runtime.last_1m_ts:
                continue
            fvgs = detect_fvgs(snapshot.h1, self.settings, bar.close_ts, emitted_ids)
            levels = fixed_liquidity_levels(snapshot.d1, snapshot.w1, bar.close_ts)
            available_m15 = [
                candle
                for candle in snapshot.m15
                if candle.is_closed and candle.close_ts <= bar.close_ts
            ]
            matching_15m = bool(
                available_m15 and available_m15[-1].close_ts == bar.close_ts
            )
            bos = (
                latest_bos_event(
                    available_m15,
                    self.settings.bos_swing_window,
                    self.settings.bos_atr_period,
                    self.settings.bos_min_atr_mult,
                )
                if matching_15m
                else None
            )
            signal = engine.process_bar(
                bar,
                fvgs,
                levels,
                bos_event=bos,
                is_15m_close=matching_15m,
            )
            if signal is not None:
                message = build_signal_message(signal)
                if self.store.record_signal(signal, message):
                    emitted_ids.add(signal.fvg.fvg_id)
                    await self._deliver(signal.fingerprint, signal.signal_ts, message)
                engine.acknowledge_signal()
        self.store.save_runtime(engine.runtime)

    async def _deliver(self, fingerprint: str, signal_ts: int, message: str) -> None:
        age_ms = int(time.time() * 1000) - signal_ts
        if age_ms > self.settings.stale_signal_minutes * 60_000:
            LOGGER.warning("Historical/stale signal recorded but not sent:\n%s", message)
            self.store.set_delivery(fingerprint, "stale")
            return
        if self.sender is None:
            LOGGER.warning("Telegram disabled; signal recorded:\n%s", message)
            self.store.set_delivery(fingerprint, "disabled")
            return
        try:
            await self.sender.send(message)
        except Exception as exc:
            LOGGER.exception("Telegram delivery failed")
            self.store.set_delivery(fingerprint, "failed", str(exc))
        else:
            self.store.set_delivery(fingerprint, "sent")

    def close(self) -> None:
        self.store.close()

