from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import psutil
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .telegram import TelegramSender


UTC = timezone.utc
BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")
WEB_DIR = Path(__file__).with_name("web")


def _utc_iso(value: str | None) -> str | None:
    if not value:
        return None
    if value.endswith("Z"):
        return value
    return f"{value.replace(' ', 'T')}Z"


def _ts_iso(value: int | None) -> str | None:
    if not value:
        return None
    return datetime.fromtimestamp(value / 1000, UTC).isoformat().replace("+00:00", "Z")


class ProcessController:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.data_dir = workspace / "data"
        self.pid_path = self.data_dir / "scanner.pid"
        self.stdout_path = self.data_dir / "scanner.stdout.log"
        self.stderr_path = self.data_dir / "scanner.stderr.log"
        self._lock = threading.Lock()

    def _pid(self) -> int | None:
        try:
            return int(self.pid_path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            return None

    def _process(self) -> psutil.Process | None:
        pid = self._pid()
        if not pid:
            return None
        try:
            process = psutil.Process(pid)
            if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
                return None
            command = " ".join(process.cmdline()).lower()
            if "ict-signal" not in command and "ict_signal" not in command:
                return None
            return process
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return None

    def status(self) -> dict[str, Any]:
        process = self._process()
        if process is None:
            return {"running": False, "pid": None, "started_at": None, "uptime_seconds": 0}
        try:
            created = process.create_time()
            return {
                "running": True,
                "pid": process.pid,
                "started_at": datetime.fromtimestamp(created, UTC).isoformat().replace(
                    "+00:00", "Z"
                ),
                "uptime_seconds": max(0, int(time.time() - created)),
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return {"running": False, "pid": None, "started_at": None, "uptime_seconds": 0}

    def start(self) -> dict[str, Any]:
        with self._lock:
            current = self._process()
            if current is not None:
                return self.status()
            self.data_dir.mkdir(parents=True, exist_ok=True)
            stdout = self.stdout_path.open("a", encoding="utf-8")
            stderr = self.stderr_path.open("a", encoding="utf-8")
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            environment = os.environ.copy()
            environment["PYTHONIOENCODING"] = "utf-8"
            process = subprocess.Popen(
                [sys.executable, "-m", "ict_signal", "live"],
                cwd=self.workspace,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                env=environment,
                creationflags=flags,
                close_fds=True,
            )
            stdout.close()
            stderr.close()
            self.pid_path.write_text(str(process.pid), encoding="ascii")
            time.sleep(0.25)
            if process.poll() is not None:
                raise RuntimeError("扫描进程启动后立即退出，请查看运行日志")
            return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            process = self._process()
            if process is None:
                return self.status()
            process.terminate()
            try:
                process.wait(timeout=8)
            except psutil.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            return self.status()

    def restart(self) -> dict[str, Any]:
        self.stop()
        return self.start()


class DashboardData:
    def __init__(self, settings: Settings, workspace: Path) -> None:
        self.settings = settings
        self.workspace = workspace
        self.database = (
            settings.database_path
            if settings.database_path.is_absolute()
            else workspace / settings.database_path
        )
        self.process = ProcessController(workspace)
        self._market_cache: tuple[float, dict[str, dict[str, Any]]] = (0, {})
        self._market_lock = asyncio.Lock()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def states(self) -> list[dict[str, Any]]:
        if not self.database.exists():
            return []
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT symbol, payload, updated_at FROM runtime_state ORDER BY symbol"
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(row["payload"])
            fvg = payload.get("trigger_fvg") or {}
            result.append(
                {
                    "symbol": row["symbol"],
                    "state": payload.get("state", "IDLE"),
                    "initialized": bool(payload.get("initialized")),
                    "liquidity_level": payload.get("trigger_liquidity_level"),
                    "touch_ts": _ts_iso(payload.get("touch_ts")),
                    "bos_ts": _ts_iso(payload.get("bos_ts")),
                    "liquidity_wait_bars": payload.get("liquidity_wait_bars", 0),
                    "entry_wait_bars": payload.get("entry_wait_bars", 0),
                    "cooldown_bars": payload.get("cooldown_bars_remaining", 0),
                    "day_high": payload.get("day_high"),
                    "day_low": payload.get("day_low"),
                    "last_bar_ts": _ts_iso(payload.get("last_1m_ts")),
                    "updated_at": _utc_iso(row["updated_at"]),
                    "touched_levels": payload.get("touched_levels", []),
                    "invalidated_levels": payload.get("invalidated_levels", []),
                    "fvg": (
                        {
                            "id": fvg.get("fvg_id"),
                            "direction": fvg.get("direction"),
                            "lower": fvg.get("lower"),
                            "upper": fvg.get("upper"),
                            "formed_at": _ts_iso(fvg.get("formed_at")),
                        }
                        if fvg
                        else None
                    ),
                }
            )
        return result

    def signals(self, limit: int) -> list[dict[str, Any]]:
        if not self.database.exists():
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT fingerprint, symbol, direction, fvg_id, liquidity_level,
                       signal_ts, signal_price, message, delivery_status,
                       delivery_error, created_at
                FROM signals ORDER BY signal_ts DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                **dict(row),
                "signal_at": _ts_iso(row["signal_ts"]),
                "created_at": _utc_iso(row["created_at"]),
            }
            for row in rows
        ]

    def overview(self) -> dict[str, Any]:
        states = self.states()
        state_counts = Counter(item["state"] for item in states)
        cooldown = sum(1 for item in states if item["cooldown_bars"] > 0)
        signals = self.signals(500)
        today = datetime.now(UTC).date()
        signals_today = sum(
            1
            for item in signals
            if item["signal_at"]
            and datetime.fromisoformat(item["signal_at"].replace("Z", "+00:00")).date()
            == today
        )
        updated = max((item["updated_at"] or "" for item in states), default="") or None
        return {
            "scanner": self.process.status(),
            "source": self.settings.market_data_source,
            "telegram_configured": bool(
                self.settings.telegram_enabled
                and self.settings.tg_bot_token
                and self.settings.tg_chat_id
            ),
            "contract_count": len(states),
            "signal_count": len(signals),
            "signals_today": signals_today,
            "last_update": updated,
            "state_counts": {
                "IDLE": state_counts.get("IDLE", 0),
                "LIQUIDITY_TOUCHED": state_counts.get("LIQUIDITY_TOUCHED", 0),
                "BOS_CONFIRMED": state_counts.get("BOS_CONFIRMED", 0),
                "SIGNAL_FIRED": state_counts.get("SIGNAL_FIRED", 0),
                "COOLDOWN": cooldown,
            },
        }

    def config(self) -> dict[str, Any]:
        settings = self.settings
        return {
            "market_data_source": settings.market_data_source,
            "universe": list(settings.symbols) if settings.symbols else "AUTO",
            "top_n": settings.top_n,
            "min_quote_volume_usdt": settings.min_quote_volume_usdt,
            "poll_seconds": settings.poll_seconds,
            "max_concurrency": settings.max_concurrency,
            "fvg_definition": settings.fvg_definition,
            "fvg_max_age_hours": settings.fvg_max_age_hours,
            "mitigation_use_close": settings.mitigation_use_close,
            "liquidity_tolerance_pct": settings.liquidity_tolerance_pct,
            "bos_swing_window": settings.bos_swing_window,
            "bos_atr_period": settings.bos_atr_period,
            "bos_min_atr_mult": settings.bos_min_atr_mult,
            "bos_timeout_bars_15m": settings.bos_timeout_bars_15m,
            "entry_timeout_bars_15m": settings.entry_timeout_bars_15m,
            "cooldown_bars_15m": settings.cooldown_bars_15m,
            "stale_signal_minutes": settings.stale_signal_minutes,
            "telegram_enabled": settings.telegram_enabled,
            "telegram_token_configured": bool(settings.tg_bot_token),
            "telegram_chat_configured": bool(settings.tg_chat_id),
        }

    async def send_telegram_test(self) -> dict[str, Any]:
        settings = self.settings
        if not settings.telegram_enabled:
            raise ValueError("Telegram 未启用，请检查 TELEGRAM_ENABLED 配置")
        if not settings.tg_bot_token or not settings.tg_chat_id:
            raise ValueError("Telegram 配置不完整，请检查 Bot Token 和 Chat ID")

        overview = await asyncio.to_thread(self.overview)
        sent_at = datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")
        message = "\n".join(
            [
                "🧪 ICT SIGNAL | Telegram 测试",
                "",
                "✅ 消息通道连接正常",
                f"📡 行情源：{str(settings.market_data_source).upper()}",
                f"📊 扫描合约：{overview['contract_count']}",
                f"🕒 时间（北京时间）：{sent_at}",
                "",
                "此消息仅用于连接测试，不是交易信号。",
            ]
        )
        await TelegramSender(settings.tg_bot_token, settings.tg_chat_id).send(message)
        return {"ok": True, "sent_at": sent_at, "message": "Telegram 测试消息已发送"}

    def logs(self, lines: int) -> list[str]:
        path = self.process.stderr_path
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return list(deque(handle, maxlen=lines))

    async def market(self) -> dict[str, dict[str, Any]]:
        expires, cached = self._market_cache
        if time.monotonic() < expires:
            return cached
        async with self._market_lock:
            expires, cached = self._market_cache
            if time.monotonic() < expires:
                return cached
            if self.settings.market_data_source != "gate":
                return {}
            try:
                async with httpx.AsyncClient(
                    base_url=self.settings.gate_base_url, timeout=15
                ) as client:
                    response = await client.get("/api/v4/futures/usdt/tickers")
                    response.raise_for_status()
                    rows = response.json()
            except (httpx.HTTPError, ValueError):
                return cached
            data: dict[str, dict[str, Any]] = {}
            for row in rows:
                symbol = str(row.get("contract", "")).replace("_", "")
                data[symbol] = {
                    "price": _number(row.get("last")),
                    "change_24h": _number(row.get("change_percentage")),
                    "volume_24h": _number(
                        row.get("volume_24h_quote")
                        or row.get("volume_24h_usd")
                        or row.get("volume_24h")
                    ),
                    "high_24h": _number(row.get("high_24h")),
                    "low_24h": _number(row.get("low_24h")),
                }
            self._market_cache = (time.monotonic() + 15, data)
            return data


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def create_app(settings: Settings, workspace: Path | None = None) -> FastAPI:
    root = (workspace or Path.cwd()).resolve()
    data = DashboardData(settings, root)
    app = FastAPI(title="ICT Signal Monitor", docs_url=None, redoc_url=None)
    app.state.dashboard = data
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/api/overview")
    async def overview() -> dict[str, Any]:
        return await asyncio.to_thread(data.overview)

    @app.get("/api/states")
    async def states() -> list[dict[str, Any]]:
        return await asyncio.to_thread(data.states)

    @app.get("/api/signals")
    async def signals(limit: int = Query(100, ge=1, le=500)) -> list[dict[str, Any]]:
        return await asyncio.to_thread(data.signals, limit)

    @app.get("/api/config")
    async def config() -> dict[str, Any]:
        return data.config()

    @app.get("/api/logs")
    async def logs(lines: int = Query(200, ge=20, le=1000)) -> dict[str, Any]:
        return {"lines": await asyncio.to_thread(data.logs, lines)}

    @app.get("/api/market")
    async def market() -> dict[str, dict[str, Any]]:
        return await data.market()

    @app.post("/api/telegram/test")
    async def telegram_test() -> dict[str, Any]:
        try:
            return await data.send_telegram_test()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (httpx.HTTPError, RuntimeError) as exc:
            error_text = str(exc)
            if isinstance(exc, RuntimeError) and error_text.startswith("Telegram API error "):
                if "can't send messages to the bot" in error_text.lower():
                    detail = (
                        "Telegram 拒绝发送：TELEGRAM_CHAT_ID 指向了机器人账号。"
                        "请改为接收消息的个人或群组 Chat ID；个人聊天需先向机器人发送 /start。"
                    )
                else:
                    detail = f"Telegram 发送失败：{error_text}"
            else:
                detail = (
                    "Telegram 发送失败，请检查网络、Bot Token、Chat ID，"
                    "以及机器人是否已在目标聊天中启动"
                )
            raise HTTPException(status_code=502, detail=detail) from exc

    @app.post("/api/scanner/{action}")
    async def scanner_action(action: str) -> dict[str, Any]:
        if action not in {"start", "stop", "restart"}:
            raise HTTPException(status_code=404, detail="Unknown scanner action")
        try:
            method = getattr(data.process, action)
            return await asyncio.to_thread(method)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return app


def run_dashboard(settings: Settings, host: str, port: int) -> None:
    app = create_app(settings)
    uvicorn.run(app, host=host, port=port, log_level=settings.log_level.lower())

