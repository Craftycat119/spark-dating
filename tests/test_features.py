from unittest import mock

from app.ages import birth_for_age
from conftest import jpeg_bytes, make_user, new_client, register


def test_teens_and_adults_are_isolated():
    adult = make_user("adult@x.io", name="Взрослый", age=25)
    teen1 = make_user("t1@x.io", name="Миша", age=15, goals=("Дружба",))
    teen2 = make_user("t2@x.io", name="Катя", age=16, goals=("Дружба",))
    assert teen1.get("/api/profile").json()["age_group"] == "teen"
    assert [c["name"] for c in teen1.get("/api/feed").json()["cards"]] == ["Катя"]
    assert [c["name"] for c in adult.get("/api/feed").json()["cards"]] == []
    assert adult.get(f"/api/users/{teen1.user_id}").status_code == 404
    assert teen1.get(f"/api/users/{adult.user_id}").status_code == 404
    assert adult.post("/api/feed/swipe", json={"user_id": teen1.user_id, "like": True}).status_code == 404
    # подросткам нельзя «Свидания»
    assert teen1.put("/api/profile", json={"goals": ["Свидания"]}).status_code == 422
    teen1.post("/api/feed/swipe", json={"user_id": teen2.user_id, "like": True})
    assert teen2.post("/api/feed/swipe", json={"user_id": teen1.user_id, "like": True}).json()["match"]


def test_birth_date_rules():
    c = new_client()
    register(c, "kid@x.io")
    assert c.put("/api/profile", json={"birth_date": birth_for_age(11).isoformat()}).status_code == 422
    assert c.put("/api/profile", json={"birth_date": birth_for_age(15).isoformat()}).status_code == 200
    # поменять самому нельзя, чтобы не «повзрослеть» ради взрослой ленты
    r = c.put("/api/profile", json={"birth_date": birth_for_age(19).isoformat()})
    assert r.status_code == 403
    assert c.get("/api/profile").json()["looking_for"] in (None, "any")


def test_undo_skip_and_like():
    me = make_user("me@x.io")
    a = make_user("a@x.io", name="Аня")
    me.post("/api/feed/swipe", json={"user_id": a.user_id, "like": False})
    assert me.get("/api/feed").json()["cards"] == []
    r = me.post("/api/feed/undo", json={"user_id": a.user_id}).json()
    assert r["undone"] == "skip" and r["card"]["name"] == "Аня"
    assert [c["name"] for c in me.get("/api/feed").json()["cards"]] == ["Аня"]
    # лайк, давший пару, отменяется, пока в чате нет ответа
    a.post("/api/feed/swipe", json={"user_id": me.user_id, "like": True})
    conv = me.post("/api/feed/swipe", json={"user_id": a.user_id, "like": True}).json()["conversation_id"]
    assert me.post("/api/feed/undo", json={"user_id": a.user_id}).json()["undone"] == "like"
    assert a.get("/api/chats").json() == []
    # а если собеседник уже написал, отмена запрещена
    me.post("/api/feed/swipe", json={"user_id": a.user_id, "like": True})
    a.post(f"/api/chats/{conv}/messages", json={"text": "Привет"})
    assert me.post("/api/feed/undo", json={"user_id": a.user_id}).status_code == 409


def test_animals_feed_and_help():
    owner = make_user("boss@example.com", name="Волонтёр")  # объявления добавляет только админ
    helper = make_user("helper@x.io")
    teen = make_user("teen@x.io", age=15, goals=("Дружба",))
    r = owner.post("/api/animals", data={"category": "charity", "name": "Барсик", "contact": "@barsik_help",
                                         "description": "Нужна операция", "fundraising_goal": "40 000 ₽"},
                   files=[("files", ("1.jpg", jpeg_bytes(), "image/jpeg"))])
    assert r.status_code == 200, r.text
    post = r.json()
    assert post["contact_url"] == "https://t.me/barsik_help" and post["fundraising_open"] is True
    owner.post("/api/animals", data={"category": "adoption", "name": "Рыжик", "contact": "t.me/+GroupInvite"})
    assert helper.post("/api/animals", data={"category": "foster", "name": "X", "contact": "@x"}).status_code == 403
    assert teen.post("/api/animals", data={"category": "foster", "name": "X", "contact": "@x"}).status_code == 403
    assert owner.post("/api/animals", data={"category": "foster", "name": "X", "contact": "не телеграм!"}).status_code == 422

    items = teen.get("/api/animals").json()["items"]  # смотреть могут все
    assert [i["name"] for i in items] == ["Рыжик", "Барсик"]
    assert [i["name"] for i in helper.get("/api/animals?category=charity").json()["items"]] == ["Барсик"]

    with mock.patch("app.telegram_notify.send_message", return_value=True) as sent:
        r = helper.post(f"/api/animals/{post['id']}/help", json={"message": "Переведу 1000", "contact": "@helper"})
    assert r.status_code == 200 and r.json()["contact_url"] == "https://t.me/barsik_help"
    assert teen.post(f"/api/animals/{post['id']}/help", json={}).status_code == 403
    assert helper.patch(f"/api/animals/{post['id']}", json={"fundraising_open": False}).status_code == 403  # не автор
    assert owner.patch(f"/api/animals/{post['id']}", json={"fundraising_open": False}).json()["fundraising_open"] is False
    assert helper.post(f"/api/animals/{post['id']}/help", json={}).status_code == 409  # сбор закрыт
    _ = sent


