import time

from app import captcha, config
from app.security import hash_secret
from conftest import jpeg_bytes, make_user, new_client


def _known(c):
    cid = c.get("/api/auth/captcha").json()["id"]
    captcha._store[cid] = (hash_secret("23456"), time.time())  # подменяем ответ, чтобы не распознавать картинку
    return cid


def test_robot_check_on_register_and_login(monkeypatch):
    monkeypatch.setattr(config.settings, "captcha_mode", "image")
    c = new_client()
    r = c.get("/api/auth/captcha").json()
    assert r["mode"] == "image" and r["image"].startswith("data:image/png;base64,")
    body = {"email": "bot@x.io", "password": "Secret123"}
    assert c.post("/api/auth/register", json=body).json()["detail"]["code"] == "captcha"
    assert c.post("/api/auth/register", json={**body, "captcha_id": _known(c), "captcha": "11111"}).status_code == 400
    cid = _known(c)
    r = c.post("/api/auth/register", json={**body, "captcha_id": cid, "captcha": "23456"})
    assert r.status_code == 200 and r.json()["dev_code"]
    assert c.post("/api/auth/register", json={**body, "captcha_id": cid, "captcha": "23456"}).status_code == 400  # одноразовая
    c.post("/api/auth/verify-email", json={"email": "bot@x.io", "code": r.json()["dev_code"]})
    c2 = new_client()
    assert c2.post("/api/auth/login", json=body).status_code == 400
    assert c2.post("/api/auth/login", json={**body, "captcha_id": _known(c2), "captcha": "23456"}).status_code == 200
    assert c2.post("/api/auth/forgot-password", json={"email": "bot@x.io"}).status_code == 400


def test_chat_files_only_for_participants_and_admin():
    a, b, stranger = make_user("fa@x.io"), make_user("fb@x.io"), make_user("fc@x.io")
    boss = make_user("boss@example.com")  # ADMIN_EMAILS
    a.post("/api/feed/swipe", json={"user_id": b.user_id, "like": True})
    conv = b.post("/api/feed/swipe", json={"user_id": a.user_id, "like": True}).json()["conversation_id"]
    url = a.post(f"/api/chats/{conv}/media", data={"kind": "image"}, files={"file": ("p.jpg", jpeg_bytes(), "image/jpeg")}).json()["media_url"]
    assert a.get(url).status_code == 200 and b.get(url).status_code == 200
    assert boss.get(url).status_code == 200
    assert stranger.get(url).status_code == 403
    assert new_client().get(url).status_code == 401
