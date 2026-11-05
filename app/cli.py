"""Служебные команды:

    python -m app.cli make-admin you@mail.com   — выдать права администратора
    python -m app.cli seed --lat 55.75 --lon 37.62 — создать демо-анкеты рядом с точкой
    python -m app.cli download-models           — скачать нейросети для проверки лица
"""
from __future__ import annotations

import argparse
import random

from PIL import Image, ImageDraw
from sqlalchemy import select

from . import storage
from .config import settings
from .ages import birth_for_age
from .interests import GOALS, SURVEY
from .database import SessionLocal, init_db
from .face_verify import download_models
from .legal import TERMS_VERSION
from .models import AnimalPost, User, UserPhoto, utcnow
from .security import hash_password

DEMO_NAMES = ["Алина", "Марк", "Соня", "Илья", "Вера", "Тимур", "Ника", "Глеб", "Лиза", "Артём", "Мира", "Даня"]
DEMO_BIOS = [
    "Люблю ночные прогулки по набережной и плёночные фотоаппараты.",
    "Кофе, скалодром и стендап по пятницам.",
    "Ищу компанию на настолки и походы выходного дня.",
    "Готовлю лучшую пасту в районе. Проверишь?",
    "Работаю в IT, по вечерам играю на гитаре.",
    "Путешествую налегке, в этом году была в Грузии и Армении.",
]
ANIMALS = [
    ("charity", "Барсик", "Кошка", "3 года", (
        "Барсика сбила машина у метро, волонтёры подобрали его ночью. Перелом задней лапы, нужна операция с пластиной "
        "и две недели стационара. Клиника на Профсоюзной согласилась оперировать сразу, оплату ждут после.\n\n"
        "Сам Барсик ласковый, мурчит даже на перевязках, с другими кошками ладит. После лечения будем искать ему дом. "
        "Все чеки и выписки выкладываем в канал, отчёт пришлём каждому, кто помог."), "38 000 ₽", "#c9461a"),
    ("adoption", "Рыжик", "Кошка", "7 месяцев", (
        "Рыжик вырос на передержке у волонтёра: приучен к лотку и когтеточке, привит, кастрирован, обработан от паразитов. "
        "Очень любопытный и игривый, обожает мячики и сидеть на подоконнике.\n\n"
        "Ищем дом без маленьких детей: Рыжик пока может поцарапать в игре. Отдаём по договору ответственного содержания, "
        "привезём сами и поможем с первыми днями."), "", "#e0743a"),
    ("foster", "Луна", "Собака", "2 года", (
        "Луна после стерилизации, ей нужна спокойная передержка на две недели, пока заживает шов. Она тихая, "
        "приучена к поводку, гуляет два раза в день, ладит с людьми, к кошкам равнодушна.\n\n"
        "Корм, попону, лекарства и пелёнки даём. Подойдёт квартира без других собак в Москве или ближнем Подмосковье. "
        "Волонтёр на связи каждый день и приедет на снятие швов."), "", "#a8411f"),
    ("charity", "Стерилизация бездомных животных", "Другое", "", (
        "Собираем на стерилизацию 12 бездомных кошек и собак, которых волонтёры отловили у гаражей на Юго-Западе. "
        "Стерилизация решает проблему гуманно: без неё за год у одной кошки рождается до 20 котят, и почти все они "
        "погибают на улице.\n\n"
        "Ветклиника делает операции по льготной цене: 1 700 ₽ за кошку и 2 500 ₽ за собаку, включая наркоз, "
        "чипирование и прививку от бешенства. После операции животных подержим на передержке и выпустим в привычное "
        "место под присмотр подкармливающих соседей, а ручных пристроим в дома. Отчёт с чеками и фото каждого хвоста "
        "опубликуем в канале."), "20 000 ₽", "#cf5a2c"),
]
COLORS = ["#ff5b1f", "#c9411a", "#e8763f", "#8a3214", "#ff8a4c", "#5a2410"]


