from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone

from .config import Settings
from .exchange import MarketDataError
from .message import build_signal_message
from .replay import parse_utc, replay_from_market
from .scanner import LiveScanner
from .storage import SignalStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ict-signal", description="ICT ordered Telegram signal scanner"
    )
    parser.add_argument("--env-file", default=".env", help="Path to .env file")
    subparsers = parser.add_subparsers(dest="command", required=True)
    live = subparsers.add_parser("live", help="Run the live scanner")
    live.add_argument("--once", action="store_true", help="Run one polling cycle")
    replay = subparsers.add_parser("replay", help="Replay Binance historical data")
    replay.add_argument("--symbol", required=True)
    replay.add_argument("--start", required=True, help="UTC ISO time")
    replay.add_argument("--end", required=True, help="UTC ISO time")
    signals = subparsers.add_parser("signals", help="Show persisted signals")
    signals.add_argument("--limit", type=int, default=20)
    dashboard = subparsers.add_parser("dashboard", help="Run the monitoring dashboard")
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=8000)
    return parser


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def _live(settings: Settings, once: bool) -> None:
    scanner = LiveScanner(settings)
    try:
        await scanner.run(once=once)
    finally:
        scanner.close()


async def _replay(settings: Settings, symbol: str, start: str, end: str) -> None:
    result = await replay_from_market(
        settings, symbol.upper(), parse_utc(start), parse_utc(end)
    )
    print(f"Replay {result.symbol}: {len(result.signals)} signal(s)")
    for signal in result.signals:
        moment = datetime.fromtimestamp(signal.signal_ts / 1000, timezone.utc).isoformat()
        print(f"\n[{moment}]\n{build_signal_message(signal)}")


def _signals(settings: Settings, limit: int) -> None:
    with SignalStore(settings.database_path) as store:
        rows = store.recent_signals(limit)
    for row in rows:
        moment = datetime.fromtimestamp(row["signal_ts"] / 1000, timezone.utc).isoformat()
        print(
            f"{moment} {row['symbol']} {row['direction']} "
            f"{row['liquidity_level']} {row['delivery_status']} {row['fingerprint']}"
        )


def main() -> None:
    args = _parser().parse_args()
    settings = Settings.from_env(args.env_file)
    _configure_logging(settings.log_level)
    if args.command == "live":
        try:
            asyncio.run(_live(settings, args.once))
        except MarketDataError as exc:
            print(f"Market data error: {exc}", file=sys.stderr)
            raise SystemExit(2) from None
    elif args.command == "replay":
        try:
            asyncio.run(_replay(settings, args.symbol, args.start, args.end))
        except MarketDataError as exc:
            print(f"Market data error: {exc}", file=sys.stderr)
            raise SystemExit(2) from None
    elif args.command == "signals":
        _signals(settings, args.limit)
    elif args.command == "dashboard":
        from .dashboard import run_dashboard

        run_dashboard(settings, args.host, args.port)


if __name__ == "__main__":
    main()

