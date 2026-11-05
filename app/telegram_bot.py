"""Вход через Telegram-бота по ссылке t.me/<бот>?start=login_<токен>.

Сайт выдаёт одноразовый токен, человек открывает бота и нажимает «Войти», бот подтверждает
токен, а страница забирает вход опросом. Работает на localhost и не требует /setdomain.
Бот читает сообщения через long polling (getUpdates) в фоновом потоке, вебхук не нужен.
"""
from __future__ import annotations

import json
import logging
import secrets
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .config import settings

log = logging.getLogger("cofi.telegram")
LOGIN_TTL = 600  # секунд на подтверждение входа


@dataclass
class PendingLogin:
    created: float
    device: str
    status: str = "pending"  # pending → confirmed | declined
    user: dict = field(default_factory=dict)


_pending: dict[str, PendingLogin] = {}
_lock = threading.Lock()
_bot_username: str = settings.telegram_bot_username
_thread: threading.Thread | None = None
_stop = threading.Event()


def api(method: str, payload: dict | None = None, timeout: float = 15) -> dict:
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}",
        data=json.dumps(payload or {}).encode(), headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def bot_username() -> str:
    return _bot_username


def _cleanup(now: float) -> None:
    for token in [t for t, p in _pending.items() if now - p.created > LOGIN_TTL]:
        del _pending[token]


def new_login(device: str) -> dict:
    token = secrets.token_urlsafe(18)
    now = time.time()
    with _lock:
        _cleanup(now)
        _pending[token] = PendingLogin(created=now, device=device[:120])
    return {"token": token, "url": f"https://t.me/{_bot_username}?start=login_{token}", "expires_in": LOGIN_TTL}


_links: dict[str, tuple[int, float]] = {}  # токен → (id пользователя, когда создан)


def new_link(user_id: int) -> str:
    """Ссылка, по которой человек с аккаунтом по почте подключает уведомления в Telegram."""
    token = secrets.token_urlsafe(18)
    now = time.time()
    with _lock:
        for t in [t for t, (_, c) in _links.items() if now - c > LOGIN_TTL]:
            del _links[t]
        _links[token] = (user_id, now)
    return f"https://t.me/{_bot_username}?start=link_{token}"


def _link_account(token: str, frm: dict) -> str:
    from .database import SessionLocal
    from .models import User

    with _lock:
        entry = _links.pop(token, None)
    if not entry:
        return "Ссылка устарела. Нажмите «Подключить уведомления в Telegram» в профиле COFI ещё раз."
    with SessionLocal() as db:
        taken = db.query(User).filter(User.telegram_id == frm["id"], User.id != entry[0]).first()
        if taken:
            return "Этот Telegram уже привязан к другому аккаунту COFI."
        user = db.get(User, entry[0])
        if not user:
            return "Аккаунт не найден."
        user.telegram_id, user.telegram_username, user.tg_notifications = frm["id"], frm.get("username"), True
        db.commit()
    return "Готово! Уведомления COFI подключены: сюда будут приходить сообщения, пары и звонки."


def take_login(token: str) -> PendingLogin | None:
    """Статус входа. Подтверждённый или отклонённый вход выдаётся один раз и удаляется."""
    with _lock:
        _cleanup(time.time())
        p = _pending.get(token)
        if p and p.status != "pending":
            del _pending[token]
        return p


HELP_TEXT = (
    f"Привет! Это бот {settings.app_name}: знакомства и дружба по общим интересам.\n\n"
    "Как войти:\n1. Откройте сайт и нажмите «Войти через Telegram».\n2. Нажмите «Открыть Telegram», вы вернётесь сюда.\n"
    "3. Нажмите «✅ Войти», и браузер войдёт сам.\n\n"
    "Почта и пароль не нужны. Сюда же приходят заявки «Помочь» по питомцам."
)
DESCRIPTION = (f"Вход в {settings.app_name} без почты и пароля. Нажмите «Войти через Telegram» на сайте, "
               "затем «Запустить» здесь и «✅ Войти».")
SHORT_DESCRIPTION = f"Вход в {settings.app_name}: знакомства и дружба по интересам"


def _site_button() -> dict:
    """Кнопка «Открыть COFI». Telegram принимает только публичные адреса, для localhost кнопки нет."""
    url = settings.base_url
    if not url.startswith("https://") or "localhost" in url or "127.0.0.1" in url:
        return {}
    return {"reply_markup": {"inline_keyboard": [[{"text": f"Открыть {settings.app_name}", "url": url}]]}}


def setup_profile() -> None:
    """Команды и описание бота, чтобы не настраивать их вручную в @BotFather."""
    for method, payload in [
        ("setMyCommands", {"commands": [
            {"command": "start", "description": "Как войти на сайт"},
            {"command": "help", "description": "Помощь"},
        ]}),
        ("setMyDescription", {"description": DESCRIPTION}),
        ("setMyShortDescription", {"short_description": SHORT_DESCRIPTION}),
    ]:
        try:
            api(method, payload)
        except Exception:  # noqa: BLE001 — оформление бота не обязательно для входа
            log.warning("Telegram: %s не выполнен", method)