def test_support_and_ads_threads():
    boss = make_user("boss@example.com")
    user = make_user("u@x.io")
    t = user.post("/api/support/threads", json={"topic": "support", "category": "complaint"}).json()
    assert [m["author"] for m in t["messages"]] == ["bot"]                 # сначала приветствие
    assert "Расскажите" in t["messages"][0]["text"] and "принято" not in t["messages"][0]["text"]
    user.post(f"/api/support/threads/{t['id']}/messages", json={"text": "Спам в чате"})
    msgs = user.get(f"/api/support/threads/{t['id']}").json()["messages"]
    assert [m["author"] for m in msgs] == ["bot", "user", "bot"] and "принято" in msgs[2]["text"]
    user.post(f"/api/support/threads/{t['id']}/messages", json={"text": "Ещё скриншот"})
    assert len(user.get(f"/api/support/threads/{t['id']}").json()["messages"]) == 4  # «принято» только один раз
    assert user.get("/api/support/threads").json()[0]["category"] == "complaint"
    assert boss.post(f"/api/admin/support/{t['id']}/reply", json={"text": "Разберёмся"}).status_code == 200
    assert user.get(f"/api/support/threads/{t['id']}").json()["messages"][-1]["author"] == "staff"
    assert make_user("other@x.io").get(f"/api/support/threads/{t['id']}").status_code == 404

    # рекламодатель без аккаунта
    guest = new_client()
    assert guest.post("/api/support/threads", json={"topic": "support", "text": "x"}).status_code == 422  # гостю нужен контакт для ответа
    ad = guest.post("/api/support/threads", json={"topic": "ads"}).json()
    assert ad["messages"][0]["author"] == "bot"
    guest.post(f"/api/support/threads/{ad['id']}/messages", json={"text": "Какие форматы рекламы?"})
    guest.post(f"/api/support/threads/{ad['id']}/messages", json={"text": "Какая аудитория?"})
    msgs = guest.get(f"/api/support/threads/{ad['id']}").json()["messages"]
    bot = [m["text"] for m in msgs if m["author"] == "bot"]
    assert "реклама не" not in " ".join(bot).lower() and "плата не" not in " ".join(bot).lower()
    assert sum("принята" in x for x in bot) == 1  # «заявка принята» — один раз, после первого сообщения
    assert any("Форматы" in x for x in bot) and any("свяжется менеджер" in x for x in bot)
    assert not any("анкет с подтверждённым фото" in x for x in bot)  # цифры аудитории бот не раскрывает
    assert len(boss.get("/api/admin/support?topic=ads").json()) == 1


def test_animal_details():
    owner = make_user("boss@example.com", name="Волонтёр")
    other = make_user("o@x.io")
    pid = owner.post("/api/animals", data={"category": "foster", "name": "Луна", "contact": "@luna",
                                           "description": "Длинное описание"}).json()["id"]
    with mock.patch("app.telegram_notify.send_message", return_value=False):
        other.post(f"/api/animals/{pid}/help", json={"message": "Могу взять", "contact": "@other_user"})
    d = other.get(f"/api/animals/{pid}").json()
    assert d["help_count"] == 1 and d["description"] == "Длинное описание" and d["author"]["name"] == "Волонтёр"
    owner.patch(f"/api/animals/{pid}", json={"active": False})
    assert other.get(f"/api/animals/{pid}").status_code == 404   # снятое видит только администрация
    assert owner.get(f"/api/animals/{pid}").status_code == 200
    # заявка из приложения видна в админ-панели, её можно отметить обработанной
    reqs = owner.get("/api/admin/help-requests?status=new").json()
    assert reqs["new"] == 1 and reqs["items"][0]["message"] == "Могу взять" and reqs["items"][0]["post"]["name"] == "Луна"
    rid = reqs["items"][0]["id"]
    assert owner.post(f"/api/admin/help-requests/{rid}/status", json={"status": "done"}).json()["status"] == "done"
    assert owner.get("/api/admin/help-requests?status=new").json()["new"] == 0
    assert other.get("/api/admin/help-requests").status_code == 403
    # обычный пользователь не может ни добавить, ни изменить, ни удалить объявление
    assert other.post("/api/animals", data={"category": "foster", "name": "Кот", "contact": "@cat"}).status_code == 403
    assert other.patch(f"/api/animals/{pid}", json={"active": True}).status_code == 403
    assert other.delete(f"/api/animals/{pid}").status_code == 403
    assert owner.get(f"/api/animals/{pid}").json()["can_manage"] and not other.get("/api/animals").json()["items"][0]["can_manage"] if other.get("/api/animals").json()["items"] else True


