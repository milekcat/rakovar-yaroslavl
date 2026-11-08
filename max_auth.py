"""Pure MAX Mini App initData signature verification (no Flask dependency)."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from urllib.parse import unquote


class MaxInitDataError(ValueError):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


def _decode_pairs(raw: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for part in raw.split("&"):
        if not part or "=" not in part:
            raise MaxInitDataError(400, "invalid_max_init_data")
        key, value = part.split("=", 1)
        if re.search(r"%(?![0-9a-fA-F]{2})", key) or re.search(r"%(?![0-9a-fA-F]{2})", value):
            raise MaxInitDataError(400, "invalid_max_encoding")
        try:
            pairs.append((unquote(key, errors="strict"), unquote(value, errors="strict")))
        except UnicodeDecodeError as exc:
            raise MaxInitDataError(400, "invalid_max_encoding") from exc
    return pairs


def validate_init_data(init_data: str, bot_token: str, *, now: int | None = None, max_age: int = 3600) -> dict:
    raw = str(init_data or "").strip()
    if not bot_token:
        raise MaxInitDataError(503, "max_bot_token_not_configured")
    if not raw or len(raw) > 12000:
        raise MaxInitDataError(400, "invalid_max_init_data")

    outer_pairs = _decode_pairs(raw)
    outer_keys = [key for key, _ in outer_pairs]
    if len(outer_keys) != len(set(outer_keys)):
        raise MaxInitDataError(400, "duplicate_max_wrapper_parameter")
    outer = dict(outer_pairs)
    if "WebAppData" in outer:
        raw = outer["WebAppData"]

    pairs = _decode_pairs(raw)
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)) or keys.count("hash") != 1:
        raise MaxInitDataError(400, "invalid_max_signature_fields")
    values = dict(pairs)
    supplied_hash = values.pop("hash", "")
    if not supplied_hash:
        raise MaxInitDataError(400, "missing_max_hash")

    data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, supplied_hash.lower()):
        raise MaxInitDataError(403, "invalid_max_signature")

    try:
        auth_date = int(values.get("auth_date", "0"))
        user = json.loads(values.get("user", "{}"))
        user_id = int(user["id"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise MaxInitDataError(400, "invalid_max_user_data") from exc
    if user_id <= 0:
        raise MaxInitDataError(400, "invalid_max_user_id")
    current = int(time.time()) if now is None else int(now)
    if auth_date > current + 60 or current - auth_date > max_age:
        raise MaxInitDataError(403, "expired_max_init_data")
    return {"user_id": user_id, "user": user, "auth_date": auth_date, "start_param": values.get("start_param", "")}
