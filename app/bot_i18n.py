"""Бот отвечает на языке Telegram человека: украинский, русский или английский.

Тексты бота пишутся по-русски, а перед отправкой (telegram_bot.api) переводятся по словарю — для каждого чата
на его язык. Язык берём из language_code, который Telegram присылает с каждым сообщением и нажатием кнопки,
и запоминаем (уведомления о сообщениях и звонках уходят без нового сообщения от человека). Не писал боту —
язык, выбранный в приложении COFI, иначе русский.

Рассылки из админки (с HTML-разметкой) и ответы операторов не переводятся: это живой текст администрации.
"""
from __future__ import annotations

import logging
import re
import threading

from .config import settings

log = logging.getLogger("cofi.bot_i18n")
APP = settings.app_name
RU_LIKE = ("ru", "be", "kk", "ky", "uz", "tg", "hy", "az", "ka", "tk")


def lang_from_code(code: str | None) -> str | None:
    """language_code из Telegram → ru / uk / en (None — Telegram язык не прислал)."""
    if not code:
        return None
    code = code.lower()
    if code.startswith("uk"):
        return "uk"
    if code.split("-")[0] in RU_LIKE:
        return "ru"
    return "en"


_cache: dict[int, str] = {}
_lock = threading.Lock()


def remember(chat_id: int | None, code: str | None) -> None:
    """Запомнить язык чата (личного) по language_code из сообщения или нажатия кнопки."""
    lang = lang_from_code(code)
    if not chat_id or chat_id <= 0 or not lang:
        return
    with _lock:
        if _cache.get(chat_id) == lang:
            return
        _cache[chat_id] = lang
    try:
        from .database import SessionLocal
        from .models import TelegramChatLang

        with SessionLocal() as db:
            row = db.get(TelegramChatLang, chat_id)
            if row:
                row.lang = lang
            else:
                db.add(TelegramChatLang(chat_id=chat_id, lang=lang))
            db.commit()
    except Exception:  # noqa: BLE001 — язык не сохранился: переживём, в памяти он есть
        log.warning("Не удалось запомнить язык чата %s", chat_id)


def chat_lang(chat_id: int | None) -> str:
    """Язык, на котором писать в этот чат."""
    if not chat_id or chat_id <= 0:
        return "ru"  # группы поддержки — для администрации, по-русски
    with _lock:
        if chat_id in _cache:
            return _cache[chat_id]
    lang = "ru"
    try:
        from sqlalchemy import select

        from .database import SessionLocal
        from .models import TelegramChatLang, User

        with SessionLocal() as db:
            row = db.get(TelegramChatLang, chat_id)
            if row:
                lang = row.lang
            else:
                user_lang = db.scalar(select(User.language).where(User.telegram_id == chat_id))
                lang = user_lang if user_lang in ("ru", "uk", "en") else "ru"
    except Exception:  # noqa: BLE001
        pass
    with _lock:
        _cache[chat_id] = lang
    return lang