def test_teens_choose_who_they_look_for():
    boy = make_user("boy@x.io", name="Миша", age=15, gender="male", looking_for="female", goals=("Дружба",))
    make_user("girl@x.io", name="Катя", age=14, gender="female", looking_for="any", goals=("Дружба",))
    make_user("boy2@x.io", name="Петя", age=14, gender="male", looking_for="any", goals=("Дружба",))
    assert boy.get("/api/profile").json()["looking_for"] == "female"
    assert [c["name"] for c in boy.get("/api/feed").json()["cards"]] == ["Катя"]


def test_seed_pets_once():
    from app.database import SessionLocal
    from app.seed_pets import seed_pets

    with SessionLocal() as db:
        assert seed_pets(db) == 0  # администратора ещё нет — ждём
    boss = make_user("boss@example.com", name="Андрей")
    assert boss.get("/api/admin/stats").status_code == 200  # открыли панель — объявления добавились
    items = boss.get("/api/animals?category=adoption").json()["items"]
    names = [p["name"] for p in items]
    assert names[:8] == ["Мраморный пинчер", "Малыши ищут дом", "Маленький мальчишка", "Красавица",
                         "Ушастая малышка", "Рыжая малышка", "Лиса-Алиса", "Девочка со стройки"]  # в порядке анкет
    lisa = next(p for p in items if p["name"] == "Лиса-Алиса")
    assert len(lisa["photos"]) == 3 and lisa["city"] == "Нячанг"
    boss.delete(f"/api/animals/{lisa['id']}")
    with SessionLocal() as db:
        assert seed_pets(db) == 0  # удалённое не возвращается



def test_feed_second_round_skips_and_likes():
    me = make_user("me@x.io", name="Я", gender="female", looking_for="any")
    make_user("a@x.io", name="Аня", gender="female", looking_for="any")
    make_user("b@x.io", name="Боря", gender="male", looking_for="any")
    cards = {c["name"]: c["id"] for c in me.get("/api/feed?limit=30").json()["cards"]}
    me.post("/api/feed/swipe", json={"user_id": cards["Аня"], "like": False})
    me.post("/api/feed/swipe", json={"user_id": cards["Боря"], "like": True})
    res = me.get("/api/feed?limit=30").json()
    assert res["cards"] == [] and res["skipped"] == 2
    assert me.post("/api/feed/restart").json()["restored"] == 2
    cards = {c["name"]: c for c in me.get("/api/feed?limit=30").json()["cards"]}
    assert set(cards) == {"Аня", "Боря"}  # второй круг: и пропущенные, и лайкнутые
    assert cards["Боря"]["liked_before"] and not cards["Аня"]["liked_before"]



def test_radius_capped_at_7000_km():
    me = make_user("far@x.io", name="Далеко")
    me.put("/api/profile", json={"max_distance_km": 20000})
    assert me.get("/api/profile").json()["max_distance_km"] == 7000
    me.put("/api/profile", json={"max_distance_km": 5})
    assert me.get("/api/profile").json()["max_distance_km"] == 5



def test_like_survives_second_round_and_makes_match():
    me = make_user("m1@x.io", name="Я", gender="female", looking_for="any")
    bob = make_user("m2@x.io", name="Боря", gender="male", looking_for="any")
    me.post("/api/feed/swipe", json={"user_id": bob.user_id, "like": True})
    me.get("/api/feed?limit=30")
    me.post("/api/feed/restart")
    assert [c["name"] for c in me.get("/api/feed?limit=30").json()["cards"]] == ["Боря"]
    # Боря отвечает взаимностью — лайк со второго круга не пропал, будет пара
    assert bob.post("/api/feed/swipe", json={"user_id": me.user_id, "like": True}).json()["match"] is True
    me.post("/api/feed/restart")
    assert me.get("/api/feed?limit=30").json()["cards"] == []  # с парой анкета во второй круг не идёт



def test_city_from_location_and_hide_switch():
    me = make_user("city1@x.io", name="Я", gender="female", looking_for="any", lat=12.2388, lon=109.1967)
    other = make_user("city2@x.io", name="Боря", gender="male", looking_for="any", lat=12.25, lon=109.19)
    assert me.post("/api/profile/location", json={"lat": 12.2388, "lon": 109.1967}).json()["city"] == "Нячанг"
    other.post("/api/profile/location", json={"lat": 10.811, "lon": 106.706})  # район Хошимина
    assert other.get("/api/profile").json()["city_name"] == "Хошимин"
    other.post("/api/profile/location", json={"lat": 12.25, "lon": 109.19})
    me.put("/api/profile", json={"max_distance_km": 100})
    card = next(c for c in me.get("/api/feed?limit=30").json()["cards"] if c["name"] == "Боря")
    assert card["city"] == "Нячанг"
    other.put("/api/profile", json={"show_city": False})
    me.post("/api/feed/restart")
    card = next(c for c in me.get("/api/feed?limit=30").json()["cards"] if c["name"] == "Боря")
    assert card["city"] is None  # скрыл город — не видно



