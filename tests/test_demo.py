from conftest import make_user, new_client


def demo_client():
    c = new_client()
    r = c.post("/api/auth/demo")
    assert r.status_code == 200, r.text
    assert r.json()["is_demo"] and r.json()["is_complete"]
    return c


def test_demo_feed_has_ten_bots_ranked_by_fit():
    c = demo_client()
    cards = c.get("/api/feed?limit=30").json()["cards"]
    assert len(cards) == 10
    names = [x["name"] for x in cards]
    assert set(names[:3]) == {"Алина", "Максим", "Вероника"}          # идеально подходят
    assert set(names[-3:]) == {"Олег", "Карина", "Игорь"}             # совсем не подходят
    assert cards[0]["match"] >= 80 and cards[-1]["match"] <= 20
    assert all(x["photos_count"] >= 3 for x in cards)
    profile = c.get(f"/api/users/{cards[0]['id']}").json()
    assert len(profile["photos"]) >= 4 and len(profile["bio"]) > 300


def test_demo_match_and_bot_replies():
    c = demo_client()
    cards = {x["name"]: x["id"] for x in c.get("/api/feed?limit=30").json()["cards"]}
    assert c.post("/api/feed/swipe", json={"user_id": cards["Даниил"], "like": True}).json()["match"] is False
    r = c.post("/api/feed/swipe", json={"user_id": cards["Алина"], "like": True}).json()
    assert r["match"] is True
    conv = r["conversation_id"]
    msgs = c.get(f"/api/chats/{conv}").json()["messages"]
    assert len(msgs) == 1 and msgs[0]["sender_id"] == cards["Алина"]   # бот поздоровался первым
    c.post(f"/api/chats/{conv}/messages", json={"text": "Привет!"})
    msgs = c.get(f"/api/chats/{conv}").json()["messages"]
    assert [m["sender_id"] == cards["Алина"] for m in msgs] == [True, False, True]


def test_bots_and_guests_are_invisible_to_real_users():
    guest = demo_client()
    bot_id = guest.get("/api/feed").json()["cards"][0]["id"]
    real = make_user("real@x.io")
    other = make_user("other@x.io")
    names = [x["name"] for x in real.get("/api/feed?limit=30").json()["cards"]]
    assert names == ["Тест"]  # только настоящий пользователь
    assert real.get(f"/api/users/{bot_id}").status_code == 404
    assert real.post("/api/feed/swipe", json={"user_id": bot_id, "like": True}).status_code == 404
    assert all(x["id"] != real.user_id for x in guest.get("/api/feed?limit=30").json()["cards"])
    assert other.user_id
