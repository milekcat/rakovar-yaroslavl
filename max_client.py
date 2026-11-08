"""Minimal MAX Bot API client using the official platform-api2 host.

Tokens are read only from MAX_BOT_TOKEN. TLS verification is always enabled.
For environments where the platform's required MinTsifry CA is not in the
system trust store, set MAX_CA_BUNDLE to the official CA bundle path.
"""
from __future__ import annotations

import json
import os
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_BASE = "https://platform-api2.max.ru"


class MaxAPIError(RuntimeError):
    def __init__(self, status: int | None, message: str):
        super().__init__(message)
        self.status = status


def _ssl_context() -> ssl.SSLContext:
    ca_bundle = os.getenv("MAX_CA_BUNDLE", "").strip()
    return ssl.create_default_context(cafile=ca_bundle or None)


def api_request(method: str, path: str, *, params: dict | None = None, body: dict | None = None, timeout: int = 35) -> dict:
    token = os.getenv("MAX_BOT_TOKEN", "").strip()
    if not token:
        raise MaxAPIError(None, "MAX_BOT_TOKEN is not configured")
    query = urlencode({k: v for k, v in (params or {}).items() if v is not None}, doseq=True)
    url = f"{API_BASE}/{path.lstrip('/')}" + (f"?{query}" if query else "")
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = Request(url, data=data, method=method.upper(), headers={
        "Authorization": token,
        "Accept": "application/json",
        **({"Content-Type": "application/json"} if data is not None else {}),
        "User-Agent": "RakovarPreview/0.4",
    })
    try:
        with urlopen(request, timeout=timeout, context=_ssl_context()) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise MaxAPIError(response.status, "MAX API response exceeded 2 MB")
            if not raw:
                return {}
            try:
                return json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise MaxAPIError(response.status, "MAX API returned a non-JSON response") from None
    except HTTPError as exc:
        # Do not include request headers or token in error text.
        # Keep response bodies out of logs; they are not needed for actionable status.
        raise MaxAPIError(exc.code, f"MAX API HTTP {exc.code}") from None
    except URLError as exc:
        raise MaxAPIError(None, f"MAX API network/TLS error: {exc.reason}") from None


def get_me() -> dict:
    return api_request("GET", "/me")


def set_commands() -> dict:
    return api_request("PATCH", "/me/commands", body={"commands": [
        {"name":"start","description":"Начать работу с РАКОВАРЪ"},
        {"name":"catalog","description":"Открыть каталог морских деликатесов"},
        {"name":"club","description":"Клубные билеты и игровые правила"},
        {"name":"referral","description":"Пригласить друга в клуб РАКОВАРЪ"},
        {"name":"tickets","description":"Проверить баланс билетов"},
        {"name":"id","description":"Показать ваш MAX ID для уведомлений"},
        {"name":"help","description":"Помощь и команды бота"},
    ]})


def get_updates(*, marker: int | None = None, timeout: int = 30, limit: int = 100) -> dict:
    return api_request("GET", "/updates", params={
        "marker": marker,
        "timeout": max(0, min(int(timeout), 90)),
        "limit": max(1, min(int(limit), 1000)),
        "types": "message_created,bot_started",
    }, timeout=max(40, int(timeout) + 10))


def send_message(*, user_id: int | None = None, chat_id: int | None = None, text: str, buttons: list | None = None) -> dict:
    if (user_id is None) == (chat_id is None):
        raise ValueError("Specify exactly one of user_id or chat_id")
    payload = {"text": str(text)[:4000]}
    if buttons:
        payload["attachments"] = [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]
    return api_request("POST", "/messages", params={"user_id": user_id, "chat_id": chat_id}, body=payload)
