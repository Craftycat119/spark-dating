import base64
import hashlib
import hmac

import pytest
from fastapi.testclient import TestClient

from app import config, ratelimit, security_log, telegram_bot
from app.geo import public_distance_km
from app.main import app
from conftest import make_user, new_client, register
from test_push import TOKEN, FakeBot


def test_code_never_shown_through_tunnel():
    """Через туннель или прокси код подтверждения не показывается: иначе можно зарегистрироваться на чужую почту."""
    c = new_client()
    r = c.post("/api/auth/register", json={"email": "victim@x.io", "password": "Secret123"}, headers={"X-Forwarded-For": "1.2.3.4"})
    assert "dev_code" not in r.text
    r = c.post("/api/auth/register", json={"email": "v2@x.io", "password": "Secret123"}, headers={"CF-Connecting-IP": "1.2.3.4"})
    assert "dev_code" not in r.text
    c2 = new_client()
    register(c2, "owner@x.io")
    r = c2.post("/api/auth/forgot-password", json={"email": "owner@x.io"}, headers={"X-Forwarded-For": "5.6.7.8"})
    assert "dev_code" not in r.text


def test_login_bruteforce_is_limited():
    c = new_client()
    register(c, "brute@x.io")
    codes = [new_client().post("/api/auth/login", json={"email": "brute@x.io", "password": f"Wrong{i}x"}).status_code for i in range(12)]
    assert codes[:10] == [401] * 10 and codes[10] == 429


def test_distance_is_coarse():
    # сдвиг на 300 м не меняет показанное расстояние, и оно всегда в целых километрах
    assert public_distance_km(55.75, 37.61, 55.80, 37.70) == public_distance_km(55.7505, 37.6105, 55.8002, 37.7001)
    assert isinstance(public_distance_km(55.75, 37.61, 55.7501, 37.6101), int)
    assert public_distance_km(55.75, 37.61, 55.7501, 37.6101) >= 1


def test_security_headers_and_private_api():
    r = new_client().get("/api/config")
    assert r.headers["x-content-type-options"] == "nosniff" and "frame-ancestors" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"


def test_websocket_from_foreign_site_rejected():
    a = make_user("ws@x.io")
    from test_app import cookie
    from starlette.websockets import WebSocketDisconnect

    with TestClient(app) as hub:
        with pytest.raises(WebSocketDisconnect):
            with hub.websocket_connect("/ws", headers={**cookie(a), "origin": "https://evil.example"}) as ws:
                ws.receive_text()


def test_private_data_not_leaked_in_public_profile():
    a, b = make_user("pa@x.io"), make_user("pb@x.io")
    card = a.get(f"/api/users/{b.user_id}").json()
    for field in ("email", "lat", "lon", "telegram_id", "telegram_username", "registration_ip", "birth_date"):
        assert field not in card
    assert a.get("/api/admin/users").status_code == 403


def test_calls_disabled_hides_and_blocks(monkeypatch):
    from app import config

    monkeypatch.setattr(config.settings, "calls_enabled", False)
    assert new_client().get("/api/config").json()["calls_enabled"] is False
    a, b = make_user("ca1@x.io"), make_user("cb1@x.io")
    a.post("/api/feed/swipe", json={"user_id": b.user_id, "like": True})
    conv = b.post("/api/feed/swipe", json={"user_id": a.user_id, "like": True}).json()["conversation_id"]
    from test_app import cookie

    with TestClient(app) as hub, hub.websocket_connect("/ws", headers=cookie(a)) as wa, hub.websocket_connect("/ws", headers=cookie(b)) as wb:
        wa.send_json({"type": "call:offer", "conversation_id": conv, "sdp": {"type": "offer", "sdp": "x"}, "call_id": "z"})
        wa.send_json({"type": "ping"})
        assert wa.receive_json()["type"] == "pong"  # звонок молча не принят
        wb.send_json({"type": "ping"})
        assert wb.receive_json()["type"] == "pong"  # собеседнику ничего не пришло


# ---------- исправления по аудиту безопасности ----------
def test_turn_password_not_public(monkeypatch):
    monkeypatch.setattr(config.settings, "ice_servers", [{"urls": ["turn:x"], "username": "cofi", "credential": "SECRET"}])
    monkeypatch.setattr(config.settings, "turn_urls", ["turn:cofilove.com:3478"])
    monkeypatch.setattr(config.settings, "turn_secret", "shared-secret")
    anon = new_client()
    assert "SECRET" not in anon.get("/api/config").text and "credential" not in anon.get("/api/config").text
    assert anon.get("/api/calls/ice").status_code == 401  # без входа — ничего
    u = make_user("ice@x.io")
    ice = u.get("/api/calls/ice").json()
    turn = next(s for s in ice if "credential" in s)
    expected = base64.b64encode(hmac.new(b"shared-secret", turn["username"].encode(), hashlib.sha1).digest()).decode()
    assert turn["credential"] == expected and turn["username"].endswith(f":{u.user_id}")  # временный, на этого человека
    monkeypatch.setattr(config.settings, "calls_enabled", False)
    assert u.get("/api/calls/ice").status_code == 403  # звонки выключены — TURN не выдаём


