import hashlib
import hmac
import time

from app import config
from app.security import password_errors
from app.telegram_auth import verify_telegram_auth
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


def _tg_payload(token, **fields):
    data = {"id": 777, "first_name": "Котик", "username": "kotik", "auth_date": int(time.time()), **fields}
    check = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    data["hash"] = hmac.new(hashlib.sha256(token.encode()).digest(), check.encode(), hashlib.sha256).hexdigest()
    return data


def test_telegram_signature():
    data = _tg_payload("123:ABC")
    assert verify_telegram_auth(data, "123:ABC")
    assert not verify_telegram_auth({**data, "id": 778}, "123:ABC")
    assert not verify_telegram_auth(data, "other")
    old = _tg_payload("123:ABC", auth_date=int(time.time()) - 3 * 86400)
    assert not verify_telegram_auth(old, "123:ABC")


def test_telegram_login_creates_user_without_email(monkeypatch):
    monkeypatch.setattr(config.settings, "telegram_bot_token", "123:ABC")
    c = new_client()
    r = c.post("/api/auth/telegram", json=_tg_payload("123:ABC"))
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["auth_provider"] == "telegram" and me["email"] is None
    assert me["name"] == "Котик"
    assert not me["photo_verified"]  # фото всё равно нужно подтвердить
    assert c.get("/api/feed/dating").status_code == 409


def test_admin_email_auto_promoted():
    c = new_client()
    assert register(c, "boss@example.com")["is_admin"]
