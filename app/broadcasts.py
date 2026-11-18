"""Рассылки через Telegram-бота: отправка, правка и удаление у всех получателей.

Картинка и текст приходят ОДНИМ сообщением: картинка — большим превью над текстом (link preview по публичной
ссылке на картинку), без отдельного фото и без повтора заголовка. Номера отправленных сообщений сохраняются —
поэтому рассылку потом можно изменить или удалить у всех.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error

from .config import settings
from .database import SessionLocal
from .models import Broadcast, utcnow

log = logging.getLogger("cofi.broadcast")
PAUSE = 0.05  # ~20 запросов в секунду (закрепление — отдельный запрос), у Telegram лимит ~30
RETRIES = 3
TEXT_MAX = 4096


def compose(subject: str, body: str) -> str:
    return f"📣 {subject.strip()}\n\n{body.strip()}"[:TEXT_MAX]


def image_url(b: Broadcast) -> str | None:
    """Публичная https-ссылка на картинку — Telegram скачивает её для превью. Локально (http) превью не будет."""
    base = settings.public_image_url or settings.base_url.rstrip("/")
    if not b.image_name or not base.startswith("https://"):
        return None
    # ?v= — после правки Telegram заново скачивает картинку, а не берёт старое (пустое) превью из своего кэша
    stamp = b.edited_at or b.created_at
    v = f"?v={int(stamp.timestamp())}" if stamp else ""
    return f"{base}/pub/broadcast/{b.image_name}{v}"


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


def _request(method: str, payload: dict) -> tuple[dict | None, str]:
    """(ответ, причина ошибки). На «Too Many Requests» ждёт, сколько просит Telegram, и повторяет."""
    from .telegram_bot import api

    err = ""
    for _ in range(RETRIES + 1):
        try:
            return api(method, payload), ""
        except urllib.error.HTTPError as ex:
            raw = ex.read().decode("utf-8", "replace")[:300]
            try:
                data = json.loads(raw)
            except ValueError:
                data = {}
            err = data.get("description") or raw or str(ex)
            wait = (data.get("parameters") or {}).get("retry_after")
            if ex.code == 429 and wait is not None:
                log.info("Telegram просит подождать %s с", wait)
                time.sleep(min(float(wait), 60) + 0.5)
                continue
            log.warning("Telegram %s (%s): %s", method, payload.get("chat_id"), err)
            return None, err
        except Exception as ex:  # noqa: BLE001 — сеть: одна повторная попытка
            err = str(ex) or ex.__class__.__name__
            log.warning("Telegram %s (%s): %s", method, payload.get("chat_id"), err)
            time.sleep(1)
    return None, err


def _call(method: str, payload: dict) -> dict | None:
    return _request(method, payload)[0]


REASONS = [  # (часть ответа Telegram, понятная подпись для админки)
    ("blocked", "Заблокировали бота"),
    ("deactivated", "Удалили аккаунт Telegram"),
    ("chat not found", "Не начинали чат с ботом"),
    ("initiate conversation", "Не начинали чат с ботом"),
    ("too many requests", "Telegram попросил подождать"),
]


def reason_label(err: str) -> str:
    low = (err or "").lower()
    return next((label for key, label in REASONS if key in low), "Сбой связи или другое")


def reasons_summary(b: Broadcast) -> dict[str, int]:
    out: dict[str, int] = {}
    for err in json.loads(b.failures or "{}").values():
        lab = reason_label(err)
        out[lab] = out.get(lab, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


# повторять бесполезно: человек сам закрыл бота или удалил аккаунт
_FINAL = ("Заблокировали бота", "Удалили аккаунт Telegram")


def _pin(chat: int, message_id: int) -> None:
    # без звука: закреп не должен будить человека вторым уведомлением
    _call("pinChatMessage", {"chat_id": chat, "message_id": message_id, "disable_notification": True})


_newcomer_lock = threading.Lock()


def deliver_to_newcomer(chat_id: int | None, delay: float = 2.0) -> None:
    """Пост «для новых пользователей» (закреплённый) — тем, кто его ещё не получал. Приветствие бота не меняется:
    пост приходит отдельным сообщением чуть позже и закрепляется вверху чата."""
    if not chat_id or chat_id <= 0 or not settings.telegram_bot_token:
        return
    time.sleep(delay)
    with _newcomer_lock, SessionLocal() as db:
        from sqlalchemy import select

        b = db.scalar(select(Broadcast).where(Broadcast.newcomers.is_(True), Broadcast.status == "sent").order_by(Broadcast.id.desc()))
        if not b:
            return
        delivered = json.loads(b.deliveries or "{}")
        if str(chat_id) in delivered:
            return
        res = _call("sendMessage", _payload(b, chat_id))
        mid = (res or {}).get("result", {}).get("message_id")
        if not mid:
            return
        _pin(chat_id, mid)
        delivered[str(chat_id)] = mid
        b.deliveries = json.dumps(delivered)
        b.sent = len(delivered)
        db.commit()
        log.info("Telegram: новому пользователю (%s) — закреплённый пост #%s", chat_id, b.id)


def send(broadcast_id: int, chats: list[int]) -> None:
    """Отправка всем. Номера сообщений сохраняются, чтобы потом изменить или удалить рассылку."""
    with SessionLocal() as db:
        b = db.get(Broadcast, broadcast_id)
        if not b:
            return
        delivered: dict[str, int] = json.loads(b.deliveries or "{}")
        failures: dict[str, str] = json.loads(b.failures or "{}")
        for chat in chats:
            if str(chat) in delivered:
                continue
            res, err = _request("sendMessage", _payload(b, chat))
            mid = (res or {}).get("result", {}).get("message_id")
            if mid:
                delivered[str(chat)] = mid
                failures.pop(str(chat), None)
                if b.pin or b.newcomers:
                    time.sleep(PAUSE)
                    _pin(chat, mid)
                log.info("Telegram: уведомление отправлено (%s): рассылка #%s", chat, b.id)
            else:
                failures[str(chat)] = err or "нет ответа"
            time.sleep(PAUSE)
        b.deliveries, b.failures = json.dumps(delivered), json.dumps(failures)
        b.sent, b.failed, b.status = len(delivered), len(failures), "sent"
        db.commit()


def edit(broadcast_id: int) -> None:
    """Новый текст — у всех, кому рассылка уже пришла."""
    with SessionLocal() as db:
        b = db.get(Broadcast, broadcast_id)
        if not b:
            return
        b.edited_at = utcnow()  # до отправки: от неё зависит адрес картинки (?v=), Telegram скачает её заново
        for chat, mid in json.loads(b.deliveries or "{}").items():
            p = _payload(b, int(chat))
            p["message_id"] = mid
            _call("editMessageText", p)
            time.sleep(PAUSE)
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
        b.newcomers = False
        db.commit()


def resend_targets(b: Broadcast, audience: set[int]) -> list[int]:
    """Кому дослать: получатели рассылки без доставленных и без тех, кто заблокировал бота или удалил аккаунт."""
    delivered = json.loads(b.deliveries or "{}")
    failures = json.loads(b.failures or "{}")
    final = {c for c, err in failures.items() if reason_label(err) in _FINAL}
    return sorted(c for c in audience | {int(x) for x in failures} if str(c) not in delivered and str(c) not in final)
