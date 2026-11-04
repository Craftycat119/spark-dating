from app import config, telegram_bot
from app.security import password_errors
from conftest import new_client, register


def test_password_rules():
    assert password_errors("Secret123") == []
    assert len(password_errors("secret123")) == 1  # нет заглавной
    assert len(password_errors("SecretABC")) == 1  # нет цифры
    assert len(password_errors("Sec1")) == 1  # короткий
    assert len(password_errors("abc")) == 3


def test_register_verify_and_login():
    c = new_client()
    profile = register(c, "Anna@Example.com")
    assert profile["email"] == "anna@example.com"
    assert profile["email_verified"]
    assert c.get("/api/auth/me").status_code == 200

    c.post("/api/auth/logout")
    assert c.get("/api/auth/me").status_code == 401

    assert c.post("/api/auth/login", json={"email": "anna@example.com", "password": "Wrong1234"}).status_code == 401
    r = c.post("/api/auth/login", json={"email": "anna@example.com", "password": "Secret123"})
    assert r.status_code == 200
    assert c.get("/api/auth/me").json()["email"] == "anna@example.com"


def test_weak_password_rejected():
    r = new_client().post("/api/auth/register", json={"email": "a@b.co", "password": "password"})
    assert r.status_code == 422


def test_unverified_login_requires_code_and_wrong_code_fails():
    c = new_client()
    r = c.post("/api/auth/register", json={"email": "u@x.io", "password": "Secret123"})
    assert r.status_code == 200
    r = c.post("/api/auth/login", json={"email": "u@x.io", "password": "Secret123"})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "email_not_verified"
    assert c.post("/api/auth/verify-email", json={"email": "u@x.io", "code": "000000"}).status_code in (400,)


def test_code_attempts_limited():
    c = new_client()
    code = c.post("/api/auth/register", json={"email": "z@x.io", "password": "Secret123"}).json()["dev_code"]
    wrong = "111111" if code != "111111" else "222222"
    for _ in range(5):
        c.post("/api/auth/verify-email", json={"email": "z@x.io", "code": wrong})
    r = c.post("/api/auth/verify-email", json={"email": "z@x.io", "code": code})
    assert r.status_code == 400


def test_password_reset():
    c = new_client()
    register(c, "r@x.io")
    code = c.post("/api/auth/forgot-password", json={"email": "r@x.io"}).json()["dev_code"]
    r = c.post("/api/auth/reset-password", json={"email": "r@x.io", "code": code, "password": "NewPass99"})
    assert r.status_code == 200
    c2 = new_client()
    assert c2.post("/api/auth/login", json={"email": "r@x.io", "password": "NewPass99"}).status_code == 200


def _bot_confirms(token, action="ok", user_id=777):
    """Имитирует нажатие кнопки в боте: /start login_<токен>, затем «Войти» или «Отмена»."""
    calls = telegram_bot.handle_update({"message": {"chat": {"id": user_id}, "text": f"/start login_{token}"}})
    assert calls[0][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"ok:{token}"
    return telegram_bot.handle_update({"callback_query": {"id": "q1", "data": f"{action}:{token}",
                                       "from": {"id": user_id, "first_name": "Котик", "username": "kotik"},
                                       "message": {"chat": {"id": user_id}, "message_id": 5}}})


def test_telegram_not_configured():
    assert new_client().post("/api/auth/telegram/start").status_code == 503


def test_telegram_bot_login_creates_user_without_email(monkeypatch):
    monkeypatch.setattr(config.settings, "telegram_bot_token", "123:ABC")
    monkeypatch.setattr(telegram_bot, "_bot_username", "cofi_bot")
    c = new_client()
    start = c.post("/api/auth/telegram/start").json()
    assert start["url"].startswith("https://t.me/cofi_bot?start=login_")
    token = start["token"]
    assert c.post("/api/auth/telegram/poll", json={"token": token}).json()["status"] == "pending"
    _bot_confirms(token)
    r = c.post("/api/auth/telegram/poll", json={"token": token})
    assert r.status_code == 200, r.text
    me = r.json()["user"]
    assert me["auth_provider"] == "telegram" and me["email"] is None
    assert me["name"] == "Котик"
    assert not me["photo_verified"]  # фото всё равно нужно подтвердить
    assert c.get("/api/feed").status_code == 409
    # токен одноразовый
    assert c.post("/api/auth/telegram/poll", json={"token": token}).status_code == 410
    # повторный вход тем же Telegram попадает в тот же аккаунт
    t2 = c.post("/api/auth/telegram/start").json()["token"]
    _bot_confirms(t2)
    assert c.post("/api/auth/telegram/poll", json={"token": t2}).json()["user"]["id"] == me["id"]


def test_telegram_bot_decline_and_unknown_token(monkeypatch):
    monkeypatch.setattr(config.settings, "telegram_bot_token", "123:ABC")
    monkeypatch.setattr(telegram_bot, "_bot_username", "cofi_bot")
    c = new_client()
    token = c.post("/api/auth/telegram/start").json()["token"]
    _bot_confirms(token, action="no")
    assert c.post("/api/auth/telegram/poll", json={"token": token}).status_code == 403
    calls = telegram_bot.handle_update({"message": {"chat": {"id": 1}, "text": "/start login_fake"}})
    assert "устарела" in calls[0][1]["text"]


def test_admin_email_auto_promoted():
    c = new_client()
    assert register(c, "boss@example.com")["is_admin"]
