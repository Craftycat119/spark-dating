"""Бот отвечает на языке Telegram человека: украинский, русский, английский."""
import io
import json
import re

from conftest import make_user

from app import bot_i18n, push, telegram_bot
from app.config import settings

RU_ONLY = re.compile(r"[ыэъЫЭЪёЁ]")  # таких букв нет в украинском
CYR = re.compile(r"[А-Яа-яЁёІіЇїЄєҐґ]")


class _Net:
    """Подменяет сеть: запоминает, что бот на самом деле отправил в Telegram (уже переведённым)."""

    def __init__(self):
        self.sent = []

    def __call__(self, req, timeout=15):
        self.sent.append((req.full_url.rsplit("/", 1)[-1], json.loads(req.data or b"{}")))
        return io.BytesIO(json.dumps({"ok": True, "result": {"message_id": 7}}).encode())


def _run(calls):
    for method, payload in calls:
        telegram_bot.api(method, payload)


def _check(text, lang):
    if lang == "en":
        assert not CYR.search(text), text
    elif lang == "uk":
        assert not RU_ONLY.search(text), text


def test_bot_speaks_telegram_language(monkeypatch):
    net = _Net()
    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    monkeypatch.setattr(telegram_bot.urllib.request, "urlopen", net)
    monkeypatch.setattr(push, "_in_background", lambda fn, *a: fn(*a) if fn in (push._send, push._edit) else None)
    bot_i18n._cache.clear()

    for chat, code, lang, hello in ((501, "uk", "uk", "Привіт! Це бот"), (502, "en-US", "en", "Hi! This is the"), (503, "ru", "ru", "Привет! Это бот")):
        net.sent.clear()
        frm = {"id": chat, "username": f"u{chat}", "language_code": code}
        _run(telegram_bot.handle_update({"message": {"message_id": 1, "chat": {"id": chat, "type": "private"}, "from": frm, "text": "/start"}}))
        text = net.sent[0][1]["text"]
        assert text.startswith(hello), text
        buttons = [b["text"] for row in net.sent[0][1].get("reply_markup", {}).get("inline_keyboard", []) for b in row]
        for x in buttons + [text]:
            _check(x, lang)

        # вход через Telegram: вопрос, кнопки и ответ после «Войти»
        token = telegram_bot.new_login("Яндекс Браузер, Android")["token"]
        net.sent.clear()
        _run(telegram_bot.handle_update({"message": {"message_id": 2, "chat": {"id": chat, "type": "private"}, "from": frm,
                                                     "text": f"/start login_{token}"}}))
        q = net.sent[0][1]
        for x in [q["text"]] + [b["text"] for b in q["reply_markup"]["inline_keyboard"][0]]:
            _check(x, lang)
        net.sent.clear()
        _run(telegram_bot.handle_update({"callback_query": {"id": "c", "data": f"ok:{token}", "from": frm,
                                                            "message": {"message_id": 3, "chat": {"id": chat, "type": "private"}}}}))
        done = [p["text"] for m, p in net.sent if m == "editMessageText"][0]
        _check(done, lang)
        assert ("Готово" in done) if lang != "en" else done.startswith("Done!")

    # уведомления без нового сообщения от человека — на запомненном языке
    u = make_user("uk-notify@x.io", name="Оксана")
    from app.database import SessionLocal
    from app.models import User

    with SessionLocal() as db:
        row = db.get(User, u.user_id)
        row.telegram_id, row.tg_notifications = 501, True
        db.commit()
        rec = db.get(User, u.user_id)
    monkeypatch.setattr(push, "away", lambda uid: True)
    net.sent.clear()
    push.notify_message(rec, "Тарас", 1, "🎤 Голосовое сообщение")
    push.notify_match(rec, "Тарас", 1)
    texts = [p["text"] for _, p in net.sent]
    assert any(t.startswith("✉️ Вам надійшло повідомлення від Тарас") and "Голосове повідомлення" in t for t in texts), texts
    assert any(t.startswith("🔥 Взаємно!") for t in texts), texts
    for _, p in net.sent:
        _check(p["text"], "uk")
        for row in p.get("reply_markup", {}).get("inline_keyboard", []):
            for b in row:
                _check(b["text"], "uk")


def test_phrases_with_names_and_untouched_texts():
    assert bot_i18n.tr("📵 Пропущенный видеовызов от Ани", "en") == "📵 Missed video call from Ани"
    assert bot_i18n.tr(f"📞 Звонок от Ани\nНажмите «Ответить», чтобы открыть {settings.app_name} и поговорить", "uk").startswith("📞 Дзвінок від Ани")
    assert bot_i18n.tr("Спасибо! Обращение №12 принято — ответим здесь, в этом чате, обычно в течение часа.\n"
                       "Можно дописать подробности или прислать ещё сообщения.", "en").startswith("Thank you! Request #12")
    # ответ оператора: переводится только заголовок, текст сотрудника как есть
    assert bot_i18n.tr(f"💬 Поддержка {settings.app_name}:\n\nПроверьте папку «Спам»", "uk") == f"💬 Підтримка {settings.app_name}:\n\nПроверьте папку «Спам»"
    # рассылка из админки (HTML) не переводится, русскому — без изменений, группы поддержки — по-русски
    bot_i18n._cache[777] = "en"
    html = {"chat_id": 777, "text": "<b>Безопасность</b>", "parse_mode": "HTML"}
    assert bot_i18n.localize("sendMessage", html) == html
    assert bot_i18n.chat_lang(-100123) == "ru"
    assert bot_i18n.lang_from_code("be") == "ru" and bot_i18n.lang_from_code("de") == "en" and bot_i18n.lang_from_code(None) is None
