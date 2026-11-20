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
    if not text:
        if any(k in msg for k in ("photo", "document", "video", "voice", "sticker")):
            return [("sendMessage", {"chat_id": chat_id, "text": "Пока принимаем только текст — опишите вопрос словами, пожалуйста."})], True
        return [], False
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.telegram_id == frm.get("id"))) if frm.get("id") else None
        t = db.scalar(select(SupportThread).where(SupportThread.telegram_chat_id == chat_id, SupportThread.topic == "support",
                                                  SupportThread.status == "open").order_by(SupportThread.id.desc()))
        new = t is None
        if new:
            contact = f"Telegram @{frm['username']}" if frm.get("username") else f"Telegram id {frm.get('id')}"
            t = SupportThread(topic="support", category="help", user_id=user.id if user else None, contact=contact,
                              telegram_chat_id=chat_id)
            db.add(t)
            db.commit()
            db.refresh(t)
        handle_user_message(db, t, text[:4000], greet=False)
        tid = t.id
    return ([("sendMessage", {"chat_id": chat_id, "text": ACCEPTED.format(id=tid)})] if new else []), True


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
    m = THREAD_REF.search(reply_to.get("text") or "")
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
