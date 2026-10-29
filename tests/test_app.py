from fastapi.testclient import TestClient

from app.main import app
from conftest import jpeg_bytes, make_user, new_client, register


def cookie(client):
    return {"cookie": f"spark_session={client.cookies['spark_session']}"}


def test_feed_requires_complete_profile():
    c = new_client()
    register(c, "x@x.io")
    r = c.get("/api/feed/dating")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "profile_incomplete"


def test_underage_rejected():
    c = new_client()
    register(c, "kid@x.io")
    assert c.put("/api/profile", json={"age": 16}).status_code == 422


def test_feeds_sorted_by_distance_and_radius():
    me = make_user("me@x.io", lat=55.75, lon=37.61)
    make_user("far@x.io", name="Далеко", lat=55.95, lon=37.61)      # ~22 км
    make_user("near@x.io", name="Рядом", lat=55.76, lon=37.61)      # ~1 км
    make_user("moon@x.io", name="Питер", lat=59.93, lon=30.33)      # ~630 км
    make_user("friends@x.io", name="Друг", lat=55.75, lon=37.62, feeds=("friends",))

    cards = me.get("/api/feed/dating").json()["cards"]
    assert [c["name"] for c in cards] == ["Рядом", "Далеко"]
    assert cards[0]["distance_km"] < 2

    me.put("/api/profile", json={"max_distance_km": 5})
    assert [c["name"] for c in me.get("/api/feed/dating").json()["cards"]] == ["Рядом"]

    # В ленту дружбы нельзя без включения показа себя в ней
    assert me.get("/api/feed/friends").status_code == 409
    me.put("/api/profile", json={"feeds": {"friends": {"enabled": True}}})
    assert [c["name"] for c in me.get("/api/feed/friends").json()["cards"]] == ["Друг"]


def test_per_feed_bio():
    me = make_user("me@x.io", feeds=("dating", "friends"))
    other = make_user("o@x.io", feeds=("dating", "friends"), bio="Общее")
    other.put("/api/profile", json={"use_common_bio": False, "feeds": {"friends": {"bio": "Ищу на футбол"}}})
    assert me.get("/api/feed/friends").json()["cards"][0]["bio"] == "Ищу на футбол"
    # Для ленты без своего описания берётся общее
    assert me.get("/api/feed/dating").json()["cards"][0]["bio"] == "Общее"
    other.put("/api/profile", json={"use_common_bio": True})
    assert me.get("/api/feed/friends").json()["cards"][0]["bio"] == "Общее"


def test_new_photo_requires_reverification():
    me = make_user("me@x.io")
    r = me.post("/api/profile/photo", files={"file": ("b.jpg", jpeg_bytes("blue"), "image/jpeg")})
    assert r.json()["photo_verified"] is False
    assert me.get("/api/feed/dating").status_code == 409


def test_match_chat_and_privacy():
    a = make_user("a@x.io", name="Аня")
    b = make_user("b@x.io", name="Боря")
    stranger = make_user("s@x.io", name="Чужой")

    r = a.post("/api/feed/dating/swipe", json={"user_id": b.user_id, "like": True})
    assert r.json() == {"match": False}
    # До метча чатов нет
    assert a.get("/api/chats").json() == []

    with b.websocket_connect("/ws") as ws:
        r = b.post("/api/feed/dating/swipe", json={"user_id": a.user_id, "like": True})
        assert r.json()["match"] is True
        conv_id = r.json()["conversation_id"]
        event = ws.receive_json()
        assert event["type"] == "match" and event["user"]["name"] == "Аня"

        r = a.post(f"/api/chats/{conv_id}/messages", json={"text": "Привет!"})
        assert r.status_code == 200
        event = ws.receive_json()
        assert event["type"] == "message" and event["message"]["text"] == "Привет!"

    # Свайпнутые анкеты больше не показываются
    assert all(c["id"] != b.user_id for c in a.get("/api/feed/dating").json()["cards"])

    r = a.post(f"/api/chats/{conv_id}/media", data={"kind": "image"},
               files={"file": ("p.jpg", jpeg_bytes(), "image/jpeg")})
    assert r.status_code == 200
    url = r.json()["media_url"]
    assert a.get(url).status_code == 200
    assert b.get(url).status_code == 200
    assert stranger.get(url).status_code == 403

    r = b.post(f"/api/chats/{conv_id}/media", data={"kind": "voice", "duration": "3.2"},
               files={"file": ("v.webm", b"\x1aE\xdf\xa3fake", "audio/webm")})
    assert r.status_code == 200 and r.json()["kind"] == "voice"
    r = b.post(f"/api/chats/{conv_id}/media", data={"kind": "circle"},
               files={"file": ("c.exe", b"MZ", "application/x-msdownload")})
    assert r.status_code == 415

    assert b.post(f"/api/chats/{conv_id}/messages", json={"kind": "sticker", "text": "love:heart"}).status_code == 200
    chats = b.get("/api/chats").json()
    assert chats[0]["unread"] == 2 and chats[0]["feeds"] == ["dating"]
    b.post(f"/api/chats/{conv_id}/read")
    assert b.get("/api/chats").json()[0]["unread"] == 0

    assert stranger.get(f"/api/chats/{conv_id}").status_code == 404
    assert stranger.post(f"/api/chats/{conv_id}/messages", json={"text": "hi"}).status_code == 404
    assert len(a.get("/api/notifications").json()) == 1