def handle_update(upd: dict) -> list[tuple[str, dict]]:
    """Обрабатывает одно обновление бота и возвращает вызовы API, которые нужно сделать.
    Вынесено отдельно, чтобы проверять логику без сети."""
    calls: list[tuple[str, dict]] = []
    if msg := upd.get("message"):
        chat_id = msg["chat"]["id"]
        text = (msg.get("text") or "").strip()
        if text.startswith("/start link_"):
            calls.append(("sendMessage", {"chat_id": chat_id, "text": _link_account(text.removeprefix("/start link_").strip(), msg.get("from") or {"id": chat_id})}))
        elif text.startswith("/start login_"):
            token = text.removeprefix("/start login_").strip()
            with _lock:
                p = _pending.get(token)
            if not p or p.status != "pending":
                calls.append(("sendMessage", {"chat_id": chat_id, "text": "Ссылка для входа устарела. Нажмите «Войти через Telegram» на сайте ещё раз."}))
            else:
                calls.append(("sendMessage", {
                    "chat_id": chat_id,
                    "text": f"Войти в {settings.app_name}?\n\nУстройство: {p.device or 'браузер'}\n\n"
                            "Если вы не нажимали «Войти через Telegram» на сайте сами, нажмите «Отмена».",
                    "reply_markup": {"inline_keyboard": [[
                        {"text": "✅ Войти", "callback_data": f"ok:{token}"},
                        {"text": "Отмена", "callback_data": f"no:{token}"},
                    ]]},
                }))
        elif text:  # /start, /help и любое другое сообщение: подсказка, как войти
            calls.append(("sendMessage", {"chat_id": chat_id, "text": HELP_TEXT, **_site_button()}))
    elif cb := upd.get("callback_query"):
        action, _, token = (cb.get("data") or "").partition(":")
        frm = cb.get("from") or {}
        if action == "callno":  # «Отклонить» на звонке
            from . import push

            reply = push.decline_from_telegram(token, frm.get("id"))
            calls.append(("answerCallbackQuery", {"callback_query_id": cb["id"]}))
            if m := cb.get("message"):
                calls.append(("editMessageText", {"chat_id": m["chat"]["id"], "message_id": m["message_id"], "text": reply}))
            return calls
        with _lock:
            p = _pending.get(token)
            ok = bool(p and p.status == "pending")
            if ok:
                p.status = "confirmed" if action == "ok" else "declined"
                p.user = {"id": frm.get("id"), "first_name": frm.get("first_name") or "", "username": frm.get("username")}
        if not ok:
            reply = "Ссылка устарела, начните вход на сайте заново."
        elif action == "ok":
            reply = f"Готово! Вернитесь в браузер: вход в {settings.app_name} выполнен."
        else:
            reply = "Вход отменён."
        calls.append(("answerCallbackQuery", {"callback_query_id": cb["id"]}))
        if m := cb.get("message"):
            calls.append(("editMessageText", {"chat_id": m["chat"]["id"], "message_id": m["message_id"], "text": reply}))
    return calls


def _loop() -> None:
    offset = 0
    while not _stop.is_set():
        try:
            res = api("getUpdates", {"offset": offset, "timeout": 25, "allowed_updates": ["message", "callback_query"]}, timeout=35)
            for upd in res.get("result", []):
                offset = upd["update_id"] + 1
                for method, payload in handle_update(upd):
                    try:
                        api(method, payload)
                    except Exception:  # noqa: BLE001
                        log.exception("Telegram %s не выполнен", method)
        except urllib.error.HTTPError as ex:
            if ex.code == 409:  # бот уже запущен в другом месте или включён вебхук
                log.error("Telegram: этот бот уже получает обновления в другом месте (вебхук или второй сервер)")
            _stop.wait(10)
        except Exception:  # noqa: BLE001 — нет сети: пробуем позже
            _stop.wait(5)


def start() -> None:
    """Запускает бота в фоне, если задан TELEGRAM_BOT_TOKEN."""
    global _thread, _bot_username
    if not settings.telegram_bot_token or _thread:
        return
    try:
        me = api("getMe")["result"]
        _bot_username = me["username"]
        api("deleteWebhook")
        setup_profile()
    except Exception:  # noqa: BLE001
        log.error("Telegram: не удалось подключиться к боту. Проверьте TELEGRAM_BOT_TOKEN и интернет")
        if not _bot_username:
            return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="telegram-bot", daemon=True)
    _thread.start()
    log.info("Telegram-бот @%s запущен: вход через Telegram включён (https://t.me/%s)", _bot_username, _bot_username)


def stop() -> None:
    global _thread
    _stop.set()
    _thread = None
