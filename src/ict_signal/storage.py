from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import Signal
from .state_machine import RuntimeState


class SignalStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self._migrate()

    def _migrate(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS runtime_state (
                symbol TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS signals (
                fingerprint TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                fvg_id TEXT NOT NULL,
                liquidity_level TEXT NOT NULL,
                signal_ts INTEGER NOT NULL,
                signal_price REAL NOT NULL,
                message TEXT NOT NULL,
                delivery_status TEXT NOT NULL DEFAULT 'pending',
                delivery_error TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_signals_symbol_fvg
                ON signals(symbol, fvg_id);
            """
        )
        self.connection.commit()

    def load_runtime(self, symbol: str) -> RuntimeState | None:
        row = self.connection.execute(
            "SELECT payload FROM runtime_state WHERE symbol = ?", (symbol,)
        ).fetchone()
        return RuntimeState.from_dict(json.loads(row["payload"])) if row else None

    def save_runtime(self, runtime: RuntimeState) -> None:
        payload = json.dumps(runtime.to_dict(), ensure_ascii=False, separators=(",", ":"))
        self.connection.execute(
            """
            INSERT INTO runtime_state(symbol, payload) VALUES (?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                payload = excluded.payload,
                updated_at = CURRENT_TIMESTAMP
            """,
            (runtime.symbol, payload),
        )
        self.connection.commit()

    def emitted_fvg_ids(self, symbol: str) -> set[str]:
        rows = self.connection.execute(
            "SELECT DISTINCT fvg_id FROM signals WHERE symbol = ?", (symbol,)
        ).fetchall()
        return {row["fvg_id"] for row in rows}

    def record_signal(self, signal: Signal, message: str) -> bool:
        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO signals(
                fingerprint, symbol, direction, fvg_id, liquidity_level,
                signal_ts, signal_price, message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal.fingerprint,
                signal.symbol,
                signal.direction.value,
                signal.fvg.fvg_id,
                signal.liquidity_level,
                signal.signal_ts,
                signal.signal_price,
                message,
            ),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def set_delivery(self, fingerprint: str, status: str, error: str | None = None) -> None:
        self.connection.execute(
            "UPDATE signals SET delivery_status = ?, delivery_error = ? WHERE fingerprint = ?",
            (status, error, fingerprint),
        )
        self.connection.commit()

    def recent_signals(self, limit: int = 50) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM signals ORDER BY signal_ts DESC LIMIT ?", (limit,)
        ).fetchall()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "SignalStore":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

