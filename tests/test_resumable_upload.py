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


def test_video_is_processed_in_background_and_finish_retry_is_safe(tmp_path):
    import shutil
    import subprocess

    import pytest

    if not shutil.which("ffmpeg"):
        pytest.skip("нет ffmpeg")
    a, b, conv = _pair()
    src = tmp_path / "IMG.MOV"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=320x240:r=60", "-f", "lavfi", "-i",
                    "sine=f=440", "-t", "1", "-c:v", "libx265", "-tag:v", "hvc1", "-c:a", "aac", str(src)], check=True)
    data = src.read_bytes()
    uid = a.post(f"/api/chats/{conv}/uploads", json={"kind": "video", "size": len(data), "filename": "IMG.MOV",
                                                      "content_type": "video/quicktime"}).json()["id"]
    a.put(f"/api/chats/{conv}/uploads/{uid}?offset=0", content=data)
    first = a.post(f"/api/chats/{conv}/uploads/{uid}/finish").json()
    assert first["kind"] == "video" and first["processing"] is True  # ответ сразу, ролик готовится фоном
    # телефон не дождался ответа и спросил снова — то же сообщение, а не «загрузка не найдена»
    again = a.post(f"/api/chats/{conv}/uploads/{uid}/finish")
    assert again.status_code == 200 and again.json()["id"] == first["id"]
    msgs = b.get(f"/api/chats/{conv}").json()
    msgs = msgs.get("messages", msgs) if isinstance(msgs, dict) else msgs
    done = next(m for m in msgs if m["id"] == first["id"])
    assert done["processing"] is False and done["media_url"].endswith(".mp4") and done["poster_url"]
    assert len([m for m in msgs if m["kind"] == "video"]) == 1  # без дубликатов
