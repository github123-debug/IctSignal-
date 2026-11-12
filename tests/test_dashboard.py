from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from ict_signal.dashboard import create_app
from ict_signal.state_machine import RuntimeState
from ict_signal.storage import SignalStore


def test_dashboard_api_masks_secrets_and_reads_runtime(settings, tmp_path):
    settings = replace(
        settings,
        database_path=tmp_path / "data" / "signals.db",
        telegram_enabled=True,
        tg_bot_token="secret-token",
        tg_chat_id="secret-chat",
        market_data_source="gate",
    )
    with SignalStore(settings.database_path) as store:
        store.save_runtime(
            RuntimeState(
                symbol="BTCUSDT",
                initialized=True,
                last_1m_ts=1_700_000_000_000,
            )
        )

    app = create_app(settings, workspace=tmp_path)
    with TestClient(app) as client:
        overview = client.get("/api/overview")
        assert overview.status_code == 200
        assert overview.json()["contract_count"] == 1
        assert overview.json()["telegram_configured"] is True

        states = client.get("/api/states")
        assert states.status_code == 200
        assert states.json()[0]["symbol"] == "BTCUSDT"

        config = client.get("/api/config")
        assert config.status_code == 200
        payload = config.json()
        assert payload["telegram_token_configured"] is True
        assert payload["telegram_chat_configured"] is True
        assert "secret-token" not in config.text
        assert "secret-chat" not in config.text


def test_dashboard_serves_frontend(settings, tmp_path):
    app = create_app(settings, workspace=tmp_path)
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "ICT Signal Monitor" in response.text
        assert 'id="testTelegram"' in response.text
        assert client.get("/static/styles.css").status_code == 200


def test_telegram_test_endpoint_sends_message_without_exposing_credentials(
    settings, tmp_path, monkeypatch
):
    settings = replace(
        settings,
        database_path=tmp_path / "data" / "signals.db",
        telegram_enabled=True,
        tg_bot_token="secret-token",
        tg_chat_id="secret-chat",
        market_data_source="gate",
    )
    sender = AsyncMock()
    monkeypatch.setattr(
        "ict_signal.dashboard.TelegramSender",
        lambda *_args, **_kwargs: sender,
    )

    app = create_app(settings, workspace=tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/telegram/test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["message"] == "Telegram 测试消息已发送"
    sender.send.assert_awaited_once()
    message = sender.send.await_args.args[0]
    assert "消息通道连接正常" in message
    assert "不是交易信号" in message
    assert "secret-token" not in response.text
    assert "secret-chat" not in response.text


def test_telegram_test_endpoint_hides_sender_exception_details(settings, tmp_path, monkeypatch):
    settings = replace(
        settings,
        database_path=tmp_path / "data" / "signals.db",
        telegram_enabled=True,
        tg_bot_token="secret-token",
        tg_chat_id="secret-chat",
    )
    sender = AsyncMock()
    sender.send.side_effect = RuntimeError("request URL contains secret-token")
    monkeypatch.setattr(
        "ict_signal.dashboard.TelegramSender",
        lambda *_args, **_kwargs: sender,
    )

    app = create_app(settings, workspace=tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/telegram/test")

    assert response.status_code == 502
    assert "secret-token" not in response.text
    assert "secret-chat" not in response.text


def test_telegram_test_endpoint_explains_bot_chat_id_error(settings, tmp_path, monkeypatch):
    settings = replace(
        settings,
        database_path=tmp_path / "data" / "signals.db",
        telegram_enabled=True,
        tg_bot_token="secret-token",
        tg_chat_id="secret-chat",
    )
    sender = AsyncMock()
    sender.send.side_effect = RuntimeError(
        "Telegram API error 403: Forbidden: the bot can't send messages to the bot"
    )
    monkeypatch.setattr(
        "ict_signal.dashboard.TelegramSender",
        lambda *_args, **_kwargs: sender,
    )

    app = create_app(settings, workspace=tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/telegram/test")

    assert response.status_code == 502
    assert "TELEGRAM_CHAT_ID 指向了机器人账号" in response.json()["detail"]

