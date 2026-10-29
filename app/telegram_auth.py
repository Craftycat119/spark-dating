"""Проверка данных Telegram Login Widget: https://core.telegram.org/widgets/login#checking-authorization"""
from __future__ import annotations

import hashlib
import hmac
import time

MAX_AGE_SECONDS = 24 * 3600


def verify_telegram_auth(data: dict, bot_token: str, now: float | None = None) -> bool:
    if not bot_token or "hash" not in data or "id" not in data:
        return False
    received_hash = str(data["hash"])
    check_string = "\n".join(
        f"{k}={data[k]}" for k in sorted(data) if k != "hash" and data[k] is not None
    )
    secret = hashlib.sha256(bot_token.encode()).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        return False
    try:
        auth_date = int(data.get("auth_date", 0))
    except (TypeError, ValueError):
        return False
    return (now or time.time()) - auth_date <= MAX_AGE_SECONDS
