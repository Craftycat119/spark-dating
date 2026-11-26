"""Поддержка через Telegram-бота.

* Человек пишет боту → сообщение попадает в обращение поддержки (как с сайта): в админку и в группу поддержки.
* Администратор отвечает в админке → бот присылает ответ человеку.
* Или прямо в группе поддержки: ответить (reply) на уведомление бота «🆘 … #N» — ответ уйдёт человеку.
"""
from __future__ import annotations

import logging
import re

from sqlalchemy import select

from .config import settings
from .database import SessionLocal
from .models import SupportThread, User

log = logging.getLogger("cofi.tg_support")
THREAD_REF = re.compile(r"#(\d+)")
ACCEPTED = ("Спасибо! Обращение №{id} принято — ответим здесь, в этом чате, обычно в течение часа.\n"
            "Можно дописать подробности или прислать ещё сообщения.")


def from_user(msg: dict) -> tuple[list[tuple[str, dict]], bool]:
    """Личное сообщение боту (не команда) → в обращение. Возвращает (вызовы API, обработано ли)."""
    from .routers.support import handle_user_message

    text = (msg.get("text") or msg.get("caption") or "").strip()
    chat_id = msg["chat"]["id"]
    frm = msg.get("from") or {}
    photo_id = _photo_file_id(msg)
    if not text and not photo_id:
        if any(k in msg for k in ("photo", "document", "video", "voice", "sticker", "video_note", "audio")):
            return [("sendMessage", {"chat_id": chat_id, "text": "Принимаем текст и скриншоты. Голосовые и видео пока не открываются — опишите вопрос словами или пришлите скриншот."})], True
        return [], False
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.telegram_id == frm.get("id"))) if frm.get("id") else None
        t = db.scalar(select(SupportThread).where(SupportThread.telegram_chat_id == chat_id, SupportThread.topic == "support",
                                                  SupportThread.status.in_(("open", "in_work", "answered"))).order_by(SupportThread.id.desc()))
        new = t is None
        if new:
            contact = f"Telegram @{frm['username']}" if frm.get("username") else f"Telegram id {frm.get('id')}"
            t = SupportThread(topic="support", category="help", user_id=user.id if user else None, contact=contact,
                              telegram_chat_id=chat_id)
            db.add(t)
            db.commit()
            db.refresh(t)
        if photo_id:
            raw = _download(photo_id)
            if raw is None:
                return [("sendMessage", {"chat_id": chat_id, "text": "Не получилось принять картинку. Пришлите её ещё раз или опишите словами."})], True
            from .routers.support import add_screenshot

            try:
                add_screenshot(db, t, raw)
            except Exception:  # noqa: BLE001 — битый файл: не роняем бота
                log.warning("Скриншот из Telegram не сохранился (чат %s)", chat_id)
        if text:
            handle_user_message(db, t, text[:4000], greet=False)
        tid = t.id
    return ([("sendMessage", {"chat_id": chat_id, "text": ACCEPTED.format(id=tid)})] if new else []), True


MAX_PHOTO = 15 * 1024 * 1024


def _photo_file_id(msg: dict) -> str | None:
    """Фото (самый крупный вариант) или картинка, отправленная файлом."""
    if msg.get("photo"):
        return max(msg["photo"], key=lambda p: p.get("file_size") or p.get("width", 0) * p.get("height", 0))["file_id"]
    doc = msg.get("document") or {}
    if (doc.get("mime_type") or "").startswith("image/"):
        return doc.get("file_id")
    return None


def _download(file_id: str) -> bytes | None:
    """Скачать файл из Telegram (через посредника, если он настроен)."""
    import urllib.request

    from .telegram_bot import api

    try:
        info = api("getFile", {"file_id": file_id}).get("result") or {}
        if not info.get("file_path") or (info.get("file_size") or 0) > MAX_PHOTO:
            return None
        url = f"{settings.telegram_api_url}/file/bot{settings.telegram_bot_token}/{info['file_path']}"
        with urllib.request.urlopen(url, timeout=30) as r:
            data = r.read(MAX_PHOTO + 1)
        return data if len(data) <= MAX_PHOTO else None
    except Exception as ex:  # noqa: BLE001
        log.warning("Не удалось скачать картинку из Telegram: %s", ex)
        return None


def _support_chat_ids() -> set[str]:
    return {str(v).strip() for v in (settings.telegram_support_chat_id, settings.telegram_complaints_chat_id,
                                     getattr(settings, "telegram_admin_chat_id", "")) if v}


def from_group(msg: dict) -> list[tuple[str, dict]]:
    """Ответ (reply) в группе поддержки на уведомление бота об обращении → ответ человеку."""
    from .routers.support import _add

    reply_to = msg.get("reply_to_message") or {}
    text = (msg.get("text") or "").strip()
    if not text or not (reply_to.get("from") or {}).get("is_bot"):
        return []
    if str(msg["chat"]["id"]) not in _support_chat_ids():
        return []  # отвечать от имени поддержки можно только из её групп
    m = THREAD_REF.search(reply_to.get("text") or reply_to.get("caption") or "")  # ответ на текст или на скриншот
    if not m:
        return []
    with SessionLocal() as db:
        t = db.get(SupportThread, int(m.group(1)))
        if not t:
            return [("sendMessage", {"chat_id": msg["chat"]["id"], "text": "Обращение не найдено.", "reply_to_message_id": msg["message_id"]})]
        _add(db, t, "staff", text[:4000])
        who = "в Telegram" if t.telegram_chat_id else ("в приложении" if t.user_id else f"в приложении (гость, контакт: {t.contact})")
    return [("sendMessage", {"chat_id": msg["chat"]["id"], "text": f"✅ Ответ отправлен {who}", "reply_to_message_id": msg["message_id"]})]


def deliver_staff_reply(thread: SupportThread, text: str) -> None:
    """Ответ поддержки — человеку в Telegram, если обращение пришло через бота."""
    if not thread.telegram_chat_id or not settings.telegram_bot_token:
        return
    from .push import _in_background, _send

    _in_background(_send, thread.telegram_chat_id, f"💬 Поддержка {settings.app_name}:\n\n{text}")
