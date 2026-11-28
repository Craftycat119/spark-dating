
from conftest import make_user

from app import telegram_bot
from app.config import settings


def _private(text, chat_id=555, username="vasya", **extra):
    return {"message": {"message_id": 1, "chat": {"id": chat_id, "type": "private"},
                        "from": {"id": chat_id, "username": username, "is_bot": False}, "text": text, **extra}}


def test_message_to_bot_becomes_support_thread_and_staff_reply_goes_back(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    sent = []
    monkeypatch.setattr("app.push._in_background", lambda fn, *a: sent.append(a))

    calls = telegram_bot.handle_update(_private("Не приходит код на почту"))
    assert calls and "Обращение №" in calls[0][1]["text"]
    # второе сообщение — в то же обращение, без повторного «принято»
    assert telegram_bot.handle_update(_private("Почта ivan@mail.ru")) == []

    boss = make_user("boss@example.com", name="Андрей")
    threads = boss.get("/api/admin/support").json()
    t = next(x for x in threads if "vasya" in (x.get("contact") or ""))
    msgs = boss.get(f"/api/admin/support/{t['id']}").json()["messages"]
    assert [m["text"] for m in msgs if m["author"] == "user"] == ["Не приходит код на почту", "Почта ivan@mail.ru"]

    # ответ из админки — человеку в Telegram
    boss.post(f"/api/admin/support/{t['id']}/reply", json={"text": "Проверьте папку «Спам»"})
    assert any(len(a) > 1 and a[0] == 555 and isinstance(a[1], str) and "Проверьте папку" in a[1] for a in sent)


def test_commands_still_show_help(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    calls = telegram_bot.handle_update(_private("/start"))
    assert "поддержку" in calls[0][1]["text"]


def test_reply_in_support_group_goes_to_user(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    monkeypatch.setattr(settings, "telegram_support_chat_id", "-1001")
    sent = []
    monkeypatch.setattr("app.push._in_background", lambda fn, *a: sent.append(a))
    telegram_bot.handle_update(_private("Помогите", chat_id=777, username="petya"))
    boss = make_user("boss@example.com", name="Андрей")
    tid = next(x for x in boss.get("/api/admin/support").json() if "petya" in (x.get("contact") or ""))["id"]

    group_reply = {"message": {"message_id": 9, "chat": {"id": -1001, "type": "supergroup"}, "from": {"id": 1, "is_bot": False},
                               "text": "Уже смотрим!",
                               "reply_to_message": {"from": {"is_bot": True}, "text": f"🆘 Нужна помощь #{tid} от гостя"}}}
    calls = telegram_bot.handle_update(group_reply)
    assert "Ответ отправлен" in calls[0][1]["text"]
    assert any(len(a) > 1 and a[0] == 777 and isinstance(a[1], str) and "Уже смотрим" in a[1] for a in sent)
    # из чужой группы — нельзя
    sent.clear()
    group_reply["message"]["chat"]["id"] = -999
    assert telegram_bot.handle_update(group_reply) == []
    assert not sent



def test_service_broadcast_reaches_everyone_who_wrote_the_bot(monkeypatch):
    from app.database import SessionLocal
    from app.models import TelegramContact, User

    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    got = []
    monkeypatch.setattr("app.broadcasts.send", lambda bid, chats: got.append(sorted(chats)))
    boss = make_user("boss@example.com", name="Андрей")
    u = make_user("bc1@x.io", name="Без уведомлений")
    with SessionLocal() as db:
        x = db.get(User, u.user_id)
        x.telegram_id, x.tg_notifications = 4242, False
        db.add(TelegramContact(username="guest1", chat_id=5151))  # писал боту без аккаунта
        db.add(TelegramContact(username="somegroup", chat_id=-100777))  # группа — не трогаем
        db.commit()
    assert boss.post("/api/admin/broadcast", data={"subject": "Новость", "body": "x"}).json()["recipients"] == 0
    r = boss.post("/api/admin/broadcast", data={"subject": "Технические работы", "body": "y", "everyone": "true"}).json()
    assert r["recipients"] == 2 and got[-1] == [4242, 5151]


class _Bot:
    def __init__(self):
        self.calls = []

    def __call__(self, method, payload=None, timeout=15):
        self.calls.append((method, payload))
        return {"ok": True, "result": {"message_id": 100 + len(self.calls)}}


def test_broadcast_one_message_with_image_then_edit_and_delete(monkeypatch):
    from conftest import jpeg_bytes

    from app import broadcasts, telegram_bot
    from app.database import SessionLocal
    from app.models import User

    bot = _Bot()
    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    monkeypatch.setattr(settings, "base_url", "https://cofi.example")
    monkeypatch.setattr(telegram_bot, "api", bot)
    monkeypatch.setattr(broadcasts, "PAUSE", 0)
    boss = make_user("boss@example.com", name="Андрей")
    for i, tid in enumerate((9001, 9002)):
        u = make_user(f"r{i}@x.io", name=f"Получатель{i}")
        with SessionLocal() as db:
            db.get(User, u.user_id).telegram_id = tid
            db.commit()
    r = boss.post("/api/admin/broadcast", data={"subject": "Безопасность", "body": "Длинный текст " * 200},
                  files={"image": ("pic.png", jpeg_bytes(), "image/png")}).json()
    assert r["recipients"] == 2
    sends = [p for m, p in bot.calls if m == "sendMessage"]
    assert len(sends) == 2 and not [m for m, _ in bot.calls if m in ("sendPhoto",)]  # одно сообщение, без отдельного фото
    p = sends[0]
    assert p["text"].count("Безопасность") == 1  # заголовок не дублируется
    assert p["link_preview_options"]["show_above_text"] and p["link_preview_options"]["url"].startswith("https://cofi.example/pub/broadcast/")
    # картинка доступна Telegram без входа
    name = p["link_preview_options"]["url"].rsplit("/", 1)[1].split("?")[0]
    from conftest import new_client
    assert new_client().get(f"/pub/broadcast/{name}").headers["content-type"] == "image/jpeg"
    head = new_client().head(f"/pub/broadcast/{name}")  # Telegram проверяет картинку запросом HEAD
    assert head.status_code == 200 and head.headers["content-type"] == "image/jpeg"
    assert new_client().get("/pub/broadcast/spark.db").status_code == 404  # только имена картинок рассылок
    assert b"SQLite" not in new_client().get("/pub/broadcast/../../spark.db").content  # базу так не скачать

    lst = boss.get("/api/admin/broadcasts").json()
    assert lst[0]["sent"] == 2 and lst[0]["can_delete"]
    bid = lst[0]["id"]
    bot.calls.clear()
    boss.patch(f"/api/admin/broadcasts/{bid}", json={"subject": "Безопасность", "body": "Исправленный текст"})
    edits = [p for m, p in bot.calls if m == "editMessageText"]
    assert len(edits) == 2 and {e["message_id"] for e in edits} == {sends[0] and 101, 102} and "Исправленный" in edits[0]["text"]
    bot.calls.clear()
    boss.delete(f"/api/admin/broadcasts/{bid}")
    assert sorted((p["chat_id"], p["message_id"]) for m, p in bot.calls if m == "deleteMessage") == [(9001, 101), (9002, 102)]
    assert boss.get("/api/admin/broadcasts").json()[0]["status"] == "deleted"


def test_pinned_post_for_newcomers_without_changing_greeting(monkeypatch):
    from app import broadcasts, telegram_bot
    from app.database import SessionLocal
    from app.models import User

    bot = _Bot()
    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    monkeypatch.setattr(settings, "base_url", "https://cofi.example")
    monkeypatch.setattr(telegram_bot, "api", bot)
    monkeypatch.setattr(broadcasts, "PAUSE", 0)
    runs = []
    monkeypatch.setattr("app.push._in_background", lambda fn, *a: runs.append((fn, a)))
    boss = make_user("boss@example.com", name="Андрей")
    u = make_user("old@x.io", name="Старожил")
    with SessionLocal() as db:
        db.get(User, u.user_id).telegram_id = 7001
        db.commit()
    boss.post("/api/admin/broadcast", data={"subject": "Безопасность в COFI", "body": "Текст", "newcomers": "true"})
    assert ("pinChatMessage", {"chat_id": 7001, "message_id": 101, "disable_notification": True}) in bot.calls  # закреплён у получателей
    assert boss.get("/api/admin/broadcasts").json()[0]["newcomers"]

    # новичок пишет боту: приветствие — как раньше, а пост приходит отдельно и закрепляется
    bot.calls.clear()
    calls = telegram_bot.handle_update({"message": {"message_id": 1, "chat": {"id": 8888, "type": "private"},
                                                    "from": {"id": 8888, "username": "newbie"}, "text": "/start"}})
    assert "Войти через Telegram" in calls[0][1]["text"]  # приветствие не изменилось
    fn, args = runs[-1]
    fn(*args[:1], 0)  # то, что ушло в фон (без паузы)
    assert [m for m, _ in bot.calls] == ["sendMessage", "pinChatMessage"]
    assert "Безопасность в COFI" in bot.calls[0][1]["text"]
    # второй раз тому же человеку — не присылаем
    bot.calls.clear()
    broadcasts.deliver_to_newcomer(8888, 0)
    assert bot.calls == []
    # человек очистил чат с ботом и нажал «Запустить» (/start): у бота пост «закреплён», но у человека его нет —
    # присылаем и закрепляем снова, старую копию открепляем
    broadcasts._last_repin.clear()
    broadcasts.deliver_to_newcomer(8888, 0, True)
    assert [m for m, _ in bot.calls] == ["sendMessage", "unpinChatMessage", "pinChatMessage"]
    # ещё раз /start сразу же — не спамим
    bot.calls.clear()
    broadcasts.deliver_to_newcomer(8888, 0, True)
    assert bot.calls == []
    # вход через сайт (/start login_…) пост повторно не присылает
    broadcasts._last_repin.clear()
    broadcasts.deliver_to_newcomer(8888, 0, False)
    assert bot.calls == []
    # выключили «новым» — новичкам больше не приходит
    bid = boss.get("/api/admin/broadcasts").json()[0]["id"]
    boss.post(f"/api/admin/broadcasts/{bid}/newcomers", json={"on": False})
    broadcasts.deliver_to_newcomer(9999, 0)
    assert bot.calls == []


def test_newcomers_only_post_is_not_sent_now(monkeypatch):
    from app import broadcasts, telegram_bot
    from app.database import SessionLocal
    from app.models import User

    bot = _Bot()
    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    monkeypatch.setattr(telegram_bot, "api", bot)
    monkeypatch.setattr(broadcasts, "PAUSE", 0)
    boss = make_user("boss@example.com", name="Андрей")
    u = make_user("old2@x.io", name="Старожил")
    with SessionLocal() as db:
        db.get(User, u.user_id).telegram_id = 7002
        db.commit()
    r = boss.post("/api/admin/broadcast", data={"subject": "Безопасность", "body": "Текст", "newcomers": "true", "only_new": "true"}).json()
    assert r["recipients"] == 0 and bot.calls == []  # сейчас никому
    b = boss.get("/api/admin/broadcasts").json()[0]
    assert b["newcomers"] and b["status"] == "sent"
    broadcasts.deliver_to_newcomer(4321, 0)
    assert [m for m, _ in bot.calls] == ["sendMessage", "pinChatMessage"]


def test_broadcast_retry_reasons_resend_and_image_edit(monkeypatch):
    import io
    import urllib.error

    from conftest import jpeg_bytes

    from app import broadcasts, telegram_bot
    from app.database import SessionLocal
    from app.models import User

    state = {"n": 1, "throttled": False}
    calls = []

    def fake(method, payload=None, timeout=15):
        calls.append((method, payload))
        chat = (payload or {}).get("chat_id")
        if method == "sendMessage" and chat == 6002 and not state["throttled"]:
            state["throttled"] = True  # первый раз — «слишком быстро», потом проходит
            raise urllib.error.HTTPError("u", 429, "x", {}, io.BytesIO(b'{"ok":false,"error_code":429,"description":"Too Many Requests: retry after 0","parameters":{"retry_after":0}}'))
        if method == "sendMessage" and chat == 6003:
            raise urllib.error.HTTPError("u", 403, "x", {}, io.BytesIO(b'{"ok":false,"description":"Forbidden: bot was blocked by the user"}'))
        if method == "sendMessage" and chat == 6004 and state["n"] == 0:
            raise urllib.error.HTTPError("u", 400, "x", {}, io.BytesIO(b'{"ok":false,"description":"Bad Request: chat not found"}'))
        state.setdefault("mid", 500)
        state["mid"] += 1
        return {"ok": True, "result": {"message_id": state["mid"]}}

    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    monkeypatch.setattr(settings, "base_url", "https://cofi.example")
    monkeypatch.setattr(telegram_bot, "api", fake)
    monkeypatch.setattr(broadcasts, "PAUSE", 0)
    boss = make_user("boss@example.com", name="Андрей")
    for i, tid in enumerate((6001, 6002, 6003, 6004)):
        u = make_user(f"q{i}@x.io", name=f"Получатель{i}")
        with SessionLocal() as db:
            db.get(User, u.user_id).telegram_id = tid
            db.commit()
    boss.post("/api/admin/broadcast", data={"subject": "Новость", "body": "Текст"})
    b = boss.get("/api/admin/broadcasts").json()[0]
    assert b["sent"] == 3 and b["failed"] == 1  # 429 повторили и доставили
    assert b["reasons"] == {"Заблокировали бота": 1} and b["missing"] == 0  # заблокировавшим не досылаем

    # «Не начинали чат» — потом человек нажал «Старт», досылаем только ему
    state["n"] = 0
    boss.post("/api/admin/broadcast", data={"subject": "Вторая", "body": "Текст"})
    b2 = boss.get("/api/admin/broadcasts").json()[0]
    assert b2["reasons"]["Не начинали чат с ботом"] == 1 and b2["missing"] == 1
    state["n"] = 1
    calls.clear()
    assert boss.post(f"/api/admin/broadcasts/{b2['id']}/resend").json()["recipients"] == 1
    assert [p["chat_id"] for m, p in calls if m == "sendMessage"] == [6004]
    b2 = boss.get("/api/admin/broadcasts").json()[0]
    assert b2["sent"] == 4 - 1 and b2["missing"] == 0

    # добавить картинку к уже отправленной рассылке — у всех, через правку сообщения
    calls.clear()
    r = boss.post(f"/api/admin/broadcasts/{b2['id']}/edit", data={"subject": "Вторая", "body": "Новый текст"},
                  files={"image": ("p.jpg", jpeg_bytes(), "image/jpeg")})
    assert r.status_code == 200 and r.json()["image_url"]
    edits = [p for m, p in calls if m == "editMessageText"]
    assert len(edits) == 3 and all(e["link_preview_options"]["url"].startswith("https://cofi.example/pub/broadcast/") for e in edits)
    # убрать картинку
    calls.clear()
    boss.post(f"/api/admin/broadcasts/{b2['id']}/edit", data={"subject": "Вторая", "body": "Новый текст", "remove_image": "true"})
    assert all(p["link_preview_options"] == {"is_disabled": True} for m, p in calls if m == "editMessageText")
    assert boss.get("/api/admin/broadcasts").json()[0]["image_url"] is None



def test_broadcast_image_through_relay(monkeypatch):
    from app import broadcasts
    from app.models import Broadcast

    monkeypatch.setattr(settings, "base_url", "https://cofi.example")
    b = Broadcast(subject="s", body="b", image_name="a" * 32 + ".jpg")
    assert broadcasts.image_url(b).startswith("https://cofi.example/pub/broadcast/")
    monkeypatch.setattr(settings, "public_image_url", "https://tg.cofi.example")
    assert broadcasts.image_url(b).startswith("https://tg.cofi.example/pub/broadcast/")


def test_broadcast_formatting_html():
    from app import broadcasts

    t = broadcasts.compose("Новое <в> COFI", "Привет! **Важно**: *отмена лайка*\n> Цитата раз\n> два\nКонец 2*3 и user_name_x")
    assert t.startswith("📣 <b>Новое &lt;в&gt; COFI</b>")
    assert "<b>Важно</b>" in t and "<i>отмена лайка</i>" in t
    assert "<blockquote>Цитата раз\ntwo".replace("two", "два") + "</blockquote>" in t
    assert "2*3" in t and "user_name_x" in t  # одиночные символы не ломают текст



def test_broadcast_audience_counts():
    from app.database import SessionLocal
    from app.models import TelegramContact, User

    boss = make_user("boss@example.com", name="Андрей")
    for i, (tid, on) in enumerate(((7101, True), (7102, False))):
        u = make_user(f"aud{i}@x.io", name=f"Ч{i}")
        with SessionLocal() as db:
            x = db.get(User, u.user_id)
            x.telegram_id, x.tg_notifications = tid, on
            db.commit()
    with SessionLocal() as db:
        db.add(TelegramContact(username="g", chat_id=7103))
        db.commit()
    assert boss.get("/api/admin/broadcast/audience").json() == {"subscribed": 1, "everyone": 3, "muted": 1, "ads": 3}



def test_broadcast_silent_for_muted_unless_loud(monkeypatch):
    from app import broadcasts, telegram_bot
    from app.database import SessionLocal
    from app.models import User

    bot = _Bot()
    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    monkeypatch.setattr(telegram_bot, "api", bot)
    monkeypatch.setattr(broadcasts, "PAUSE", 0)
    boss = make_user("boss@example.com", name="Андрей")
    for i, (tid, on) in enumerate(((7201, True), (7202, False))):
        u = make_user(f"mute{i}@x.io", name=f"М{i}")
        with SessionLocal() as db:
            x = db.get(User, u.user_id)
            x.telegram_id, x.tg_notifications = tid, on
            db.commit()
    assert boss.get("/api/admin/broadcast/audience").json()["muted"] == 1
    boss.post("/api/admin/broadcast", data={"subject": "Новость", "body": "т", "everyone": "true"})
    sends = {p["chat_id"]: p for m, p in bot.calls if m == "sendMessage"}
    assert set(sends) == {7201, 7202}
    assert not sends[7201].get("disable_notification") and sends[7202]["disable_notification"] is True
    bot.calls.clear()
    boss.post("/api/admin/broadcast", data={"subject": "Техработы", "body": "т", "everyone": "true", "loud": "true"})
    sends = {p["chat_id"]: p for m, p in bot.calls if m == "sendMessage"}
    assert not any(p.get("disable_notification") for p in sends.values())  # со звуком у всех
    assert boss.get("/api/admin/broadcasts").json()[0]["loud"]



def test_screenshot_sent_to_bot_goes_to_support_thread(monkeypatch):
    from conftest import jpeg_bytes

    from app import telegram_support

    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    monkeypatch.setattr("app.push._in_background", lambda fn, *a: None)
    monkeypatch.setattr(telegram_support, "_download", lambda fid: jpeg_bytes() if fid == "big" else None)
    upd = _private("", chat_id=909, username="shotter")
    upd["message"].pop("text")
    upd["message"]["photo"] = [{"file_id": "small", "width": 90, "height": 90}, {"file_id": "big", "width": 1280, "height": 1280}]
    upd["message"]["caption"] = "Вот ошибка"
    calls = telegram_bot.handle_update(upd)
    assert calls and "Обращение №" in calls[0][1]["text"]
    boss = make_user("boss@example.com", name="Андрей")
    t = next(x for x in boss.get("/api/admin/support").json() if "shotter" in (x.get("contact") or ""))
    msgs = boss.get(f"/api/admin/support/{t['id']}").json()["messages"]
    assert any(m["image_url"] for m in msgs) and any(m["text"] == "Вот ошибка" for m in msgs)
    assert boss.get(next(m["image_url"] for m in msgs if m["image_url"])).headers["content-type"] == "image/jpeg"
    # голосовое — вежливо просим текст или скриншот
    v = _private("", chat_id=910)
    v["message"].pop("text")
    v["message"]["voice"] = {"file_id": "v"}
    assert "скриншот" in telegram_bot.handle_update(v)[0][1]["text"]



def test_screenshot_goes_to_telegram_as_photo(monkeypatch):
    from conftest import jpeg_bytes

    from app import push

    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    monkeypatch.setattr(settings, "telegram_support_chat_id", "-1001")
    photos, texts = [], []
    monkeypatch.setattr(push, "_in_background", lambda fn, *a: (photos if fn is push._send_photo else texts).append(a))
    u = make_user("shotg@x.io", name="Ксения")
    tid = u.post("/api/support/threads", json={"topic": "support", "category": "complaint", "text": "Жалоба на анкету"}).json()["id"]
    texts.clear()
    u.post(f"/api/support/threads/{tid}/images", files={"file": ("s.jpg", jpeg_bytes(), "image/jpeg")})
    assert len(photos) == 1 and not texts  # картинкой, без текста «посмотрите в админ-панели»
    chat, path, caption, _buttons = photos[0]
    assert str(chat) == "-1001" and f"#{tid}" in caption and path.endswith(".jpg")
    # ответ в группе на скриншот (reply на фото с подписью) уходит человеку
    from app import telegram_bot
    sent = []
    monkeypatch.setattr("app.push._in_background", lambda fn, *a: sent.append(a))
    reply = {"message": {"message_id": 9, "chat": {"id": -1001, "type": "supergroup"}, "from": {"id": 1, "is_bot": False},
                         "text": "Разберёмся", "reply_to_message": {"from": {"is_bot": True}, "caption": caption}}}
    assert "Ответ отправлен" in telegram_bot.handle_update(reply)[0][1]["text"]



def test_ads_broadcast_skips_teens_by_app_age_and_telegram_birthdate(monkeypatch):
    from datetime import date

    from app import broadcasts, telegram_bot
    from app.database import SessionLocal
    from app.models import TelegramContact, User

    calls = []

    def fake(method, payload=None, timeout=15):
        calls.append((method, payload))
        if method == "getChat":
            cid = payload["chat_id"]
            year = {8803: date.today().year - 15, 8801: 1990}.get(cid)  # гость 8803 — 15 лет по Telegram
            return {"ok": True, "result": {"id": cid, **({"birthdate": {"day": 1, "month": 1, "year": year}} if year else {})}}
        return {"ok": True, "result": {"message_id": 700 + len(calls)}}

    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    monkeypatch.setattr(telegram_bot, "api", fake)
    monkeypatch.setattr(broadcasts, "PAUSE", 0)
    boss = make_user("boss@example.com", name="Андрей")
    adult = make_user("adad@x.io", name="Взрослый")
    teen = make_user("adteen@x.io", name="Подросток", age=15, goals=("Дружба",))
    with SessionLocal() as db:
        db.get(User, adult.user_id).telegram_id = 8801
        db.get(User, teen.user_id).telegram_id = 8802
        db.add(TelegramContact(username="guestadult", chat_id=8804))  # гость без даты рождения — возраст неизвестен
        db.add(TelegramContact(username="guestteen", chat_id=8803))
        db.commit()
    assert boss.get("/api/admin/broadcast/audience").json()["ads"] == 3  # подросток из COFI исключён сразу
    boss.post("/api/admin/broadcast", data={"subject": "Скидка", "body": "Текст", "kind": "ads", "advertiser": "ООО Кофе, erid: abc",
                                            "newcomers": "true"})
    sent = {p["chat_id"]: p for m, p in calls if m == "sendMessage"}
    assert set(sent) == {8801, 8804}  # 8802 — подросток в COFI, 8803 — 15 лет по Telegram
    assert sent[8801]["text"].endswith("<i>Реклама. ООО Кофе, erid: abc</i>")
    b = boss.get("/api/admin/broadcasts").json()[0]
    assert b["kind"] == "ads" and not b["newcomers"] and b["reasons"] == {"Младше 18 по данным Telegram": 1}
    assert b["missing"] == 0  # досылать подростку не будем
    # обычная новость уходит и подросткам
    calls.clear()
    boss.post("/api/admin/broadcast", data={"subject": "Новость", "body": "Текст", "everyone": "true"})
    assert 8802 in {p["chat_id"] for m, p in calls if m == "sendMessage"}



def test_ads_without_advertiser_can_be_sent(monkeypatch):
    from app import broadcasts, telegram_bot
    from app.database import SessionLocal
    from app.models import User

    calls = []
    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    monkeypatch.setattr(telegram_bot, "api", lambda m, p=None, timeout=15: calls.append((m, p)) or {"ok": True, "result": {"message_id": 1}})
    monkeypatch.setattr(broadcasts, "PAUSE", 0)
    boss = make_user("boss@example.com", name="Андрей")
    u = make_user("noadv@x.io", name="Взрослый")
    with SessionLocal() as db:
        db.get(User, u.user_id).telegram_id = 9911
        db.commit()
    r = boss.post("/api/admin/broadcast", data={"subject": "Скидка", "body": "Текст", "kind": "ads"})  # поле рекламодателя пустое
    assert r.status_code == 200
    text = next(p["text"] for m, p in calls if m == "sendMessage")
    assert text.endswith("<i>Реклама</i>")