def test_new_user_gets_max_radius():
    me = make_user("radius@x.io", name="Новичок")
    assert me.get("/api/profile").json()["max_distance_km"] == 7000



def _pair_chat():
    a = make_user("pa@x.io", name="Аня", gender="female", looking_for="any")
    b = make_user("pb@x.io", name="Боря", gender="male", looking_for="any")
    b.post("/api/feed/swipe", json={"user_id": a.user_id, "like": True})
    conv = a.post("/api/feed/swipe", json={"user_id": b.user_id, "like": True}).json()["conversation_id"]
    return a, b, conv


def test_reply_edit_pin():
    a, b, conv = _pair_chat()
    first = a.post(f"/api/chats/{conv}/messages", json={"text": "Привет! Как дела?"}).json()
    reply = b.post(f"/api/chats/{conv}/messages", json={"text": "Отлично", "reply_to": first["id"]}).json()
    assert reply["reply_to"]["id"] == first["id"] and reply["reply_to"]["text"].startswith("Привет")
    # изменить можно только своё
    assert b.patch(f"/api/chats/{conv}/messages/{first['id']}", json={"text": "взлом"}).status_code == 403
    edited = a.patch(f"/api/chats/{conv}/messages/{first['id']}", json={"text": "Привет! Как ты?"}).json()
    assert edited["edited"] and edited["text"] == "Привет! Как ты?"
    # закрепить — видно обоим
    assert b.post(f"/api/chats/{conv}/pin", json={"message_id": first["id"]}).json()["pinned"]["id"] == first["id"]
    assert a.get(f"/api/chats/{conv}").json()["pinned"]["text"] == "Привет! Как ты?"
    b.post(f"/api/chats/{conv}/pin", json={"message_id": None})
    assert a.get(f"/api/chats/{conv}").json()["pinned"] is None
    # чужой чат — нельзя
    c = make_user("pc@x.io", name="Чужой")
    assert c.post(f"/api/chats/{conv}/pin", json={"message_id": first["id"]}).status_code in (403, 404)



def test_likes_section_lists():
    me = make_user("lk0@x.io", name="Я", gender="female", looking_for="any")
    mutual = make_user("lk1@x.io", name="Взаимный", gender="male", looking_for="any")
    sent = make_user("lk2@x.io", name="Лайкнула", gender="male", looking_for="any")
    fan = make_user("lk3@x.io", name="Поклонник", gender="male", looking_for="any")
    me.post("/api/feed/swipe", json={"user_id": mutual.user_id, "like": True})
    mutual.post("/api/feed/swipe", json={"user_id": me.user_id, "like": True})
    me.post("/api/feed/swipe", json={"user_id": sent.user_id, "like": True})
    fan.post("/api/feed/swipe", json={"user_id": me.user_id, "like": True})
    d = me.get("/api/feed/likes").json()
    assert [p["name"] for p in d["mutual"]] == ["Взаимный"] and d["mutual"][0]["conversation_id"]
    assert [p["name"] for p in d["sent"]] == ["Лайкнула"]
    assert [p["name"] for p in d["received"]] == ["Поклонник"]
    assert "email" not in d["received"][0]
    # ответила взаимностью — поклонник переходит во «взаимные»
    assert me.post("/api/feed/swipe", json={"user_id": fan.user_id, "like": True}).json()["match"] is True
    d = me.get("/api/feed/likes").json()
    assert {p["name"] for p in d["mutual"]} == {"Взаимный", "Поклонник"} and d["received"] == []
    # написать без взаимности нельзя
    assert sent.get(f"/api/users/{me.user_id}").json()["conversation_id"] is None



def test_like_kept_when_skipped_on_second_round_and_after_photo_change():
    me = make_user("keep0@x.io", name="Я", gender="female", looking_for="any")
    him = make_user("keep1@x.io", name="Он", gender="male", looking_for="any")
    me.post("/api/feed/swipe", json={"user_id": him.user_id, "like": True})
    me.get("/api/feed?limit=30")
    me.post("/api/feed/restart")  # второй круг
    assert me.get("/api/feed?limit=30").json()["cards"][0]["liked_before"]
    me.post("/api/feed/swipe", json={"user_id": him.user_id, "like": False})  # «Дальше» на втором круге
    assert [p["name"] for p in me.get("/api/feed/likes").json()["sent"]] == ["Он"]  # лайк остался
    # он сменил фото — оно ждёт проверки, но из «Вы лайкнули» не пропадает
    from app.database import SessionLocal
    from app.models import User

    with SessionLocal() as db:
        db.get(User, him.user_id).photo_verified = False
        db.commit()
    assert [p["name"] for p in me.get("/api/feed/likes").json()["sent"]] == ["Он"]
    # а взаимность по-прежнему создаёт пару
    with SessionLocal() as db:
        db.get(User, him.user_id).photo_verified = True
        db.commit()
    assert him.post("/api/feed/swipe", json={"user_id": me.user_id, "like": True}).json()["match"] is True



