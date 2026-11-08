"""Уведомления на телефон через Telegram-бота: сообщения, пары и звонки тем, кто сейчас не в приложении.

Telegram показывает сообщение бота вверху экрана со звуком, даже когда COFI закрыт.
Кнопки «Ответить» и «Открыть чат» открывают COFI как мини-приложение Telegram (нужен https-адрес в BASE_URL),
вход при этом происходит сам (см. /api/auth/telegram/webapp).

Звонок человеку не в сети: предложение соединения (offer) и ICE-кандидаты звонящего ждут здесь до 90 секунд.
Собеседник нажимает «Ответить» в Telegram, открывает COFI, забирает звонок (call:join) и отвечает как обычно.
"""
from __future__ import annotations

import logging
import threading
import time
import urllib.error
from dataclasses import dataclass, field
from urllib.parse import urlencode

from .config import settings
from .realtime import manager, notify

log = logging.getLogger("cofi.push")
CALL_TTL = 90
MESSAGE_PAUSE = 60  # не чаще одного уведомления о сообщениях в чате за минуту


@dataclass
class PendingCall:
    call_id: str
    conversation_id: int
    caller_id: int
    caller_name: str
    callee_id: int
    video: bool
    sdp: dict
    created: float = field(default_factory=time.time)
    ice: list = field(default_factory=list)
    tg_chat: int | None = None  # куда слать «Пропущенный вызов» (Telegram собеседника), если уведомления включены
    tg_message: int | None = None  # сообщение «Звонок от…», которое правим по итогу


_calls: dict[str, PendingCall] = {}
_last_message_notice: dict[tuple[int, int], float] = {}
_lock = threading.Lock()


def enabled() -> bool:
    return bool(settings.telegram_bot_token)


def app_link(**params) -> str | None:
    """Ссылка, открывающая COFI внутри Telegram. Telegram принимает только публичный https."""
    base = settings.base_url.rstrip("/")
    if not base.startswith("https://") or "localhost" in base or "127.0.0.1" in base:
        return None
    return f"{base}/?{urlencode(params)}" if params else f"{base}/"


def _open_button(text: str, **params) -> dict | None:
    url = app_link(**params)
    return {"text": text, "web_app": {"url": url}} if url else None


def _send(chat_id: int, text: str, buttons: list[dict | None] | None = None) -> int | None:
    from .telegram_bot import api

    payload: dict = {"chat_id": chat_id, "text": text}
    row = [b for b in (buttons or []) if b]
    if row:
        payload["reply_markup"] = {"inline_keyboard": [row]}
    try:
        res = api("sendMessage", payload)
        log.info("Telegram: уведомление отправлено (%s): %s", chat_id, text.splitlines()[0])
        return res.get("result", {}).get("message_id")
    except urllib.error.HTTPError as ex:
        reason = ex.read().decode("utf-8", "replace")
        hint = " Человек должен открыть бота и нажать «Запустить»." if ex.code in (400, 403) else ""
        log.warning("Telegram: уведомление не отправлено (%s): %s%s", chat_id, reason, hint)
    except Exception as ex:  # noqa: BLE001 — нет сети до api.telegram.org
        log.warning("Telegram: уведомление не отправлено (%s): %s", chat_id, ex)
    return None


def _edit(chat_id: int | None, message_id: int | None, text: str) -> None:
    if not chat_id or not message_id:
        return
    from .telegram_bot import api

    try:
        api("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": text})
    except Exception:  # noqa: BLE001
        pass


def _in_background(fn, *args) -> None:
    threading.Thread(target=fn, args=args, daemon=True).start()


def can_notify(user) -> bool:
    if not enabled() or user.is_bot:
        return False
    if not user.telegram_id:
        log.info("Telegram-уведомление для %s не отправлено: Telegram не подключён (вход по почте). "
                 "Пусть нажмёт в профиле «Подключить уведомления в Telegram»", user.name or user.id)
        return False
    if not user.tg_notifications:
        log.info("Telegram-уведомление для %s не отправлено: уведомления выключены в профиле", user.name or user.id)
        return False
    return True


def away(user_id: int) -> bool:
    """Человек не смотрит на COFI: приложение закрыто, свёрнуто или в фоне (соединение может быть ещё живо)."""
    return not manager.is_active(user_id)


