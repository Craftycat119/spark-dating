import pytest
from fastapi.testclient import TestClient

from app.geo import public_distance_km
from app.main import app
from conftest import make_user, new_client, register


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