def test_guest_can_write_to_support_with_contact():
    from conftest import new_client

    g = new_client()
    assert g.post("/api/support/threads", json={"topic": "support", "text": "Не приходит код"}).status_code == 422  # нет контакта
    t = g.post("/api/support/threads", json={"topic": "support", "text": "Не приходит код", "contact": "@guest"}).json()
    assert t["id"] and any(m["author"] == "user" for m in t["messages"])
    assert [x["id"] for x in g.get("/api/support/threads").json()] == [t["id"]]  # гость видит своё обращение
    boss = make_user("boss@example.com", name="Андрей")
    threads = boss.get("/api/admin/support").json()
    assert any(x["id"] == t["id"] for x in threads)  # и оно в админке



def test_deleted_accounts_counted_anonymously():
    boss = make_user("boss@example.com", name="Андрей")
    gone = make_user("gone@x.io", name="Ушла")
    assert gone.delete("/api/profile").status_code == 200
    d = boss.get("/api/admin/stats").json()["deletions"]
    assert d["self_total"] == 1 and d["today"] == 1 and d["week"] == 1
    row = d["recent"][0]
    assert row["by"] == "self" and row["age_group"] == "adult" and row["days"] == 0
    assert "Ушла" not in str(d) and "gone@x.io" not in str(d)  # ни имени, ни почты



def test_registration_funnel_in_admin():
    from conftest import new_client, register

    boss = make_user("boss@example.com", name="Андрей")
    make_user("full@x.io", name="Дошёл")  # полностью
    half = new_client()
    register(half, "half@x.io")  # почта подтверждена, дальше не пошёл
    new_client().post("/api/auth/register", json={"email": "nocode@x.io", "password": "Secret123"})  # код не ввёл
    f = boss.get("/api/admin/stats").json()["funnel"]
    steps = {r["step"]: r for r in f["steps"]}
    assert f["total"] == 3 and f["done"] == 1
    assert steps["email"]["stuck"] == 1 and steps["about"]["stuck"] == 1 and steps["done"]["stuck"] == 1
    assert steps["email"]["reached"] == 3 and steps["about"]["reached"] == 2 and steps["done"]["reached"] == 1
    lst = boss.get("/api/admin/users?step=about").json()
    assert lst["total"] == 1 and lst["items"][0]["email"] == "half@x.io" and lst["items"][0]["reg_step_label"].startswith("Имя")


def test_audit_hardening():
    from conftest import new_client

    c = new_client()
    r = c.get("/robots.txt")
    assert r.status_code == 200 and "Disallow: /api/" in r.text
    assert "/pub" not in r.text  # картинки рассылок должны быть доступны Telegram
    assert c.get("/sitemap.xml").status_code == 404 and c.get("/wp-login.php").status_code == 404
    assert c.get("/").status_code == 200 and c.get("/feed").status_code == 200  # страницы приложения как раньше
    h = c.get("/").headers
    assert h["cross-origin-opener-policy"] == "same-origin-allow-popups" and h["cross-origin-resource-policy"] == "same-site"
    r = c.post("/api/auth/register", json={"email": "x@y.io", "password": "Secret123", "junk": "<script>"})
    bad = c.post("/api/auth/login", json={"email": "a@b.co"})
    assert bad.status_code == 422
    d = bad.json()["detail"][0]
    assert set(d) == {"loc", "msg"} and d["msg"] == "Заполните поле" and "input" not in bad.text


def test_cancel_mutual_like_even_with_messages():
    me = make_user("um1@x.io", name="Аня", gender="female", looking_for="male")
    him = make_user("um2@x.io", name="Олег", gender="male", looking_for="female")
    me.post("/api/feed/swipe", json={"user_id": him.user_id, "like": True})
    conv = him.post("/api/feed/swipe", json={"user_id": me.user_id, "like": True}).json()["conversation_id"]
    me.post(f"/api/chats/{conv}/messages", json={"text": "Привет"})
    assert me.post("/api/feed/undo", json={"user_id": him.user_id}).status_code == 409  # «вернуть» — нельзя, переписка
    r = me.post("/api/feed/unlike", json={"user_id": him.user_id})
    assert r.status_code == 200 and r.json()["unmatched"]
    mine = me.get("/api/feed/likes").json()
    assert not mine["mutual"] and not mine["sent"]  # пары и моего лайка нет
    assert [p["id"] for p in mine["received"]] == [him.user_id]  # он меня лайкнул — можно ответить снова
    his = him.get("/api/feed/likes").json()
    assert not his["mutual"] and [p["id"] for p in his["sent"]] == [me.user_id]
    assert him.get(f"/api/chats/{conv}").status_code in (403, 404)  # чат пропал у обоих
    assert me.post("/api/feed/unlike", json={"user_id": him.user_id}).status_code == 404