def make_admin(email: str) -> None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email.strip().lower()))
        if not user:
            raise SystemExit(f"Пользователь {email} не найден — сначала зарегистрируйтесь")
        user.is_admin = True
        db.commit()
        print(f"{email} теперь администратор. Панель: /admin")


def _avatar(name: str, color: str) -> str:
    img = Image.new("RGB", (800, 1000), color)
    d = ImageDraw.Draw(img)
    for i in range(0, 1000, 40):
        d.line([(0, i), (800, i + 300)], fill=(255, 255, 255, 30), width=2)
    d.ellipse([250, 260, 550, 560], fill="#ffffff")
    d.text((40, 900), name, fill="#ffffff")
    import io

    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return storage.save_image(buf.getvalue(), "photos")


def seed(lat: float, lon: float, count: int) -> None:
    with SessionLocal() as db:
        for i in range(count):
            name = DEMO_NAMES[i % len(DEMO_NAMES)]
            u = User(
                email=f"demo{i + 1}@example.com",
                terms_accepted_at=utcnow(), terms_version=TERMS_VERSION, age_confirmation="adult",
                password_hash=hash_password("Demo12345"),
                email_verified=True,
                name=name,
                age=(a := random.randint(19, 38)),
                birth_date=birth_for_age(a),
                bio=random.choice(DEMO_BIOS),
                photo_path=_avatar(name, COLORS[i % len(COLORS)]),
                photo_verified=True,
                photo_verified_at=utcnow(),
                lat=lat + random.uniform(-0.15, 0.15),
                lon=lon + random.uniform(-0.25, 0.25),
                registration_ip="127.0.0.1",
            )
            u.registration_lat, u.registration_lon = u.lat, u.lon
            for k in range(random.randint(1, 3)):
                u.photos.append(UserPhoto(path=_avatar(f"{name} {k + 2}", COLORS[(i + k + 2) % len(COLORS)])))
            u.gender = "female" if i % 2 == 0 else "male"
            u.looking_for = random.choice(["male", "female", "any"]) if i % 3 else "any"
            u.goals = random.sample(sorted(GOALS), k=random.randint(1, 2))
            u.interests = [opt for q in SURVEY[1:] for opt in random.sample(q["options"], k=random.randint(1, 3))]
            db.add(u)
        db.commit()
        author = db.scalar(select(User).where(User.email == "demo1@example.com"))
        for cat, name, species, age, desc, goal, color in ANIMALS:
            post = AnimalPost(author_id=author.id, category=cat, name=name, species=species, age_text=age, city="Москва",
                              description=desc, contact="@cofi_volunteers", fundraising_goal=goal, lat=lat, lon=lon)
            post.photos = [_avatar(name, color), _avatar(f"{name} 2", color), _avatar(f"{name} 3", color)]
            db.add(post)
        db.commit()
    print(f"Создано {count} демо-анкет (пароль у всех Demo12345) и {len(ANIMALS)} объявлений о животных")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("make-admin")
    p.add_argument("email")
    s = sub.add_parser("seed")
    s.add_argument("--lat", type=float, default=55.7558)
    s.add_argument("--lon", type=float, default=37.6173)
    s.add_argument("--count", type=int, default=12)
    sub.add_parser("download-models")
    sub.add_parser("outlook-login", help="подключить личную почту Outlook.com для отправки кодов")
    t = sub.add_parser("test-email", help="отправить пробное письмо")
    t.add_argument("to")
    args = parser.parse_args()

    init_db()
    if args.cmd == "make-admin":
        make_admin(args.email)
    elif args.cmd == "seed":
        seed(args.lat, args.lon, args.count)
    elif args.cmd == "download-models":
        download_models()
        print("Готово")
    elif args.cmd == "outlook-login":
        from .outlook_oauth import login_interactive

        login_interactive()
    elif args.cmd == "test-email":
        from .emailer import send_email

        ok = send_email(args.to, "COFI: проверка почты", "Если вы читаете это письмо, отправка кодов работает.")
        print("Письмо отправлено" if ok and settings.smtp_host else "Не отправлено, подробности выше в логе")


if __name__ == "__main__":
    main()