# ---------- Словарь: точные фразы ----------
T: dict[str, tuple[str, str]] = {  # русский → (украинский, английский)
    "Ссылка устарела. Нажмите «Подключить уведомления в Telegram» в профиле COFI ещё раз.": (
        "Посилання застаріло. Натисніть «Підключити сповіщення в Telegram» у профілі COFI ще раз.",
        "This link has expired. Tap “Connect Telegram notifications” in your COFI profile again."),
    "✅ Подключить": ("✅ Підключити", "✅ Connect"),
    "Отмена": ("Скасувати", "Cancel"),
    "Этот Telegram уже привязан к другому аккаунту COFI.": (
        "Цей Telegram уже прив'язаний до іншого акаунта COFI.", "This Telegram is already linked to another COFI account."),
    "Аккаунт не найден.": ("Акаунт не знайдено.", "Account not found."),
    "Готово! Уведомления COFI подключены: сюда будут приходить сообщения, пары и звонки.": (
        "Готово! Сповіщення COFI підключено: сюди надходитимуть повідомлення, пари та дзвінки.",
        "Done! COFI notifications are on: messages, matches and calls will come here."),
    "Готово! Уведомления COFI подключены: сюда будут приходить сообщения и пары.": (
        "Готово! Сповіщення COFI підключено: сюди надходитимуть повідомлення та пари.",
        "Done! COFI notifications are on: messages and matches will come here."),
    f"🌐 Открыть {APP} в браузере": (f"🌐 Відкрити {APP} у браузері", f"🌐 Open {APP} in browser"),
    f"Открыть {APP} в Telegram": (f"Відкрити {APP} у Telegram", f"Open {APP} in Telegram"),
    "Ссылка для входа устарела. Нажмите «Войти через Telegram» на сайте ещё раз.": (
        "Посилання для входу застаріло. Натисніть «Увійти через Telegram» на сайті ще раз.",
        "The sign-in link has expired. Tap “Sign in with Telegram” on the website again."),
    "✅ Войти": ("✅ Увійти", "✅ Sign in"),
    "Не получилось отправить, попробуйте ещё раз чуть позже.": (
        "Не вдалося надіслати, спробуйте ще раз трохи пізніше.", "Couldn't send it, please try again a bit later."),
    "Подключение отменено.": ("Підключення скасовано.", "Connection cancelled."),
    "Ссылка устарела, начните вход на сайте заново.": (
        "Посилання застаріло, почніть вхід на сайті заново.", "The link has expired, start signing in on the website again."),
    f"Готово! Вернитесь в браузер: вход в {APP} выполнен.": (
        f"Готово! Поверніться в браузер: вхід у {APP} виконано.", f"Done! Go back to your browser: you're signed in to {APP}."),
    "Вход отменён.": ("Вхід скасовано.", "Sign-in cancelled."),
    "Открыть чат": ("Відкрити чат", "Open chat"),
    "Написать": ("Написати", "Write"),
    "Перезвонить": ("Передзвонити", "Call back"),
    "✅ Ответить": ("✅ Відповісти", "✅ Answer"),
    "❌ Отклонить": ("❌ Відхилити", "❌ Decline"),
    "Звонок уже завершён": ("Дзвінок уже завершено", "The call has already ended"),
    "Принимаем текст и скриншоты. Голосовые и видео пока не открываются — опишите вопрос словами или пришлите скриншот.": (
        "Приймаємо текст і скриншоти. Голосові та відео поки не відкриваються — опишіть питання словами або надішліть скриншот.",
        "We accept text and screenshots. Voice messages and videos can't be opened yet — describe the problem in words or send a screenshot."),
    "Не получилось принять картинку. Пришлите её ещё раз или опишите словами.": (
        "Не вдалося прийняти зображення. Надішліть його ще раз або опишіть словами.",
        "Couldn't receive the picture. Send it again or describe it in words."),
    "📷 Фото": ("📷 Фото", "📷 Photo"),
    "🎬 Видео": ("🎬 Відео", "🎬 Video"),
    "🎤 Голосовое сообщение": ("🎤 Голосове повідомлення", "🎤 Voice message"),
    "⭕ Видеосообщение": ("⭕ Відеоповідомлення", "⭕ Video message"),
    "Стикер": ("Стікер", "Sticker"),
    "браузер": ("браузер", "browser"),
}

HELP_RU = (
    f"Привет! Это бот {APP}: знакомства и дружба по общим интересам.\n\n"
    "Как войти:\n1. Откройте сайт и нажмите «Войти через Telegram».\n2. Нажмите «Открыть Telegram», вы вернётесь сюда.\n"
    "3. Нажмите «✅ Войти», и браузер войдёт сам.\n\n"
    "Почта и пароль не нужны.\n\n"
    "💬 Вопрос, проблема или предложение? Просто напишите сюда сообщение — оно попадёт в поддержку, ответ придёт в этот чат."
)
T[HELP_RU] = (
    f"Привіт! Це бот {APP}: знайомства та дружба за спільними інтересами.\n\n"
    "Як увійти:\n1. Відкрийте сайт і натисніть «Увійти через Telegram».\n2. Натисніть «Відкрити Telegram», ви повернетеся сюди.\n"
    "3. Натисніть «✅ Увійти», і браузер увійде сам.\n\n"
    "Пошта й пароль не потрібні.\n\n"
    "💬 Запитання, проблема чи пропозиція? Просто напишіть сюди повідомлення — воно потрапить у підтримку, відповідь прийде в цей чат.",
    f"Hi! This is the {APP} bot: dating and friendship based on shared interests.\n\n"
    "How to sign in:\n1. Open the website and tap “Sign in with Telegram”.\n2. Tap “Open Telegram” — you'll come back here.\n"
    "3. Tap “✅ Sign in” and your browser will sign in by itself.\n\n"
    "No email or password needed.\n\n"
    "💬 A question, problem or idea? Just write a message here — it goes to support, and the reply will come to this chat.",
)