def test_support_statuses_flow():

    boss = make_user("boss@example.com", name="Андрей")
    u = make_user("sup@x.io", name="Ксения")
    tid = u.post("/api/support/threads", json={"topic": "support", "category": "help", "text": "Не могу подключить геопозицию"}).json()["id"]
    lst = lambda s: [t["id"] for t in boss.get(f"/api/admin/support?status={s}").json()]
    assert tid in lst("active") and tid in lst("open")
    assert boss.post(f"/api/admin/support/{tid}/status", json={"status": "in_work"}).json()["status"] == "in_work"
    assert tid in lst("in_work") and tid in lst("active")
    boss.post(f"/api/admin/support/{tid}/reply", json={"text": "Проверьте разрешение в настройках"})
    assert tid in lst("answered") and tid not in lst("active")  # ответ ушёл — ждём человека
    u.post(f"/api/support/threads/{tid}/messages", json={"text": "Не помогло"})
    assert tid in lst("open")  # написал снова — опять ждёт ответа
    boss.post(f"/api/admin/support/{tid}/status", json={"status": "noreply"})
    assert tid in lst("done") and tid not in lst("active")
    assert boss.post(f"/api/admin/support/{tid}/status", json={"status": "bogus"}).status_code == 404


def test_voice_served_with_audio_type():
    from app.config import settings

    a = make_user("va@x.io", name="А", gender="female", looking_for="male")
    b = make_user("vb@x.io", name="Б", gender="male", looking_for="female")
    a.post("/api/feed/swipe", json={"user_id": b.user_id, "like": True})
    conv = b.post("/api/feed/swipe", json={"user_id": a.user_id, "like": True}).json()["conversation_id"]
    folder = settings.media_dir / "chat" / str(conv)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "v.m4a").write_bytes(b"\x00\x00\x00\x18ftypM4A ")
    r = a.get(f"/media/chat/{conv}/v.m4a")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mp4"



def test_support_screenshots():
    from conftest import jpeg_bytes, new_client

    boss = make_user("boss@example.com", name="Андрей")
    u = make_user("shot@x.io", name="Ксения")
    other = make_user("shot2@x.io", name="Чужой")
    tid = u.post("/api/support/threads", json={"topic": "support", "category": "complaint"}).json()["id"]
    m = u.post(f"/api/support/threads/{tid}/images", files={"file": ("s.png", jpeg_bytes(), "image/png")}).json()
    assert m["image_url"].startswith(f"/api/support/threads/{tid}/images/") and m["author"] == "user"
    assert u.get(m["image_url"]).headers["content-type"] == "image/jpeg"
    assert boss.get(m["image_url"]).status_code == 200  # администрация видит
    assert other.get(m["image_url"]).status_code == 404  # чужой — нет
    assert new_client().get(m["image_url"]).status_code == 404
    assert u.post(f"/api/support/threads/{tid}/images", files={"file": ("x.txt", b"hello", "text/plain")}).status_code == 400
    msgs = boss.get(f"/api/admin/support/{tid}").json()["messages"]
    assert any(x["image_url"] for x in msgs)
    assert u.get(f"/api/support/threads/{tid}/images/..%2F..%2Fspark.db").status_code == 404



def test_admin_users_split_adults_and_teens():
    boss = make_user("boss@example.com", name="Андрей")
    make_user("ad1@x.io", name="Взрослый", age=25)
    make_user("tn1@x.io", name="Подросток", age=15, goals=("Дружба",))
    r = boss.get("/api/admin/users?age=teen").json()
    assert [u["name"] for u in r["items"]] == ["Подросток"] and r["ages"]["teen"] == 1
    adults = [u["name"] for u in boss.get("/api/admin/users?age=adult").json()["items"]]
    assert "Взрослый" in adults and "Подросток" not in adults
    everyone = boss.get("/api/admin/users").json()
    assert everyone["total"] >= 3  # без фильтра — все люди, включая админа без анкеты



def test_everyone_compatible_sees_each_other():
    # 4 взрослых рядом (Нячанг): каждый видит всех, кто подходит по полу и кого ищет; подростки — только подростков
    people = {
        "m_f": make_user("v1@x.io", name="Парень", gender="male", looking_for="female", lat=12.24, lon=109.19),
        "f_m": make_user("v2@x.io", name="Девушка", gender="female", looking_for="male", lat=12.25, lon=109.18),
        "f_any": make_user("v3@x.io", name="Девушка2", gender="female", looking_for="any", lat=12.20, lon=109.20),
        "m_any": make_user("v4@x.io", name="Парень2", gender="male", looking_for="any", lat=16.05, lon=108.20),  # Дананг, ~450 км
        "teen": make_user("v5@x.io", name="Подросток", gender="female", looking_for="any", age=15, goals=("Дружба",), lat=12.24, lon=109.19),
        "teen2": make_user("v6@x.io", name="Подросток2", gender="male", looking_for="any", age=16, goals=("Дружба",), lat=12.24, lon=109.19),
    }
    seen = {k: {c["name"] for c in c_.get("/api/feed?limit=30").json()["cards"]} for k, c_ in people.items()}
    assert seen["m_f"] == {"Девушка", "Девушка2"}
    assert seen["f_m"] == {"Парень", "Парень2"}
    assert seen["f_any"] == {"Парень", "Парень2"}  # девушка ищет всех, но «Девушка» ищет только парней
    assert seen["m_any"] == {"Девушка", "Девушка2"}  # «Парень» ищет только девушек
    assert seen["teen"] == {"Подросток2"} and seen["teen2"] == {"Подросток"}
    boss = make_user("boss@example.com", name="Андрей")
    feed = boss.get("/api/admin/stats").json()["feed"]
    assert feed["visible"]["adult"] >= 4 and feed["visible"]["teen"] == 2



