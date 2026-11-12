from __future__ import annotations

import httpx


class TelegramSender:
    def __init__(self, bot_token: str, chat_id: str, timeout: float = 20.0) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout

    async def send(self, message: str) -> None:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    url,
                    json={
                        "chat_id": self.chat_id,
                        "text": message,
                        "disable_web_page_preview": True,
                    },
                )
            except httpx.RequestError as exc:
                # Do not expose the token embedded in the request URL.
                raise RuntimeError(
                    f"Telegram request failed: {exc.__class__.__name__}"
                ) from exc

            try:
                payload = response.json()
            except ValueError:
                payload = {}
            description = str(payload.get("description") or response.reason_phrase)
            description = description.replace(self.bot_token, "[已隐藏]")
            description = description.replace(self.chat_id, "[已隐藏]")
            if not response.is_success:
                raise RuntimeError(
                    f"Telegram API error {response.status_code}: {description}"
                )
            if not payload.get("ok"):
                description = str(payload.get("description") or "unknown error")
                description = description.replace(self.bot_token, "[已隐藏]")
                description = description.replace(self.chat_id, "[已隐藏]")
                raise RuntimeError(f"Telegram rejected sendMessage: {description}")