# ---------- сообщения и пары ----------

def _unread(user_id: int, conversation_id: int) -> int:
    from sqlalchemy import func, select

    from .database import SessionLocal
    from .models import Message

    with SessionLocal() as db:
        return db.scalar(select(func.count(Message.id)).where(
            Message.conversation_id == conversation_id, Message.sender_id != user_id, Message.read_at.is_(None))) or 0


def notify_message(recipient, sender_name: str, conversation_id: int, preview: str) -> None:
    """Новое сообщение: уведомляем, если человек сейчас не смотрит на COFI."""
    if not away(recipient.id) or not can_notify(recipient):
        return
    key = (recipient.id, conversation_id)
    now = time.time()
    with _lock:
        if now - _last_message_notice.get(key, 0) < MESSAGE_PAUSE:
            return
        _last_message_notice[key] = now
    unread = _unread(recipient.id, conversation_id)
    more = f" ({unread} непрочитанных)" if unread > 1 else ""
    text = f"✉️ Вам пришло сообщение от {sender_name}{more}" + (f":\n{preview[:300]}" if preview else "")
    _in_background(_send, recipient.telegram_id, text, [_open_button("Открыть чат", chat=conversation_id)])


def notify_match(recipient, other_name: str, conversation_id: int) -> None:
    if not away(recipient.id) or not can_notify(recipient):
        return
    _in_background(_send, recipient.telegram_id, f"🔥 Взаимно! Вы и {other_name} понравились друг другу. Напишите первым",
                   [_open_button("Написать", chat=conversation_id)])


# ---------- звонки ----------

def _expire() -> None:
    """Убираем звонки, которые никто не взял. Вызывать под _lock; сообщения в Telegram правим в фоне."""
    now = time.time()
    for cid in [c for c, p in _calls.items() if now - p.created > CALL_TTL]:
        _missed(_calls.pop(cid))


def _missed(p: PendingCall) -> None:
    """Никто не ответил: правим «Звонок от…» и отдельным сообщением шлём «Пропущенный вызов» — его видно в уведомлениях."""
    if not p.tg_chat:
        return
    kind = "видеовызов" if p.video else "вызов"
    _in_background(_edit, p.tg_chat, p.tg_message, f"📞 Звонок от {p.caller_name} завершён")
    _in_background(_send, p.tg_chat, f"📵 Пропущенный {kind} от {p.caller_name}",
                   [_open_button("Перезвонить", chat=p.conversation_id)])


def offer(call: PendingCall, callee) -> bool:
    """Сохраняем звонок. Если собеседник не смотрит на COFI, шлём ему звонок в Telegram. True — уведомление ушло."""
    with _lock:
        _expire()
        _calls[call.call_id] = call
    if not can_notify(callee):
        return False
    call.tg_chat = callee.telegram_id  # «Пропущенный вызов» придёт, даже если звонок показывался в приложении
    if not away(callee.id):
        return False
    kind = "Видеозвонок" if call.video else "Звонок"
    msg_id = _send(callee.telegram_id, f"📞 {kind} от {call.caller_name}\nНажмите «Ответить», чтобы открыть COFI и поговорить", [
        _open_button("✅ Ответить", call=call.call_id),
        {"text": "❌ Отклонить", "callback_data": f"callno:{call.call_id}"},
    ])
    if msg_id is None:
        return False
    call.tg_message = msg_id
    return True


def add_ice(call_id: str, sender_id: int, candidate) -> None:
    """Кандидаты звонящего копим, пока собеседник не открыл COFI."""
    with _lock:
        p = _calls.get(call_id)
        if p and p.caller_id == sender_id and candidate and len(p.ice) < 60:
            p.ice.append(candidate)


def take(call_id: str, user_id: int) -> PendingCall | None:
    """Собеседник открыл COFI по кнопке «Ответить» и забирает звонок."""
    with _lock:
        _expire()
        p = _calls.get(call_id)
        if not p or p.callee_id != user_id:
            return None
    _in_background(_edit, p.tg_chat, p.tg_message, f"📞 Разговор с {p.caller_name}")
    return p