def test_age_range_filters_dating_feed():
    me = make_user("ar0@x.io", name="Я", gender="male", looking_for="female", age=30)
    for i, age in enumerate((19, 25, 35, 50, 70)):
        make_user(f"ar{i + 1}@x.io", name=f"Ей{age}", gender="female", looking_for="male", age=age)
    names = lambda: {c["name"] for c in me.get("/api/feed?limit=30").json()["cards"]}
    assert names() == {"Ей19", "Ей25", "Ей35", "Ей50", "Ей70"}  # по умолчанию 18–65+: все
    assert me.put("/api/profile", json={"age_min": 24, "age_max": 40}).json()["age_min"] == 24
    assert names() == {"Ей25", "Ей35"}
    me.put("/api/profile", json={"age_min": 45, "age_max": 65})  # 65 = «65 и старше»
    assert names() == {"Ей50", "Ей70"}
    assert me.put("/api/profile", json={"age_min": 40, "age_max": 30}).status_code == 422
    r = me.put("/api/profile", json={"age_min": 5, "age_max": 99}).json()
    assert (r["age_min"], r["age_max"]) == (18, 65)  # за пределами — к границам


def test_teen_feed_ignores_age_range():
    t1 = make_user("tr1@x.io", name="Подр1", age=15, goals=("Дружба",), looking_for="any")
    make_user("tr2@x.io", name="Подр2", age=16, goals=("Дружба",), looking_for="any")
    assert {c["name"] for c in t1.get("/api/feed").json()["cards"]} == {"Подр2"}


def test_gallery_accepts_gif_and_short_video(tmp_path):
    import shutil
    import subprocess

    import pytest
    from PIL import Image

    if not shutil.which("ffmpeg"):
        pytest.skip("нет ffmpeg")
    u = make_user("gal@x.io", name="Галерея")
    frames = [Image.new("RGB", (120, 90), c) for c in ((200, 0, 0), (0, 200, 0), (0, 0, 200))]
    gif = tmp_path / "a.gif"
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=200, loop=0)
    r = u.post("/api/profile/photos", files={"file": ("a.gif", gif.read_bytes(), "image/gif")})
    assert r.status_code == 200 and r.json()["photos"][-1]["url"].endswith(".mp4")
    vid = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25", "-t", "20",
                    "-pix_fmt", "yuv420p", str(vid)], check=True)
    r = u.post("/api/profile/photos", files={"file": ("v.mp4", vid.read_bytes(), "video/mp4")})
    assert r.status_code == 200
    from app.config import settings

    url = r.json()["photos"][-1]["url"]
    path = settings.media_dir / url.split("/media/", 1)[1]
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                               capture_output=True, text=True).stdout)
    assert dur <= 15.5  # обрезано до 15 секунд
    bad = u.post("/api/profile/photos", files={"file": ("x.mp4", b"not a video", "video/mp4")})
    assert bad.status_code == 415



def test_videos_become_compatible_everywhere(tmp_path):
    import shutil
    import subprocess

    import pytest

    from app import storage
    from app.config import settings

    if not shutil.which("ffmpeg"):
        pytest.skip("нет ffmpeg")
    enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    folder = settings.media_dir / "chat" / "9"
    folder.mkdir(parents=True, exist_ok=True)

    def make(name, *args):
        p = folder / name
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=60", "-f", "lavfi",
                        "-i", "sine=frequency=440", "-t", "2", *args, str(p)], check=True)
        return f"chat/9/{name}"

    def info(rel):
        i = storage._probe(settings.media_dir / rel)
        v = storage._stream(i, "video")
        return v["codec_name"], v["pix_fmt"], round(storage._fps(i)), storage._stream(i, "audio").get("codec_name")

    # 60 кадров/с → 30, H.264 yuv420p, AAC
    rel = storage.to_playable(make("a.mp4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"), "video")
    assert info(rel) == ("h264", "yuv420p", 30, "aac")
    # HEVC 10 бит (как HDR с iPhone) → H.264 8 бит
    if "libx265" in enc:
        rel = storage.to_playable(make("b.mov", "-c:v", "libx265", "-pix_fmt", "yuv420p10le", "-c:a", "aac", "-tag:v", "hvc1"), "video")
        assert rel.endswith(".mp4") and info(rel)[:2] == ("h264", "yuv420p")
    # нормальное лёгкое видео не трогаем (только индекс в начало)
    ok = make("c.mp4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:v", "500k")
    before = (settings.media_dir / ok).stat().st_size
    assert storage.to_playable(ok, "video") == ok and abs((settings.media_dir / ok).stat().st_size - before) < before * 0.05
    # GIF с нечётной шириной не ломает перекодирование
    from PIL import Image

    frames = [Image.new("RGB", (121, 77), c) for c in ((200, 0, 0), (0, 200, 0))]
    gif = tmp_path / "odd.gif"
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=200, loop=0)
    u = make_user("oddgif@x.io", name="Гиф")
    r = u.post("/api/profile/photos", files={"file": ("odd.gif", gif.read_bytes(), "image/gif")})
    assert r.status_code == 200, r.text



