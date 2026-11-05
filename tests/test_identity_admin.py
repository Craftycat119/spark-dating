from app import config, push, telegram_bot
from app.ages import birth_for_age
from app.interests import compatible
from conftest import make_user, new_client, register
from test_push import TOKEN, FakeBot


def test_trans_gender_matching_and_teen_limit():
    assert compatible("female", "male", "trans_male", "female")  # ищет парня — трансгендерный парень подходит
    assert not compatible("female", "female", "trans_male", "any")
    c = new_client()
    register(c, "teen@x.io")
    base = {"name": "Миша", "birth_date": birth_for_age(15).isoformat(), "looking_for": "any", "accept_terms": True, "confirm_age": True}
    assert c.put("/api/profile", json={**base, "gender": "trans_male"}).status_code == 422
    me = c.put("/api/profile", json={**base, "gender": "male", "orientation": "bi"}).json()
    assert me["gender"] == "male" and me["orientation"] is None  # подросткам ориентацию не храним


def test_orientation_shown_only_when_allowed():
    a = make_user("i1@x.io", gender="female", looking_for="any")
    b = make_user("i2@x.io", gender="trans_male", looking_for="any")
    b.put("/api/profile", json={"orientation": "pan"})
    card = a.get(f"/api/users/{b.user_id}").json()
    assert card["gender_label"] == "Трансгендерный парень" and card["orientation_label"] == "Пансексуал"
    b.put("/api/profile", json={"show_identity": False})
    card = a.get(f"/api/users/{b.user_id}").json()
    assert card["gender_label"] is None and card["orientation_label"] is None


def test_admin_without_profile_and_support_to_telegram(monkeypatch):
    boss = make_user("boss@example.com", name="Админ")  # ADMIN_EMAILS в conftest
    r = boss.post("/api/admin/admins", json={"name": "Оля", "email": "olya@x.io", "password": "Secret123"})
    assert r.status_code == 200 and r.json()["is_admin"]
    olya = new_client()
    me = olya.post("/api/auth/login", json={"email": "olya@x.io", "password": "Secret123"}).json()
    assert me["is_admin"] and me["name"] == "Оля" and me["terms_accepted"]
    # обращение пользователя уходит админам в Telegram
    bot = FakeBot()
    monkeypatch.setattr(config.settings, "telegram_bot_token", TOKEN)
    monkeypatch.setattr(config.settings, "telegram_admin_chat_id", "-100500")
    monkeypatch.setattr(telegram_bot, "api", bot)
    monkeypatch.setattr(push, "_in_background", lambda fn, *a: fn(*a))
    u = make_user("user@x.io", name="Вася")
    u.post("/api/support/threads", json={"category": "complaint", "text": "Мне пишут гадости"})
    sent = [p for m, p in bot.sent if m == "sendMessage"]
    assert sent and sent[0]["chat_id"] == "-100500" and "⚠️ Жалоба" in sent[0]["text"] and "Вася" in sent[0]["text"]
