from app import config, push, telegram_bot
from app.ages import birth_for_age
from app.interests import compatible
from conftest import make_user, new_client, register
from test_push import TOKEN, FakeBot


def test_gender_matching_and_teen_limit():
    assert compatible("female", "male", "male", "female")
    assert not compatible("female", "female", "male", "any")
    c = new_client()
    register(c, "teen@x.io")
    base = {"name": "Миша", "birth_date": birth_for_age(15).isoformat(), "looking_for": "any", "accept_terms": True, "confirm_age": True}
    assert c.put("/api/profile", json={**base, "gender": "trans_male"}).status_code == 422
    me = c.put("/api/profile", json={**base, "gender": "male", "orientation": "bi"}).json()
    assert me["gender"] == "male" and me["orientation"] is None  # подросткам сексуальность не храним


def test_sexuality_depends_on_gender_and_separate_toggles():
    a = make_user("i1@x.io", gender="female", looking_for="any")
    b = make_user("i2@x.io", gender="male", looking_for="any")
    assert b.put("/api/profile", json={"orientation": "lesbian"}).status_code == 422
    assert b.put("/api/profile", json={"orientation": "gay"}).status_code == 200
    card = a.get(f"/api/users/{b.user_id}").json()
    assert card["gender_label"] == "Парень" and card["orientation_label"] == "Гей"
    b.put("/api/profile", json={"show_identity": False})
    card = a.get(f"/api/users/{b.user_id}").json()
    assert card["gender_label"] is None and card["orientation_label"] == "Гей"
    b.put("/api/profile", json={"show_orientation": False})
    assert a.get(f"/api/users/{b.user_id}").json()["orientation_label"] is None
    # смена пола сбрасывает неподходящую сексуальность
    me = b.put("/api/profile", json={"gender": "female"}).json()
    assert me["orientation"] is None
    n = make_user("i3@x.io", gender="nonbinary", looking_for="any")
    assert n.put("/api/profile", json={"orientation": "lesbian"}).status_code == 200
    assert n.put("/api/profile", json={"orientation": "gay"}).status_code == 200


def test_extras_height_weight_zodiac():
    a = make_user("e1@x.io")
    me = a.put("/api/profile", json={"height_cm": 180, "weight_kg": 75, "zodiac": "leo", "extras_done": True}).json()
    assert me["height_cm"] == 180 and me["zodiac"] == "leo" and me["extras_done"]
    assert a.put("/api/profile", json={"height_cm": 20}).status_code in (400, 422)
    assert a.put("/api/profile", json={"zodiac": "dragon"}).status_code in (400, 422)
    b = make_user("e2@x.io")
    card = b.get(f"/api/users/{a.user_id}").json()
    assert card["height_cm"] == 180 and card["zodiac_label"] == "Лев"


def test_blacklist():
    a = make_user("b1@x.io", gender="female", looking_for="any")
    b = make_user("b2@x.io", gender="male", looking_for="any")
    b.post("/api/feed/swipe", json={"user_id": a.user_id, "like": True})
    r = a.post("/api/feed/swipe", json={"user_id": b.user_id, "like": True}).json()
    conv = r.get("conversation_id")
    assert conv
    assert a.post(f"/api/users/{b.user_id}/block").status_code == 200
    assert b.post(f"/api/chats/{conv}/messages", json={"text": "привет"}).status_code == 404
    assert all(c["id"] != conv for c in b.get("/api/chats").json())
    assert b.get(f"/api/users/{a.user_id}").status_code == 404
    assert [x["id"] for x in a.get("/api/blocks").json()] == [b.user_id]
    assert all(x["id"] != a.user_id for x in b.get("/api/feed").json()["cards"])
    a.delete(f"/api/users/{b.user_id}/block")
    assert b.post(f"/api/chats/{conv}/messages", json={"text": "привет"}).status_code == 200


def test_admin_without_profile_and_support_to_telegram(monkeypatch):
    boss = make_user("boss@example.com", name="Админ")  # ADMIN_EMAILS в conftest
    r = boss.post("/api/admin/admins", json={"name": "Оля", "email": "olya@x.io", "password": "Secret123"})
    assert r.status_code == 200 and r.json()["is_admin"]
    olya = new_client()
    me = olya.post("/api/auth/login", json={"email": "olya@x.io", "password": "Secret123"}).json()
    assert me["is_admin"] and me["name"] == "Оля" and me["terms_accepted"]
    # обращение пользователя уходит админам в Telegram
    bot = FakeBot()
    monkeypatch.setattr(config.settings, "telegram_bot_token", TOKEN)
    monkeypatch.setattr(config.settings, "telegram_admin_chat_id", "-100500")
    monkeypatch.setattr(telegram_bot, "api", bot)
    monkeypatch.setattr(push, "_in_background", lambda fn, *a: fn(*a))
    u = make_user("user@x.io", name="Вася")
    u.post("/api/support/threads", json={"category": "complaint", "text": "Мне пишут гадости"})
    sent = [p for m, p in bot.sent if m == "sendMessage"]
    assert sent and sent[0]["chat_id"] == "-100500" and "⚠️ Жалоба" in sent[0]["text"] and "Вася" in sent[0]["text"]


def test_review_fixes():
    # жалоба на анкету из другой возрастной группы не раскрывает имя
    adult = make_user("r1@x.io", name="Взрослый")
    teen = new_client()
    register(teen, "r2@x.io")
    teen.put("/api/profile", json={"name": "Тайное Имя", "birth_date": birth_for_age(15).isoformat(), "accept_terms": True, "confirm_age": True})
    teen_id = teen.get("/api/auth/me").json()["id"]
    t = adult.post("/api/support/threads", json={"category": "complaint", "about_user_id": teen_id}).json()
    assert t["about_user_id"] is None and "Тайное" not in str(t)
    # подростку вес не сохраняется
    me = teen.put("/api/profile", json={"weight_kg": 50}).json()
    assert me["weight_kg"] is None
    # лайк в обход фильтра «кого ищу» не проходит
    m = make_user("r3@x.io", gender="male", looking_for="female")
    w = make_user("r4@x.io", gender="male", looking_for="female")
    assert m.post("/api/feed/swipe", json={"user_id": w.user_id, "like": True}).status_code == 404
    # «Вернуть» не показывает анкету того, кто вас заблокировал
    a = make_user("r5@x.io", gender="female", looking_for="any")
    b = make_user("r6@x.io", gender="male", looking_for="any")
    b.post("/api/feed/swipe", json={"user_id": a.user_id, "like": False})
    a.post(f"/api/users/{b.user_id}/block")
    a.post(f"/api/users/{b.user_id}/block")  # повторное нажатие — без ошибки
    assert b.post("/api/feed/undo", json={"user_id": a.user_id}).status_code == 404
