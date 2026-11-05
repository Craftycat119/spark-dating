import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from app import config, push, telegram_bot
from app.routers.auth import verify_webapp_init_data
from conftest import make_user, new_client, register

TOKEN = "123:ABC"


def _init_data(user, token=TOKEN, **extra):
    fields = {"auth_date": str(int(time.time())), "query_id": "q1", "user": json.dumps(user), **extra}
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_webapp_init_data_signature():
    data = _init_data({"id": 42, "first_name": "Андрей"})
    assert verify_webapp_init_data(data, TOKEN)["id"] == 42
    assert verify_webapp_init_data(data, "other") is None
    assert verify_webapp_init_data(data.replace("42", "43"), TOKEN) is None
    old = _init_data({"id": 42}, auth_date=str(int(time.time()) - 3 * 86400))
    assert verify_webapp_init_data(old, TOKEN) is None


def test_webapp_login_creates_telegram_user(monkeypatch):
    monkeypatch.setattr(config.settings, "telegram_bot_token", TOKEN)
    c = new_client()
    me = c.post("/api/auth/telegram/webapp", json={"init_data": _init_data({"id": 77, "first_name": "Котик", "username": "kot"})}).json()
    assert me["auth_provider"] == "telegram" and me["telegram_linked"] and me["tg_notifications"]


def test_link_telegram_to_email_account(monkeypatch):
    monkeypatch.setattr(config.settings, "telegram_bot_token", TOKEN)
    monkeypatch.setattr(telegram_bot, "_bot_username", "cofi_bot")
    c = new_client()
    register(c, "mail@x.io")
    url = c.post("/api/profile/telegram-link").json()["url"]
    token = url.split("start=link_")[1]
    calls = telegram_bot.handle_update({"message": {"chat": {"id": 555}, "from": {"id": 555, "username": "me"}, "text": f"/start link_{token}"}})
    assert "подключены" in calls[0][1]["text"]
    assert c.get("/api/profile").json()["telegram_linked"]


class FakeBot:
    def __init__(self):
        self.sent = []

    def __call__(self, method, payload=None, timeout=15):
        self.sent.append((method, payload))
        return {"ok": True, "result": {"message_id": len(self.sent)}}


def test_offline_call_and_message_notifications(monkeypatch):
    bot = FakeBot()
    monkeypatch.setattr(config.settings, "telegram_bot_token", TOKEN)
    monkeypatch.setattr(config.settings, "base_url", "https://cofi.example")
    monkeypatch.setattr(telegram_bot, "api", bot)
    monkeypatch.setattr(push, "_in_background", lambda fn, *a: fn(*a))
    a, b = make_user("ca@x.io", name="Аня"), make_user("cb@x.io", name="Борис")
    ida, idb = a.get("/api/profile").json()["id"], b.get("/api/profile").json()["id"]
    from app.database import SessionLocal
    from app.models import User

    with SessionLocal() as db:
        db.get(User, idb).telegram_id = 9001
        db.commit()
    a.post("/api/feed/swipe", json={"user_id": idb, "like": True})
    conv = b.post("/api/feed/swipe", json={"user_id": ida, "like": True}).json()["conversation_id"]
    bot.sent.clear()
    # сообщение человеку не в сети приходит в Telegram с кнопкой «Открыть чат»
    a.post(f"/api/chats/{conv}/messages", json={"text": "Привет!"})
    method, payload = bot.sent[0]
    assert method == "sendMessage" and payload["chat_id"] == 9001 and "Аня: Привет!" in payload["text"]
    assert payload["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"] == f"https://cofi.example/?chat={conv}"
    a.post(f"/api/chats/{conv}/messages", json={"text": "Ещё"})
    assert len(bot.sent) == 1  # не чаще раза в минуту на чат
    # звонок: «Ответить» открывает COFI, «Отклонить» сбрасывает звонок
    with SessionLocal() as db:
        callee = db.get(User, idb)
        call = push.PendingCall(call_id="c1", conversation_id=conv, caller_id=ida, caller_name="Аня", callee_id=idb, video=True, sdp={"type": "offer"})
        assert push.offer(call, callee)
    _, payload = bot.sent[-1]
    row = payload["reply_markup"]["inline_keyboard"][0]
    assert "Видеозвонок от Аня" in payload["text"] and row[0]["web_app"]["url"].endswith("?call=c1") and row[1]["callback_data"] == "callno:c1"
    push.add_ice("c1", ida, {"candidate": "x"})
    push.add_ice("c1", idb, {"candidate": "чужой"})
    p = push.take("c1", idb)
    assert p and p.ice == [{"candidate": "x"}] and push.take("c1", ida) is None
    assert "отклонили" in push.decline_from_telegram("c1", 9001)
    assert push.take("c1", idb) is None


def test_call_to_offline_user_via_telegram(monkeypatch):
    """Собеседник не в сети: звонящему приходит call:notified, а открывший COFI собеседник забирает звонок через call:join."""
    from fastapi.testclient import TestClient

    from app.database import SessionLocal
    from app.main import app
    from app.models import User
    from test_app import cookie

    bot = FakeBot()
    monkeypatch.setattr(config.settings, "telegram_bot_token", TOKEN)
    monkeypatch.setattr(config.settings, "base_url", "https://cofi.example")
    monkeypatch.setattr(telegram_bot, "api", bot)
    a, b = make_user("oa@x.io"), make_user("ob@x.io")
    with SessionLocal() as db:
        db.get(User, b.user_id).telegram_id = 9002
        db.commit()
    a.post("/api/feed/swipe", json={"user_id": b.user_id, "like": True})
    conv = b.post("/api/feed/swipe", json={"user_id": a.user_id, "like": True}).json()["conversation_id"]
    with TestClient(app) as hub, hub.websocket_connect("/ws", headers=cookie(a)) as wa:
        wa.send_json({"type": "call:offer", "conversation_id": conv, "sdp": {"type": "offer", "sdp": "x"}, "video": False, "call_id": "k1"})
        assert wa.receive_json()["type"] == "call:notified"
        assert any("Звонок от" in (p or {}).get("text", "") for _, p in bot.sent)
        wa.receive_json()  # запись о звонке в чате
        wa.send_json({"type": "call:ice", "conversation_id": conv, "call_id": "k1", "candidate": {"candidate": "c"}})
        with hub.websocket_connect("/ws", headers=cookie(b)) as wb:
            wb.send_json({"type": "call:join", "call_id": "k1"})
            got = wb.receive_json()
            assert got["type"] == "call:offer" and got["answer_now"] and got["sdp"]["sdp"] == "x"
            assert wb.receive_json() == {"type": "call:ice", "conversation_id": conv, "call_id": "k1", "candidate": {"candidate": "c"}}
            wb.send_json({"type": "call:answer", "conversation_id": conv, "sdp": {"type": "answer", "sdp": "y"}, "call_id": "k1"})
            assert wa.receive_json()["type"] == "call:answer"