def finish(call_id: str, outcome: str) -> None:
    """Звонок закончился: answer (ответили), end (звонящий сбросил), reject (отклонили)."""
    with _lock:
        p = _calls.pop(call_id, None)
    if not p:
        return
    if outcome == "end":  # звонящий сбросил, пока никто не ответил
        _missed(p)
    elif outcome == "reject":
        _in_background(_edit, p.tg_chat, p.tg_message, f"📞 Вы отклонили звонок от {p.caller_name}")


def decline_from_telegram(call_id: str, telegram_user_id: int) -> str:
    """Кнопка «Отклонить» в Telegram. Возвращает текст для сообщения бота."""
    with _lock:
        p = _calls.get(call_id)
        if not p or p.tg_chat != telegram_user_id:
            return "Звонок уже завершён"
        _calls.pop(call_id, None)
    notify(p.caller_id, {"type": "call:reject", "conversation_id": p.conversation_id, "call_id": p.call_id})
    return f"📞 Вы отклонили звонок от {p.caller_name}"


# ---------- обращения в поддержку → администраторам ----------

SUPPORT_TITLES = {"help": "🆘 Нужна помощь", "complaint": "⚠️ Жалоба", "suggestion": "💡 Предложение", "ads": "📣 Реклама"}
_last_support_notice: dict[int, float] = {}


def admin_chats(db) -> list:
    """Куда бот шлёт администрации обращения, рекламу и заявки: группа TELEGRAM_ADMIN_CHAT_ID
    или все администраторы, у которых подключён Telegram и включены уведомления."""
    from sqlalchemy import select

    from .models import User

    if settings.telegram_admin_chat_id:
        return [settings.telegram_admin_chat_id]
    return list(db.scalars(select(User.telegram_id).where(User.is_admin.is_(True), User.telegram_id.is_not(None),
                                                          User.tg_notifications.is_(True))))


def admin_button(section: str) -> dict | None:
    """Кнопка «Открыть в админ-панели», если у сайта публичный https-адрес."""
    return {"text": "Открыть в админ-панели", "url": f"{settings.base_url.rstrip('/')}/admin#{section}"} if app_link() else None


def _who(thread) -> str:
    """«Вася (#12), Telegram @vasya, почта v@mail.ru» — чтобы администрация сразу видела, кому отвечать."""
    u = thread.user
    if not u:
        return f"гостя без аккаунта, контакт: {thread.contact}" if thread.contact else "гостя без аккаунта (контакт не оставлен)"
    parts = [f"{u.name or 'без имени'} (#{u.id})"]
    if u.telegram_username:
        parts.append(f"Telegram @{u.telegram_username}")
    elif u.telegram_id:
        parts.append(f"Telegram id {u.telegram_id}")
    if u.email:
        parts.append(f"почта {u.email}")
    if thread.contact:
        parts.append(f"контакт: {thread.contact}")
    return ", ".join(parts)


def notify_admins(db, thread, text: str) -> None:
    """Новое сообщение в обращении: администраторам в Telegram (или в группу TELEGRAM_ADMIN_CHAT_ID)."""
    if not enabled():
        return
    from .models import User

    now = time.time()
    with _lock:
        if now - _last_support_notice.get(thread.id, 0) < 20:  # переписка идёт — не дёргаем на каждое слово
            return
        _last_support_notice[thread.id] = now
    # поддержка (помощь, жалобы, предложения) — в свою группу, если она задана; реклама — в группу администрации
    chats = [settings.telegram_support_chat_id] if thread.topic == "support" and settings.telegram_support_chat_id else admin_chats(db)
    if not chats:
        log.info("Обращение #%s: некому отправить в Telegram. Привяжите Telegram к аккаунту админа или задайте TELEGRAM_ADMIN_CHAT_ID", thread.id)
        return
    who = _who(thread)
    target = db.get(User, thread.about_user_id) if thread.about_user_id else None
    about = f"\nНа анкету: {target.name or 'без имени'} (#{target.id})" if target else ""
    title = SUPPORT_TITLES.get(thread.category, "🆘 Обращение")
    message = f"{title} #{thread.id} от {who}{about}\n\n{text[:1500]}"
    for chat in chats:
        _in_background(_send, chat, message, [admin_button("support")])


def broadcast(chats: list[int], text: str) -> None:
    """Рассылка из админ-панели. Не быстрее ~25 сообщений в секунду: так требует Telegram."""
    for chat in chats:
        _send(chat, text, [_open_button("Открыть COFI")])
        time.sleep(0.04)