DESCRIPTION = {  # описание бота до /start — Telegram показывает его на языке приложения
    "uk": f"Вхід у {APP} без пошти й пароля. Натисніть «Увійти через Telegram» на сайті, потім «Запустити» тут і «✅ Увійти».",
    "en": f"Sign in to {APP} without email or password. Tap “Sign in with Telegram” on the website, then “Start” here and “✅ Sign in”.",
}
SHORT_DESCRIPTION = {"uk": f"Вхід у {APP}: знайомства та дружба за інтересами", "en": f"Sign in to {APP}: dating and friendship by interests"}
COMMANDS = {
    "uk": [{"command": "start", "description": "Як увійти на сайт"}, {"command": "help", "description": "Допомога"}],
    "en": [{"command": "start", "description": "How to sign in"}, {"command": "help", "description": "Help"}],
}


def _media(x: str, i: int) -> str:
    """Превью сообщения: «📷 Фото: подпись» — переводим только тип вложения, подпись человека не трогаем."""
    for ru, tr in T.items():
        if ru.startswith(("📷", "🎬", "🎤", "⭕")) and x.startswith(ru):
            return tr[i] + x[len(ru):]
    return T["Стикер"][i] if x == "Стикер" else x


def _p(uk, en):
    return (uk, en)


def _device(d: str, i: int) -> str:
    """«Яндекс Браузер, Android» / «браузер» → на языке чата."""
    return d.replace("Яндекс Браузер", ("Яндекс Браузер", "Yandex Browser")[i]).replace("браузер", ("браузер", "browser")[i])