def test_chat_rate_limits():
    a = make_user("r1@x.io", gender="female", looking_for="any")
    b = make_user("r2@x.io", gender="male", looking_for="any")
    b.post("/api/feed/swipe", json={"user_id": a.user_id, "like": True})
    conv = a.post("/api/feed/swipe", json={"user_id": b.user_id, "like": True}).json()["conversation_id"]
    codes = [a.post(f"/api/chats/{conv}/messages", json={"text": f"спам {i}"}).status_code for i in range(32)]
    assert codes[:30] == [200] * 30 and codes[30] == 429


def test_guest_cookie_secure_over_https():
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app, base_url="https://testserver")  # как на сервере за https
    r = c.post("/api/support/threads", json={"topic": "ads"})
    assert "secure" in r.headers["set-cookie"].lower()


def test_suspicious_activity_alert(monkeypatch):
    bot = FakeBot()
    monkeypatch.setattr(config.settings, "telegram_bot_token", TOKEN)
    monkeypatch.setattr(config.settings, "telegram_admin_chat_id", "-1009")
    monkeypatch.setattr(telegram_bot, "api", bot)
    monkeypatch.setattr(security_log, "THRESHOLD", 5)
    monkeypatch.setattr(security_log, "_last_alert", 0.0)
    security_log._events.clear()
    monkeypatch.setattr(security_log.threading, "Thread", lambda target, args, daemon: type("T", (), {"start": lambda s: target(*args)})())
    c = new_client()
    for _ in range(5):
        c.post("/api/auth/login", json={"email": "nobody@x.io", "password": "Wrong12345"})
    alerts = [p for m, p in bot.sent if m == "sendMessage" and "подозрительная активность" in p["text"]]
    assert alerts and alerts[0]["chat_id"] == "-1009" and "неудачный вход" in alerts[0]["text"]
    ratelimit._hits.clear()


def test_failed_email_does_not_block_retry(monkeypatch):
    from app import emailer
    from app.config import settings

    monkeypatch.setattr(settings, "smtp_host", "smtp.example")
    monkeypatch.setattr(settings, "dev_mode", False)
    monkeypatch.setattr(emailer, "send_code", lambda *a: False)  # почтовый сервис отказал
    c = new_client()
    r = c.post("/api/auth/register", json={"email": "fail@x.io", "password": "Secret123"})
    assert r.status_code == 502
    r = c.post("/api/auth/register", json={"email": "fail@x.io", "password": "Secret123"})
    assert r.status_code == 502  # снова честная ошибка, а не «код уже отправлен»


def test_mini_app_cookie_works_inside_telegram_web(monkeypatch):
    import hashlib
    import hmac
    import json
    import time
    from urllib.parse import urlencode

    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr(config.settings, "telegram_bot_token", "123:TEST")
    fields = {"auth_date": str(int(time.time())), "user": json.dumps({"id": 777, "first_name": "Андрей"})}
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", b"123:TEST", hashlib.sha256).digest()
    init_data = urlencode({**fields, "hash": hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()})
    c = TestClient(app, base_url="https://testserver")
    r = c.post("/api/auth/telegram/webapp", json={"init_data": init_data})
    cookie = r.headers["set-cookie"].lower()
    assert r.status_code == 200 and "samesite=none" in cookie and "partitioned" in cookie and "secure" in cookie
    assert c.get("/api/auth/me").status_code == 200  # с этой cookie вход держится


def test_cross_site_requests_rejected():
    u = make_user("csrf@x.io")
    assert u.put("/api/profile", json={"bio": "x"}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert u.put("/api/profile", json={"bio": "свой"}, headers={"Origin": "http://testserver"}).status_code == 200
    assert u.put("/api/profile", json={"bio": "без Origin"}).status_code == 200  # не браузер — сессия всё равно нужна


def test_csp_allows_camera_preview():
    csp = new_client().get("/").headers["content-security-policy"]
    assert "mediastream:" in csp.split("media-src", 1)[1].split(";", 1)[0]  # иначе камера на iPhone чёрная


def test_static_is_versioned_and_cached():
    from fastapi.testclient import TestClient

    from app import assets
    from app.main import app

    c = TestClient(app)
    html = c.get("/").text
    v = assets.version()
    assert f'src="/static/v/{v}/js/app.js"' in html
    assert f'rel="modulepreload" href="/static/v/{v}/js/ui.js"' in html
    assert 'href="/static/manifest.webmanifest"' in html  # manifest и иконки — на постоянных адресах
    r = c.get(f"/static/v/{v}/js/app.js")
    assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
    assert c.get("/static/v/old/js/app.js").headers["cache-control"] == "no-cache"  # старая версия не залипает
    assert c.get(f"/static/v/{v}/../../app/config.py").status_code == 404
    assert c.get("/static/js/app.js").headers["cache-control"] == "no-cache"
    assert "/static/v/" in c.get("/admin").text
