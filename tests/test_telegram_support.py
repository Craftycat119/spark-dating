from unittest import mock

from conftest import make_user

from app import telegram_bot
from app.config import settings


def _private(text, chat_id=555, username="vasya", **extra):
    return {"message": {"message_id": 1, "chat": {"id": chat_id, "type": "private"},
                        "from": {"id": chat_id, "username": username, "is_bot": False}, "text": text, **extra}}


def test_message_to_bot_becomes_support_thread_and_staff_reply_goes_back(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    sent = []
    monkeypatch.setattr("app.push._in_background", lambda fn, *a: sent.append(a))

    calls = telegram_bot.handle_update(_private("Не приходит код на почту"))
    assert calls and "Обращение №" in calls[0][1]["text"]
    # второе сообщение — в то же обращение, без повторного «принято»
    assert telegram_bot.handle_update(_private("Почта ivan@mail.ru")) == []

    boss = make_user("boss@example.com", name="Андрей")
    threads = boss.get("/api/admin/support").json()
    t = next(x for x in threads if "vasya" in (x.get("contact") or ""))
    msgs = boss.get(f"/api/admin/support/{t['id']}").json()["messages"]
    assert [m["text"] for m in msgs if m["author"] == "user"] == ["Не приходит код на почту", "Почта ivan@mail.ru"]

    # ответ из админки — человеку в Telegram
    boss.post(f"/api/admin/support/{t['id']}/reply", json={"text": "Проверьте папку «Спам»"})
    assert any(a[0] == 555 and "Проверьте папку" in a[1] for a in sent)


def test_commands_still_show_help(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    calls = telegram_bot.handle_update(_private("/start"))
    assert "поддержку" in calls[0][1]["text"]


def test_reply_in_support_group_goes_to_user(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    monkeypatch.setattr(settings, "telegram_support_chat_id", "-1001")
    sent = []
    monkeypatch.setattr("app.push._in_background", lambda fn, *a: sent.append(a))
    telegram_bot.handle_update(_private("Помогите", chat_id=777, username="petya"))
    boss = make_user("boss@example.com", name="Андрей")
    tid = next(x for x in boss.get("/api/admin/support").json() if "petya" in (x.get("contact") or ""))["id"]

    group_reply = {"message": {"message_id": 9, "chat": {"id": -1001, "type": "supergroup"}, "from": {"id": 1, "is_bot": False},
                               "text": "Уже смотрим!",
                               "reply_to_message": {"from": {"is_bot": True}, "text": f"🆘 Нужна помощь #{tid} от гостя"}}}
    calls = telegram_bot.handle_update(group_reply)
    assert "Ответ отправлен" in calls[0][1]["text"]
    assert any(a[0] == 777 and "Уже смотрим" in a[1] for a in sent)
    # из чужой группы — нельзя
    sent.clear()
    group_reply["message"]["chat"]["id"] = -999
    assert telegram_bot.handle_update(group_reply) == []
    assert not sent



def test_service_broadcast_reaches_everyone_who_wrote_the_bot(monkeypatch):
    from app.database import SessionLocal
    from app.models import TelegramContact, User

    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    got = []
    monkeypatch.setattr("app.push.broadcast", lambda chats, text: got.append((sorted(chats), text)))
    boss = make_user("boss@example.com", name="Андрей")
    u = make_user("bc1@x.io", name="Без уведомлений")
    with SessionLocal() as db:
        x = db.get(User, u.user_id)
        x.telegram_id, x.tg_notifications = 4242, False
        db.add(TelegramContact(username="guest1", chat_id=5151))  # писал боту без аккаунта
        db.add(TelegramContact(username="somegroup", chat_id=-100777))  # группа — не трогаем
        db.commit()
    assert boss.post("/api/admin/broadcast", json={"subject": "Новость", "body": "x"}).json()["recipients"] == 0
    r = boss.post("/api/admin/broadcast", json={"subject": "Технические работы", "body": "y", "everyone": True}).json()
    assert r["recipients"] == 2 and got[-1][0] == [4242, 5151]
