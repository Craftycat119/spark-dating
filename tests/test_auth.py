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
    assert r.status_code == 200 and r.json()["status"] == "code_required"
    assert c.get("/api/auth/me").status_code == 401  # один пароль не впускает — нужен код из письма
    assert c.post("/api/auth/login/verify", json={"email": "anna@example.com", "code": "000000"}).status_code == 400
    r = c.post("/api/auth/login/verify", json={"email": "anna@example.com", "code": r.json()["dev_code"]})
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
    r = c2.post("/api/auth/login", json={"email": "r@x.io", "password": "NewPass99"})
    assert r.status_code == 200 and r.json()["status"] == "code_required"


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


def test_telegram_bot_help_and_site_button(monkeypatch):
    calls = telegram_bot.handle_update({"message": {"chat": {"id": 5}, "text": "/start"}})
    assert "Войти через Telegram" in calls[0][1]["text"] and "reply_markup" not in calls[0][1]  # localhost: без кнопки
    monkeypatch.setattr(config.settings, "base_url", "https://cofi.example")
    calls = telegram_bot.handle_update({"message": {"chat": {"id": 5}, "text": "/help"}})  # обычный текст теперь идёт в поддержку
    assert calls[0][1]["reply_markup"]["inline_keyboard"][0][0]["url"] == "https://cofi.example"


def test_bot_menu_button_follows_base_url(monkeypatch):
    sent = []
    monkeypatch.setattr(telegram_bot, "api", lambda m, p=None, timeout=15: sent.append((m, p)) or {"ok": True})
    monkeypatch.setattr(config.settings, "base_url", "https://new-tunnel.trycloudflare.com")
    monkeypatch.setattr(telegram_bot, "_reachable", lambda url: True)
    telegram_bot.setup_profile()
    menu = [p for m, p in sent if m == "setChatMenuButton"]
    assert menu and menu[0]["menu_button"]["web_app"]["url"] == "https://new-tunnel.trycloudflare.com/"



def test_stale_tunnel_address_is_not_put_into_bot(monkeypatch):
    sent = []
    monkeypatch.setattr(telegram_bot, "api", lambda m, p=None, timeout=15: sent.append(m) or {"ok": True})
    monkeypatch.setattr(config.settings, "base_url", "https://old-tunnel.trycloudflare.com")
    monkeypatch.setattr(telegram_bot, "_reachable", lambda url: False)
    telegram_bot.setup_profile()
    assert "setChatMenuButton" not in sent



def test_login_resend_only_after_correct_password():
    c = new_client()
    register(c, "z@x.io")
    c.post("/api/auth/logout")
    assert new_client().post("/api/auth/login/resend", json={"email": "z@x.io"}).status_code == 400  # пароль не вводили
    first = c.post("/api/auth/login", json={"email": "z@x.io", "password": "Secret123"}).json()
    assert first["status"] == "code_required"
    again = c.post("/api/auth/login", json={"email": "z@x.io", "password": "Secret123"}).json()
    assert again["status"] == "code_pending"  # повторное «Войти» в течение минуты — тот же код
    r = c.post("/api/auth/login/verify", json={"email": "z@x.io", "code": first["dev_code"]})
    assert r.status_code == 200
    # код одноразовый
    c3 = new_client()
    assert c3.post("/api/auth/login/verify", json={"email": "z@x.io", "code": first["dev_code"]}).status_code == 400



def test_login_without_code_when_switched_off(monkeypatch):
    from app.config import settings

    c = new_client()
    register(c, "nocode@x.io")
    c.post("/api/auth/logout")
    monkeypatch.setattr(settings, "login_email_code", False)
    r = c.post("/api/auth/login", json={"email": "nocode@x.io", "password": "Secret123"})
    assert r.status_code == 200 and r.json()["email"] == "nocode@x.io"  # сразу профиль, без кода
    assert c.get("/api/auth/me").status_code == 200
    # регистрация по-прежнему с кодом
    r = new_client().post("/api/auth/register", json={"email": "fresh@x.io", "password": "Secret123"})
    assert r.json()["status"] == "code_sent"
