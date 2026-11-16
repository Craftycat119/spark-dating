"""Рассылки через Telegram-бота: отправка, правка и удаление у всех получателей.

Картинка и текст приходят ОДНИМ сообщением: картинка — большим превью над текстом (link preview по публичной
ссылке на картинку), без отдельного фото и без повтора заголовка. Номера отправленных сообщений сохраняются —
поэтому рассылку потом можно изменить или удалить у всех.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error

from .config import settings
from .database import SessionLocal
from .models import Broadcast, utcnow

log = logging.getLogger("cofi.broadcast")
PAUSE = 0.04  # ~25 сообщений в секунду — ограничение Telegram
TEXT_MAX = 4096


def compose(subject: str, body: str) -> str:
    return f"📣 {subject.strip()}\n\n{body.strip()}"[:TEXT_MAX]


def image_url(b: Broadcast) -> str | None:
    """Публичная https-ссылка на картинку — Telegram скачивает её для превью. Локально (http) превью не будет."""
    base = settings.base_url.rstrip("/")
    if not b.image_name or not base.startswith("https://"):
        return None
    return f"{base}/pub/broadcast/{b.image_name}"


def _payload(b: Broadcast, chat_id: int) -> dict:
    from .push import _open_button

    p: dict = {"chat_id": chat_id, "text": compose(b.subject, b.body)}
    url = image_url(b)
    # картинка над текстом, крупно; без картинки — без превью ссылок
    p["link_preview_options"] = ({"url": url, "prefer_large_media": True, "show_above_text": True} if url else {"is_disabled": True})
    btn = _open_button("Открыть COFI")
    if btn:
        p["reply_markup"] = {"inline_keyboard": [[btn]]}
    return p


def _call(method: str, payload: dict) -> dict | None:
    from .telegram_bot import api

    try:
        return api(method, payload)
    except urllib.error.HTTPError as ex:
        log.warning("Telegram %s (%s): %s", method, payload.get("chat_id"), ex.read().decode("utf-8", "replace")[:300])
    except Exception as ex:  # noqa: BLE001
        log.warning("Telegram %s (%s): %s", method, payload.get("chat_id"), ex)
    return None


def send(broadcast_id: int, chats: list[int]) -> None:
    """Отправка всем. Номера сообщений сохраняются, чтобы потом изменить или удалить рассылку."""
    with SessionLocal() as db:
        b = db.get(Broadcast, broadcast_id)
        if not b:
            return
        delivered: dict[str, int] = {}
        failed = 0
        for chat in chats:
            res = _call("sendMessage", _payload(b, chat))
            mid = (res or {}).get("result", {}).get("message_id")
            if mid:
                delivered[str(chat)] = mid
                log.info("Telegram: уведомление отправлено (%s): рассылка #%s", chat, b.id)
            else:
                failed += 1
            time.sleep(PAUSE)
        b.deliveries = json.dumps(delivered)
        b.sent, b.failed, b.status = len(delivered), failed, "sent"
        db.commit()


def edit(broadcast_id: int) -> None:
    """Новый текст — у всех, кому рассылка уже пришла."""
    with SessionLocal() as db:
        b = db.get(Broadcast, broadcast_id)
        if not b:
            return
        for chat, mid in json.loads(b.deliveries or "{}").items():
            p = _payload(b, int(chat))
            p["message_id"] = mid
            _call("editMessageText", p)
            time.sleep(PAUSE)
        b.edited_at = utcnow()
        db.commit()


def delete(broadcast_id: int) -> None:
    """Удалить у всех. Telegram разрешает боту удалять свои сообщения в течение 48 часов."""
    with SessionLocal() as db:
        b = db.get(Broadcast, broadcast_id)
        if not b:
            return
        for chat, mid in json.loads(b.deliveries or "{}").items():
            _call("deleteMessage", {"chat_id": int(chat), "message_id": mid})
            time.sleep(PAUSE)
        b.status = "deleted"
        db.commit()
