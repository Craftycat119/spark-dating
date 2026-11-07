"""Демо-режим: временный аккаунт без регистрации и 10 ботов-анкет.

Боты видны только демо-пользователям, а демо-пользователи — только ботам,
поэтому реальные пользователи их никогда не встретят. Демо-аккаунт живёт сутки.
Часть ботов заранее «лайкнула» гостя, так что взаимные пары случаются;
в чате боты отвечают заготовленными репликами.
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .ages import birth_for_age
from .config import settings
from .database import SessionLocal
from .legal import TERMS_VERSION
from .models import Conversation, Message, Swipe, User, UserPhoto, utcnow
from .realtime import notify
from .serializers import message_out

log = logging.getLogger("cofi.demo")

CENTER = (55.7558, 37.6173)  # центр Москвы
DEMO_TTL = timedelta(hours=24)


def portrait(gender: str, n: int) -> str:
    return f"https://randomuser.me/api/portraits/{'women' if gender == 'female' else 'men'}/{n}.jpg"


def scene(seed: str) -> str:
    return f"https://picsum.photos/seed/cofi-{seed}/720/900"


GUEST = {
    "name": "Гость",
    "age": 27,
    "gender": "male",
    "looking_for": "any",
    "goals": ["Свидания", "Дружба"],
    "interests": ["Кофейни", "Бег", "Фотография", "Техно", "Путешествия", "Фантастика", "Юмор", "Природа и походы"],
    "bio": "Это демо-аккаунт. Здесь можно свайпать, открывать анкеты, получать пары и переписываться с ботами.",
    "photo": portrait("male", 32),
}

# fit — для себя: насколько бот подходит гостю (perfect / medium / poor)
BOTS: list[dict] = [
    {
        "key": "alina", "fit": "perfect", "name": "Алина", "age": 26, "gender": "female", "km": (1.2, 0.8),
        "likes_you": True, "photo": 44, "scenes": ["film-camera", "coffee-bar", "mountain-trail"],
        "goals": ["Свидания", "Серьёзные отношения"],
        "interests": ["Кофейни", "Бег", "Фотография", "Техно", "Путешествия", "Фантастика", "Природа и походы", "Йога"],
        "bio": (
            "Фотографирую на плёнку и до сих пор радуюсь каждой проявке, как ребёнок. По будням продуктовый дизайнер, "
            "по субботам бегаю 10 км вдоль Москвы-реки, а потом иду в кофейню и пробую всё, что сварили на новом зерне. "
            "Люблю техно-вечеринки в старых заводах, но ухожу до шести утра, чтобы успеть на рассвет. За последние два "
            "года была в Грузии, Армении и на Алтае, следующий план: пешком по Ликийской тропе. Пересматриваю «Бегущего "
            "по лезвию» раз в год. Ищу человека, с которым можно и в поход с палаткой, и молча посидеть с книгами в одной "
            "кофейне. Плюс, если умеешь варить пуровер лучше меня."
        ),
        "replies": [
            "Привет! Вижу, ты тоже бегаешь. Какая у тебя любимая дистанция?",
            "О, классно! А на плёнку снимаешь или на цифру? У меня Zenit и Olympus mju",
            "Слушай, в субботу на Хлебозаводе будет хороший техно-сет. Пойдём?",
        ],
    },
    {
        "key": "maxim", "fit": "perfect", "name": "Максим", "age": 29, "gender": "male", "km": (-2.5, 1.9),
        "likes_you": True, "photo": 75, "scenes": ["bike-forest", "camp-tent", "techno-club"],
        "goals": ["Дружба", "Компания для хобби"],
        "interests": ["Бег", "Фотография", "Природа и походы", "Путешествия", "Техно", "Кофейни", "Велосипед", "Юмор"],
        "bio": (
            "Собираю компанию для походов выходного дня и велосипедных выездов за город. Работаю бэкенд-разработчиком, "
            "поэтому в свободное время стараюсь быть подальше от экрана. Летом прошёл Кольский пешком, зимой катаюсь на "
            "беговых лыжах. Снимаю всё на старый Fujifilm и веду маленький канал с фотками из поездок. Люблю хорошую "
            "электронику, иногда играю диджей-сеты для друзей. Ищу людей, которым не лень встать в пять утра ради "
            "рассвета на вершине, и с которыми потом весело сидеть у костра и шутить до полуночи."
        ),
        "replies": [
            "Здорово, что совпали! Ты в походы ходишь или больше по городу гуляешь?",
            "Мы в эти выходные едем на великах в Звенигород, присоединяйся",
            "Отлично, кину детали ближе к пятнице 🙌",
        ],
    },
    {
        "key": "vera", "fit": "perfect", "name": "Вероника", "age": 24, "gender": "female", "km": (0.6, -3.1),
        "likes_you": True, "photo": 68, "scenes": ["neon-city", "anime-room", "concert-lights"],
        "goals": ["Свидания", "Просто общение"],
        "interests": ["Фантастика", "Аниме", "Кофейни", "Техно", "Электроника", "Юмор", "Фотография", "Путешествия"],
        "bio": (
            "Иллюстратор, рисую обложки для музыкальных релизов. Обожаю научную фантастику: от Лема и Стругацких до "
            "«Пространства» и «Аркейна». Смотрю аниме без стыда и могу час рассказывать, почему «Евангелион» гениален. "
            "Мой идеальный вечер: лайв-сет в маленьком клубе, потом ночная шаверма и разговоры о том, есть ли жизнь на "
            "Европе. Фотографирую неоновые вывески и коллекционирую значки из каждого города. Ищу человека с хорошим "
            "чувством юмора, который не боится странных идей и готов спонтанно уехать в Питер на выходные."
        ),
        "replies": [
            "Хей! Какое у тебя любимое аниме? Только честно 😄",
            "Принято. Тогда вопрос с подвохом: «Дюна» книга или фильм?",
            "Мне нравится, как ты думаешь. Может, кофе на неделе?",
        ],
    },
    {
        "key": "daniil", "fit": "medium", "name": "Даниил", "age": 31, "gender": "male", "km": (3.8, 2.2),
        "likes_you": False, "photo": 41, "scenes": ["gym-weights", "restaurant-dinner", "airport"],
        "goals": ["Серьёзные отношения"],
        "interests": ["Бег", "Спортзал", "Рестораны", "Карьера", "Путешествия", "Комедии", "Саморазвитие"],
        "bio": (
            "Руковожу отделом продаж в айти-компании, много летаю по работе и стараюсь из каждой командировки привезти "
            "новую кухню. Утром бег или зал, вечером книги по менеджменту или хорошая комедия. Готовлю стейки и пасту, "
            "умею выбирать вино. Ценю пунктуальность и людей, у которых есть цель. Ищу серьёзные отношения: человека, "
            "с которым можно строить планы на годы вперёд и при этом не забывать отдыхать."
        ),
        "replies": [
            "Привет! Рад знакомству. Чем занимаешься?",
            "Интересно. Как насчёт ужина в четверг? Знаю отличное грузинское место",
        ],
    },
    {
        "key": "sonya", "fit": "medium", "name": "Соня", "age": 27, "gender": "female", "km": (-1.4, -2.6),
        "likes_you": True, "photo": 12, "scenes": ["museum-hall", "yoga-mat", "bookshop"],
        "goals": ["Свидания", "Дружба"],
        "interests": ["Кофейни", "Йога", "Выставки и музеи", "Театр", "Чтение", "Инди", "Драмы", "Путешествия"],
        "bio": (
            "Работаю куратором в небольшой галерее современного искусства. Утро начинаю с йоги и капучино на овсяном, "
            "вечера провожу в театре или с книгой. Сейчас читаю Салли Руни и перечитываю Довлатова. Слушаю инди и "
            "собираю плейлисты под каждое время года. Мечтаю съездить в Японию весной. Ищу человека, с которым можно "
            "обсуждать спектакли до ночи и молча гулять по бульварам."
        ),
        "replies": [
            "Привет! Ты бываешь на выставках? Сейчас в Гараже очень интересная",
            "Тогда пойдём вместе в воскресенье, а потом в кофейню рядом 🙂",
        ],
    },
    {
        "key": "artem", "fit": "medium", "name": "Артём", "age": 33, "gender": "male", "km": (2.1, -1.7),
        "likes_you": False, "photo": 52, "scenes": ["board-games", "standup-mic", "retro-console"],
        "goals": ["Дружба", "Компания для хобби"],
        "interests": ["Настольные игры", "Видеоигры", "Фантастика", "Программирование", "Стендап", "Юмор", "Дома с фильмом"],
        "bio": (
            "Геймдизайнер, собираю коллекцию настолок (уже больше восьмидесяти коробок). По средам устраиваю игротеку "
            "дома, по пятницам хожу на открытые микрофоны и иногда сам выступаю. Люблю фантастику, ретро-приставки и "
            "долгие кооперативные игры. Ищу людей в компанию: на «Мрачную гавань», «Каркассон» и просто поболтать."
        ),
        "replies": ["Привет! Настолки любишь? В среду собираемся на «Кодовые имена»"],
    },
    {
        "key": "liza", "fit": "medium", "name": "Лиза", "age": 25, "gender": "female", "km": (-3.3, 0.4),
        "likes_you": True, "photo": 26, "scenes": ["dance-floor", "beach-sunset", "festival"],
        "goals": ["Просто общение", "Свидания"],
        "interests": ["Танцы", "Вечеринки", "Техно", "Электроника", "Пляж", "Путешествия", "Свобода"],
        "bio": (
            "Танцую хаус и вог, преподаю в студии три раза в неделю. Летом живу от фестиваля к фестивалю: Outline, "
            "Signal, а осенью обязательно Бали или Шри-Ланка. Обожаю электронику и людей, которые не стесняются "
            "танцевать. Ценю свободу и спонтанность, не люблю долгие переписки. Пиши, если знаешь хорошую вечеринку."
        ),
        "replies": ["Привет! Ты танцуешь? 😄", "Тогда точно надо сходить вместе, научу базе"],
    },
    {
        "key": "oleg", "fit": "poor", "name": "Олег", "age": 38, "gender": "male", "km": (5.2, 4.1),
        "likes_you": False, "photo": 85, "scenes": ["church-old", "family-dinner", "office"],
        "goals": ["Серьёзные отношения"],
        "interests": ["Рестораны", "Семья", "Вера", "Карьера", "Классика", "Драмы"],
        "bio": (
            "Финансовый директор, человек традиционных взглядов. Семья для меня на первом месте, хожу в церковь по "
            "воскресеньям, слушаю классическую музыку. Отдыхаю в хороших ресторанах и на даче. Не люблю шумные "
            "вечеринки и спонтанность. Ищу спокойную, хозяйственную спутницу для создания семьи."
        ),
        "replies": ["Добрый день. Расскажите о себе, пожалуйста."],
    },
    {
        "key": "karina", "fit": "poor", "name": "Карина", "age": 30, "gender": "female", "km": (-4.6, 3.3),
        "likes_you": False, "photo": 90, "scenes": ["horror-night", "plants-home", "knitting"],
        "goals": ["Серьёзные отношения"],
        "interests": ["Метал", "Ужасы", "Видеоигры", "Дома с фильмом", "Рукоделие", "Растения"],
        "bio": (
            "Интроверт со стажем. Дома у меня сорок растений, два кота и гитара, на которой играю дум-метал. Смотрю "
            "хорроры, вяжу свитера и прохожу Dark Souls в пятый раз. Из дома выхожу ради концертов и садового центра. "
            "Ищу такого же домоседа для уютных вечеров."
        ),
        "replies": ["Привет. Любишь хорроры?"],
    },
    {
        "key": "igor", "fit": "poor", "name": "Игорь", "age": 35, "gender": "male", "km": (4.4, -4.8),
        "likes_you": False, "photo": 9, "scenes": ["night-club", "car-city", "luxury-dinner"],
        "goals": ["Просто общение"],
        "interests": ["Спортзал", "Хип-хоп", "Вечеринки", "Рестораны", "Карьера", "Свобода"],
        "bio": (
            "Предприниматель, у меня сеть автомоек. Зал пять раз в неделю, по выходным клубы и рестораны. Слушаю "
            "рэп, гоняю на машине по ночному городу. Серьёзные отношения не ищу, интересно лёгкое общение без "
            "обязательств."
        ),
        "replies": ["Привет 😎"],
    },
]

# Лента «Дружба» (14–17): только дружба и общие хобби, без романтики.
# Фото у ботов-подростков рисованные (буква на вязаном фоне), а не фотографии людей.
TEEN_GUEST = {
    "name": "Гость",
    "age": 15,
    "gender": "male",
    "looking_for": "any",
    "goals": ["Дружба", "Компания для хобби"],
    "interests": ["Видеоигры", "Аниме", "Программирование", "Настольные игры", "Бег", "Фантастика", "Юмор", "Рисование"],
    "bio": "Это демо ленты «Дружба» (до 18 лет). Здесь только дружба: ищите компанию по интересам.",
}

TEEN_BOTS: list[dict] = [
    {
        "key": "teen_masha", "name": "Маша", "age": 15, "gender": "female", "km": (1.1, -0.9), "likes_you": True,
        "scenes": ["anime-room", "sketchbook", "board-games"], "goals": ["Дружба", "Компания для хобби"],
        "interests": ["Аниме", "Рисование", "Настольные игры", "Фантастика", "Юмор", "Видеоигры"],
        "bio": (
            "Рисую мангу в планшете и мечтаю выпустить свой комикс. Хожу в художку по вторникам и четвергам, "
            "а по выходным играю с друзьями в настолки: сейчас залипли в «Каркассон» и «Мафию». Ищу ребят, "
            "с которыми можно обсуждать аниме, вместе ходить на фестивали и рисовать на скорость."
        ),
        "replies": ["Привет! Какое аниме сейчас смотришь?", "Круто! Приходи в субботу в антикафе на настолки, нас там пятеро"],
    },
    {
        "key": "teen_kirill", "name": "Кирилл", "age": 16, "gender": "male", "km": (-1.8, 1.4), "likes_you": True,
        "scenes": ["robotics", "retro-console", "bike-forest"], "goals": ["Компания для хобби", "Дружба"],
        "interests": ["Программирование", "Видеоигры", "Фантастика", "Велосипед", "Настольные игры"],
        "bio": (
            "Собираю роботов в кружке робототехники, в этом году ездили на олимпиаду в Казань. Пишу бота для "
            "Telegram на Python и учу Unity. Летом катаюсь на велике по паркам. Ищу команду на хакатон для "
            "школьников и тех, кто любит кооперативные игры."
        ),
        "replies": ["Хей! Ты тоже кодишь? На чём пишешь?", "Давай вместе на хакатон в декабре, нужен ещё человек в команду"],
    },
    {
        "key": "teen_dasha", "name": "Даша", "age": 16, "gender": "female", "km": (2.3, 0.6), "likes_you": False,
        "scenes": ["volunteer-shelter", "dog-walk", "bookshop"], "goals": ["Дружба"],
        "interests": ["Животные", "Чтение", "Экология", "Бег", "Юмор"],
        "bio": (
            "Волонтёрю в приюте: гуляю с собаками по воскресеньям. Читаю фэнтези и детективы, бегаю по утрам. "
            "Хочу найти друзей, которые тоже любят животных, чтобы вместе ходить в приют и на эко-субботники."
        ),
        "replies": ["Привет! Хочешь в воскресенье с нами в приют погулять с собаками?"],
    },
    {
        "key": "teen_tim", "name": "Тимофей", "age": 17, "gender": "male", "km": (-2.9, -1.5), "likes_you": False,
        "scenes": ["skate-park", "concert-lights", "guitar-room"], "goals": ["Компания для хобби", "Просто общение"],
        "interests": ["Играю на инструменте", "Рок", "Инди", "Концерты", "Юмор"],
        "bio": (
            "Играю на гитаре в школьной группе, репетируем в подвале у барабанщика. Катаюсь на скейте в парке "
            "у реки. Ищем басиста и просто людей, с кем можно сходить на концерт или поджемить."
        ),
        "replies": ["Привет! На чём играешь? Нам нужен басист 🎸"],
    },
    {
        "key": "teen_vika", "name": "Вика", "age": 14, "gender": "female", "km": (0.4, 2.7), "likes_you": True,
        "scenes": ["dance-floor", "k-pop", "coffee-bar"], "goals": ["Дружба", "Просто общение"],
        "interests": ["Танцы", "K-pop", "Поп", "Юмор", "Сериалы запоем"],
        "bio": (
            "Танцую k-pop каверы в студии, снимаем ролики на телефон. Обожаю сериалы и какао с маршмеллоу. "
            "Ищу подругу или друга для танцевальной команды и просто поболтать после школы."
        ),
        "replies": ["Привет! Любишь k-pop? Какая группа любимая?", "Приходи к нам на пробное занятие в студию!"],
    },
    {
        "key": "teen_gosha", "name": "Гоша", "age": 17, "gender": "male", "km": (3.6, -2.2), "likes_you": False,
        "scenes": ["football", "gym-weights", "mountain-trail"], "goals": ["Компания для хобби"],
        "interests": ["Спортзал", "Бег", "Природа и походы", "Документальное"],
        "bio": (
            "Играю в футбол за школьную команду, по выходным хожу с отцом в походы. Готовлюсь к ЕГЭ по биологии. "
            "Ищу ребят на дворовый футбол и пробежки."
        ),
        "replies": ["Привет! Погоняем в футбол в субботу?"],
    },
]

FALLBACK_REPLY = "Давай лучше встретимся и обсудим вживую 🙂"
TEEN_FALLBACK = "Давай договоримся встретиться всей компанией, так веселее 🙂"


def _teen_portrait(name: str) -> str:
    """Рисованный портрет для бота-подростка (буква на вязаном фоне)."""
    from .cli import _avatar

    return _avatar(name, "#c9461a")


def ensure_bots(db: Session) -> list[User]:
    bots = {u.email: u for u in db.scalars(select(User).where(User.is_bot.is_(True)))}
    created = []
    for b in BOTS + TEEN_BOTS:
        email = f"{b['key']}@bots.cofi"
        if email in bots:
            continue
        lat = CENTER[0] + b["km"][0] / 111
        lon = CENTER[1] + b["km"][1] / 63
        u = User(
            email=email, email_verified=False, email_notifications=False, auth_provider="bot", is_bot=True,
            name=b["name"], age=b["age"], birth_date=birth_for_age(b["age"]), gender=b["gender"], looking_for="any", bio=b["bio"],
            photo_path=_teen_portrait(b["name"]) if b in TEEN_BOTS else portrait(b["gender"], b["photo"]),
            photo_verified=True, photo_verified_at=utcnow(),
            lat=lat, lon=lon, registration_lat=lat, registration_lon=lon,
        )
        u.goals, u.interests = b["goals"], b["interests"]
        for s in b["scenes"]:
            u.photos.append(UserPhoto(path=scene(s)))
        db.add(u)
        created.append(u)
    if created:
        db.commit()
    return list(db.scalars(select(User).where(User.is_bot.is_(True))))


def create_guest(db: Session, ip: str, user_agent: str, teen: bool = False) -> User:
    cleanup(db)
    bots = ensure_bots(db)
    G = TEEN_GUEST if teen else GUEST
    g = User(
        name=G["name"], age=G["age"], birth_date=birth_for_age(G["age"]), gender=G["gender"], looking_for=G["looking_for"],
        bio=G["bio"], auth_provider="demo", is_demo=True, email_notifications=False,
        terms_accepted_at=utcnow(), terms_version=TERMS_VERSION, age_confirmation="guardian" if teen else "adult",
        photo_path=_teen_portrait(G["name"]) if teen else G["photo"], photo_verified=True, photo_verified_at=utcnow(),
        lat=CENTER[0], lon=CENTER[1], registration_lat=CENTER[0], registration_lon=CENTER[1],
        registration_ip=ip, registration_user_agent=user_agent[:512], max_distance_km=50,
    )
    g.goals, g.interests = G["goals"], G["interests"]
    db.add(g)
    db.flush()
    by_email = {b.email: b for b in bots}
    for b in TEEN_BOTS if teen else BOTS:
        if b["likes_you"]:
            db.add(Swipe(from_user_id=by_email[f"{b['key']}@bots.cofi"].id, to_user_id=g.id, liked=True))
    db.commit()
    from . import feed_index

    feed_index.invalidate()  # новые боты и гость должны сразу попасть в подбор
    return g


def cleanup(db: Session) -> int:
    """Удаляет демо-аккаунты старше суток."""
    from .routers.profile import delete_user_completely

    old = db.scalars(select(User).where(User.is_demo.is_(True), User.created_at < utcnow() - DEMO_TTL)).all()
    for u in old:
        delete_user_completely(db, u)
    return len(old)


def _script(bot: User) -> list[str]:
    key = bot.email.split("@")[0]
    return next((b["replies"] for b in BOTS + TEEN_BOTS if b["key"] == key), [])


def bot_reply(conv_id: int, bot_id: int, greeting: bool = False) -> None:
    """Ответ бота с паузой и индикатором «печатает». Запускается фоновой задачей FastAPI."""
    delay = settings.demo_reply_delay
    with SessionLocal() as db:
        bot = db.get(User, bot_id)
        conv = db.get(Conversation, conv_id)
        if not bot or not conv or not conv.active:
            return
        guest_id = conv.other(bot_id).id
        sent = db.scalars(select(Message).where(Message.conversation_id == conv_id, Message.sender_id == bot_id)).all()
        if greeting and sent:
            return
        script = _script(bot)
        fallback = TEEN_FALLBACK if bot.age_group == "teen" else FALLBACK_REPLY
        text = script[len(sent)] if len(sent) < len(script) else fallback
    if delay:
        time.sleep(delay * 0.4)
        notify(guest_id, {"type": "typing", "conversation_id": conv_id})
        time.sleep(delay * 0.6)
    with SessionLocal() as db:
        conv = db.get(Conversation, conv_id)
        if not conv or not conv.active:
            return
        msg = Message(conversation_id=conv_id, sender_id=bot_id, kind="text", text=text)
        db.add(msg)
        conv.last_message_at = utcnow()
        db.commit()
        db.refresh(msg)
        notify(guest_id, {"type": "message", "message": message_out(msg)})