def test_call_signaling_relay():
    a = make_user("a@x.io")
    b = make_user("b@x.io")
    a.post("/api/feed/dating/swipe", json={"user_id": b.user_id, "like": True})
    conv_id = b.post("/api/feed/dating/swipe", json={"user_id": a.user_id, "like": True}).json()["conversation_id"]
    # Один общий event loop для обоих сокетов — как на настоящем сервере
    with TestClient(app) as hub, hub.websocket_connect("/ws", headers=cookie(a)) as wa, \
            hub.websocket_connect("/ws", headers=cookie(b)) as wb:
        wa.send_json({"type": "ping"})
        assert wa.receive_json()["type"] == "pong"
        wa.send_json({"type": "call:offer", "conversation_id": conv_id, "sdp": {"type": "offer", "sdp": "x"}, "video": True, "call_id": "c1"})
        # Обоим приходит запись о звонке в чате, затем собеседнику — сам оффер
        assert wa.receive_json()["message"]["kind"] == "call"
        assert wb.receive_json()["message"]["text"] == "video"
        offer = wb.receive_json()
        assert offer["type"] == "call:offer" and offer["from"]["id"] == a.user_id
        wb.send_json({"type": "call:answer", "conversation_id": conv_id, "sdp": {"type": "answer", "sdp": "y"}, "call_id": "c1"})
        assert wa.receive_json()["type"] == "call:answer"


def test_unmatch_hides_chat():
    a = make_user("a@x.io")
    b = make_user("b@x.io")
    a.post("/api/feed/dating/swipe", json={"user_id": b.user_id, "like": True})
    conv_id = b.post("/api/feed/dating/swipe", json={"user_id": a.user_id, "like": True}).json()["conversation_id"]
    assert a.delete(f"/api/chats/{conv_id}").status_code == 200
    assert b.get("/api/chats").json() == []


def test_admin_panel():
    boss = make_user("boss@example.com", name="Админ")
    a = make_user("a@x.io", name="Аня")
    b = make_user("b@x.io", name="Боря")
    a.post("/api/feed/dating/swipe", json={"user_id": b.user_id, "like": True})
    conv_id = b.post("/api/feed/dating/swipe", json={"user_id": a.user_id, "like": True}).json()["conversation_id"]
    a.post(f"/api/chats/{conv_id}/messages", json={"text": "секрет"})

    assert a.get("/api/admin/users").status_code == 403

    stats = boss.get("/api/admin/stats").json()
    assert stats["users"] == 3 and stats["matches"] == 1

    users = boss.get("/api/admin/users", params={"q": "аня"}).json()
    assert users["total"] == 1
    detail = boss.get(f"/api/admin/users/{a.user_id}").json()
    assert detail["registration_ip"] and detail["created_at"] and detail["registration_lat"] == 55.75
    assert detail["conversations"][0]["id"] == conv_id

    msgs = boss.get(f"/api/admin/conversations/{conv_id}").json()["items"]
    assert msgs[0]["text"] == "секрет"

    assert boss.post(f"/api/admin/users/{b.user_id}/ban", json={"banned": True}).status_code == 200
    assert b.get("/api/auth/me").status_code == 401

    r = boss.post("/api/admin/broadcast", json={"subject": "Обновление", "body": "Добавили кружочки"})
    assert r.json()["recipients"] == 2  # забаненный не получает

    assert boss.delete(f"/api/admin/users/{a.user_id}").status_code == 200
    assert boss.get(f"/api/admin/users/{a.user_id}").status_code == 404
    assert boss.get("/api/admin/conversations").json() == []


def test_delete_own_account():
    a = make_user("a@x.io")
    assert a.delete("/api/profile").status_code == 200
    assert a.get("/api/auth/me").status_code == 401
