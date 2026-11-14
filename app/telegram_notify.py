"""Отправка сообщений через Telegram-бота (заявки «Помочь» по животным)."""
from __future__ import annotations

import json
import logging
import re
import urllib.request

from .config import settings

log = logging.getLogger("cofi.telegram")
USERNAME_RE = re.compile(r"^(?:@|https?://t\.me/|t\.me/)?([A-Za-z0-9_+/-]{3,64})/?$")


def normalize_contact(value: str) -> str | None:
    """@user, t.me/user, https://t.me/+invite → https://t.me/… ; иначе None."""
    m = USERNAME_RE.match(value.strip())
    if not m:
        return None
    return f"https://t.me/{m.group(1)}"


def send_message(chat_id: str | int, text: str) -> bool:
    if not settings.telegram_bot_token or not chat_id:
        log.info("Telegram не настроен, сообщение для %s:\n%s", chat_id, text)
        return False
    data = json.dumps({"chat_id": chat_id, "text": text, "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(
        f"{settings.telegram_api_url}/bot{settings.telegram_bot_token}/sendMessage",
        data=data, headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()).get("ok", False)
    except Exception:  # noqa: BLE001 — заявка сохранена в базе в любом случае
        log.exception("Не удалось отправить сообщение в Telegram (%s)", chat_id)
        return False
