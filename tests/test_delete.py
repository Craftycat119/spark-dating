from app.ages import birth_for_age
from conftest import jpeg_bytes, make_user


def test_deleted_profile_disappears_everywhere():
    boss = make_user("boss@example.com")
    a, b = make_user("da@x.io", name="Удаляемый"), make_user("db@x.io")
    a.post("/api/feed/swipe", json={"user_id": b.user_id, "like": True})
    conv = b.post("/api/feed/swipe", json={"user_id": a.user_id, "like": True}).json()["conversation_id"]
    a.post(f"/api/chats/{conv}/messages", json={"text": "привет"})
    a.post("/api/profile/photos", files={"file": ("g.jpg", jpeg_bytes(), "image/jpeg")})
    a.post("/api/support/threads", json={"category": "help", "text": "вопрос"})
    assert a.delete("/api/profile").status_code == 200
    names = [u["name"] for u in boss.get("/api/admin/users").json()["items"]]
    assert "Удаляемый" not in names
    assert boss.get(f"/api/admin/users/{a.user_id}").status_code == 404
    assert b.get("/api/chats").json() == []


def test_admin_birth_date_is_validated():
    boss = make_user("boss@example.com")
    u = make_user("bd@x.io")
    future = birth_for_age(-1).isoformat()
    assert boss.post(f"/api/admin/users/{u.user_id}/birth-date", json={"birth_date": future}).status_code == 422
