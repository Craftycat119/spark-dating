from conftest import jpeg_bytes, make_user


def _pair():
    a = make_user("ua@example.com", name="Аня", gender="female")
    b = make_user("ub@example.com", name="Боря", gender="male")
    b.post("/api/feed/swipe", json={"user_id": a.user_id, "like": True})
    conv = a.post("/api/feed/swipe", json={"user_id": b.user_id, "like": True}).json()["conversation_id"]
    return a, b, conv


def test_resumable_upload_pause_resume_and_finish():
    a, b, conv = _pair()
    data = jpeg_bytes()
    up = a.post(f"/api/chats/{conv}/uploads", json={"kind": "image", "size": len(data), "filename": "p.jpg", "content_type": "image/jpeg"}).json()
    uid, half = up["id"], len(data) // 2
    assert a.put(f"/api/chats/{conv}/uploads/{uid}?offset=0", content=data[:half]).json()["received"] == half
    # «закрыли приложение» — после возвращения спрашиваем, сколько дошло, и продолжаем с этого места
    assert a.get(f"/api/chats/{conv}/uploads/{uid}").json()["received"] == half
    r = a.put(f"/api/chats/{conv}/uploads/{uid}?offset=0", content=data[:half])  # повтор старого куска
    assert r.status_code == 409 and r.json()["detail"]["received"] == half
    assert a.post(f"/api/chats/{conv}/uploads/{uid}/finish").status_code == 409  # ещё не всё
    a.put(f"/api/chats/{conv}/uploads/{uid}?offset={half}", content=data[half:])
    msg = a.post(f"/api/chats/{conv}/uploads/{uid}/finish").json()
    assert msg["kind"] == "image" and msg["media_url"].startswith(f"/media/chat/{conv}/")
    assert b.get(msg["media_url"]).status_code == 200
    assert a.get(f"/api/chats/{conv}/uploads/{uid}").status_code == 404  # временный файл убран


def test_upload_cancel_limits_and_foreign_access():
    a, b, conv = _pair()
    assert a.post(f"/api/chats/{conv}/uploads", json={"kind": "image", "size": 50 * 1024 * 1024}).status_code == 413
    assert a.post(f"/api/chats/{conv}/uploads", json={"kind": "video", "size": 10, "filename": "x.exe"}).status_code == 415
    uid = a.post(f"/api/chats/{conv}/uploads", json={"kind": "video", "size": 10, "filename": "IMG.MOV"}).json()["id"]
    assert b.get(f"/api/chats/{conv}/uploads/{uid}").status_code == 404  # чужую загрузку не видно
    assert b.put(f"/api/chats/{conv}/uploads/{uid}?offset=0", content=b"x").status_code == 404
    assert a.put(f"/api/chats/{conv}/uploads/{uid}?offset=0", content=b"x" * 11).status_code == 413
    assert a.get(f"/api/chats/{conv}/uploads/{'a' * 31}%2F").status_code == 404
    a.delete(f"/api/chats/{conv}/uploads/{uid}")
    assert a.get(f"/api/chats/{conv}/uploads/{uid}").status_code == 404