def test_gallery_clip_limits_and_poster(tmp_path):
    import shutil
    import subprocess

    import pytest

    from app.config import settings

    if not shutil.which("ffmpeg"):
        pytest.skip("нет ффмпег")
    u = make_user("clip2@x.io", name="Клип")

    def video(name, seconds):
        p = tmp_path / name
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10", "-t", str(seconds),
                        "-pix_fmt", "yuv420p", str(p)], check=True)
        return p.read_bytes()

    r = u.post("/api/profile/photos", files={"file": ("long.mp4", video("long.mp4", 70), "video/mp4")})
    assert r.status_code == 422 and "60 секунд" in r.json()["detail"]
    r = u.post("/api/profile/photos", files={"file": ("ok.mp4", video("ok.mp4", 30), "video/mp4")})
    assert r.status_code == 200
    url = r.json()["photos"][-1]["url"]
    clip = settings.media_dir / url.split("/media/", 1)[1]
    assert clip.with_name(clip.stem + ".poster.jpg").exists()  # превью для профиля
    assert u.get(url.replace(".mp4", ".poster.jpg")).status_code == 200
    bad = u.post("/api/profile/photos", files={"file": ("x.mp4", b"\x00" * 2000, "video/mp4")})
    assert bad.status_code == 415



def test_gallery_resumable_upload_survives_a_drop():
    from conftest import jpeg_bytes

    u = make_user("resume@x.io", name="Пауза")
    data = jpeg_bytes()
    uid = u.post("/api/profile/uploads", json={"size": len(data), "filename": "a.jpg", "content_type": "image/jpeg"}).json()["id"]
    half = len(data) // 2
    assert u.put(f"/api/profile/uploads/{uid}?offset=0", content=data[:half]).json()["received"] == half
    # «обрыв связи»: клиент спрашивает, сколько дошло, и продолжает с того же места
    assert u.get(f"/api/profile/uploads/{uid}").json()["received"] == half
    r = u.put(f"/api/profile/uploads/{uid}?offset=0", content=data[:half])  # повтор старого куска
    assert r.status_code == 409 and r.json()["detail"]["received"] == half
    u.put(f"/api/profile/uploads/{uid}?offset={half}", content=data[half:])
    me = u.post(f"/api/profile/uploads/{uid}/finish").json()
    assert len(me["photos"]) == 1
    other = make_user("resume2@x.io", name="Чужой")
    assert other.get(f"/api/profile/uploads/{uid}").status_code == 404  # чужую загрузку не видно



def test_teens_cannot_pick_adult_only_interests():
    from app.interests import ADULT_ONLY_INTERESTS

    teen = make_user("teenint@x.io", name="Подросток", age=15, goals=("Дружба",))
    r = teen.put("/api/profile", json={"interests": ["Вино и дегустации", "Бар с друзьями", "Футбол", "Кофе", "Шахматы"]})
    assert r.status_code == 200 and not ADULT_ONLY_INTERESTS & set(r.json()["interests"])
    assert teen.put("/api/profile", json={"interests": ["Вино и дегустации", "Бар с друзьями", "Футбол"]}).status_code == 422  # остался 1
    adult = make_user("adultint@x.io", name="Взрослый")
    assert "Вино и дегустации" in adult.put("/api/profile", json={"interests": ["Вино и дегустации", "Кофе", "Бег"]}).json()["interests"]
    assert "Вино и дегустации" in teen.get("/api/config").json()["adult_only_interests"]



def test_teens_have_no_language_exchange_goal():
    teen = make_user("teenlang@x.io", name="Подросток", age=15, goals=("Дружба",))
    assert "Языковой обмен" not in teen.get("/api/config").json()["teen_goals"]
    assert teen.put("/api/profile", json={"goals": ["Языковой обмен"]}).status_code == 422
    adult = make_user("adultlang@x.io", name="Взрослый")
    assert "Языковой обмен" in adult.put("/api/profile", json={"goals": ["Языковой обмен"]}).json()["goals"]



def test_ads_audience_question_goes_to_manager():
    from app.routers.support import ADS_MANAGER_WILL_ANSWER, ads_answer

    assert ads_answer("Сколько пользователей у вас?", None) == ADS_MANAGER_WILL_ANSWER
    assert ads_answer("Какая аудитория?", None) == ADS_MANAGER_WILL_ANSWER
    assert "Стоимость" in ads_answer("Сколько стоит?", None)