# ---------- Фразы с подстановками ----------
P: list[tuple[re.Pattern, tuple]] = [
    (re.compile(r"^Подключить уведомления к аккаунту COFI (.+)\?\n\nЕсли это не ваш аккаунт или ссылку прислал кто-то другой, нажмите «Отмена»\.$", re.S),
     _p(lambda m: f"Підключити сповіщення до акаунта COFI {m[1].replace('без имени', 'без імені')}?\n\nЯкщо це не ваш акаунт або посилання надіслав хтось інший, натисніть «Скасувати».",
        lambda m: f"Connect notifications to the COFI account {m[1].replace('без имени', 'no name')}?\n\nIf this isn't your account or someone else sent you the link, tap “Cancel”.")),
    (re.compile(rf"^Войти в {re.escape(APP)}\?\n\nУстройство: (.+)\n\nЕсли вы не нажимали «Войти через Telegram» на сайте сами, нажмите «Отмена»\.$", re.S),
     _p(lambda m: f"Увійти в {APP}?\n\nПристрій: {_device(m[1], 0)}\n\nЯкщо ви не натискали «Увійти через Telegram» на сайті самі, натисніть «Скасувати».",
        lambda m: f"Sign in to {APP}?\n\nDevice: {_device(m[1], 1)}\n\nIf you didn't tap “Sign in with Telegram” on the website yourself, tap “Cancel”.")),
    (re.compile(r"^✉️ Вам пришло сообщение от (.+?)(?: \((\d+) непрочитанных\))?(?::\n(.*))?$", re.S),
     _p(lambda m: f"✉️ Вам надійшло повідомлення від {m[1]}{f' ({m[2]} непрочитаних)' if m[2] else ''}{f':{chr(10)}{_media(m[3], 0)}' if m[3] is not None else ''}",
        lambda m: f"✉️ New message from {m[1]}{f' ({m[2]} unread)' if m[2] else ''}{f':{chr(10)}{_media(m[3], 1)}' if m[3] is not None else ''}")),
    (re.compile(r"^🔥 Взаимно! Вы и (.+) понравились друг другу\. Напишите первым$", re.S),
     _p(lambda m: f"🔥 Взаємно! Ви та {m[1]} сподобалися одне одному. Напишіть першими",
        lambda m: f"🔥 It's a match! You and {m[1]} liked each other. Write first")),
    (re.compile(r"^📞 Звонок от (.+) завершён$", re.S), _p(lambda m: f"📞 Дзвінок від {m[1]} завершено", lambda m: f"📞 Call from {m[1]} ended")),
    (re.compile(r"^📵 Пропущенный (видеовызов|вызов) от (.+)$", re.S),
     _p(lambda m: f"📵 Пропущений {'відеодзвінок' if m[1] == 'видеовызов' else 'дзвінок'} від {m[2]}",
        lambda m: f"📵 Missed {'video call' if m[1] == 'видеовызов' else 'call'} from {m[2]}")),
    (re.compile(rf"^📞 (Видеозвонок|Звонок) от (.+)\nНажмите «Ответить», чтобы открыть {re.escape(APP)} и поговорить$", re.S),
     _p(lambda m: f"📞 {'Відеодзвінок' if m[1] == 'Видеозвонок' else 'Дзвінок'} від {m[2]}\nНатисніть «Відповісти», щоб відкрити {APP} і поговорити",
        lambda m: f"📞 {'Video call' if m[1] == 'Видеозвонок' else 'Call'} from {m[2]}\nTap “Answer” to open {APP} and talk")),
    (re.compile(r"^📞 Разговор с (.+)$", re.S), _p(lambda m: f"📞 Розмова з {m[1]}", lambda m: f"📞 Talking with {m[1]}")),
    (re.compile(r"^📞 Вы отклонили звонок от (.+)$", re.S), _p(lambda m: f"📞 Ви відхилили дзвінок від {m[1]}", lambda m: f"📞 You declined the call from {m[1]}")),
    (re.compile(r"^Спасибо! Обращение №(\d+) принято — ответим здесь, в этом чате, обычно в течение часа\.\nМожно дописать подробности или прислать ещё сообщения\.$", re.S),
     _p(lambda m: f"Дякуємо! Звернення №{m[1]} прийнято — відповімо тут, у цьому чаті, зазвичай протягом години.\nМожна дописати подробиці або надіслати ще повідомлення.",
        lambda m: f"Thank you! Request #{m[1]} received — we'll reply here in this chat, usually within an hour.\nYou can add details or send more messages.")),
    (re.compile(rf"^💬 Поддержка {re.escape(APP)}:\n\n(.*)$", re.S),
     _p(lambda m: f"💬 Підтримка {APP}:\n\n{m[1]}", lambda m: f"💬 {APP} support:\n\n{m[1]}")),
]


def tr(text: str, lang: str) -> str:
    """Перевод фразы бота на язык чата (неизвестная фраза — как есть)."""
    if lang not in ("uk", "en") or not text:
        return text
    i = 0 if lang == "uk" else 1
    if text in T:
        return T[text][i]
    for rx, out in P:
        m = rx.match(text)
        if m:
            return out[i](m)
    return text


def localize(method: str, payload: dict | None) -> dict | None:
    """Перевести сообщение бота перед отправкой. Рассылки из админки (HTML-разметка) и группы — без изменений."""
    if not payload or method not in ("sendMessage", "editMessageText") or payload.get("parse_mode"):
        return payload
    lang = chat_lang(payload.get("chat_id"))
    if lang == "ru":
        return payload
    out = dict(payload)
    if isinstance(out.get("text"), str):
        out["text"] = tr(out["text"], lang)
    kb = (out.get("reply_markup") or {}).get("inline_keyboard")
    if kb:
        out["reply_markup"] = {**out["reply_markup"], "inline_keyboard": [
            [{**b, "text": tr(b.get("text", ""), lang)} for b in row] for row in kb]}
    return out
