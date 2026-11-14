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
    assert guest.post("/api/support/threads", json={"topic": "support", "text": "x"}).status_code == 401
    ad = guest.post("/api/support/threads", json={"topic": "ads"}).json()
    assert ad["messages"][0]["author"] == "bot"
    guest.post(f"/api/support/threads/{ad['id']}/messages", json={"text": "Какие форматы рекламы?"})
    guest.post(f"/api/support/threads/{ad['id']}/messages", json={"text": "Какая аудитория?"})
    msgs = guest.get(f"/api/support/threads/{ad['id']}").json()["messages"]
    assert "тестовый период" in msgs[2]["text"] and "анкет" in msgs[4]["text"]
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



def test_feed_restart_shows_skipped_again_but_not_likes():
    me = make_user("me@x.io", name="Я", gender="female", looking_for="any")
    make_user("a@x.io", name="Аня", gender="female", looking_for="any")
    make_user("b@x.io", name="Боря", gender="male", looking_for="any")
    cards = {c["name"]: c["id"] for c in me.get("/api/feed?limit=30").json()["cards"]}
    me.post("/api/feed/swipe", json={"user_id": cards["Аня"], "like": False})
    me.post("/api/feed/swipe", json={"user_id": cards["Боря"], "like": True})
    res = me.get("/api/feed?limit=30").json()
    assert res["cards"] == [] and res["skipped"] == 1
    assert me.post("/api/feed/restart").json()["restored"] == 1
    assert [c["name"] for c in me.get("/api/feed?limit=30").json()["cards"]] == ["Аня"]  # лайкнутый не возвращается
