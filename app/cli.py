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
from .interests import GOALS, SURVEY
from .database import SessionLocal, init_db
from .face_verify import download_models
from .models import User, UserPhoto, utcnow
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
                password_hash=hash_password("Demo12345"),
                email_verified=True,
                name=name,
                age=random.randint(19, 38),
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
    print(f"Создано {count} демо-анкет (пароль у всех Demo12345)")


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
    args = parser.parse_args()

    init_db()
    if args.cmd == "make-admin":
        make_admin(args.email)
    elif args.cmd == "seed":
        seed(args.lat, args.lon, args.count)
    elif args.cmd == "download-models":
        download_models()
        print("Готово")


if __name__ == "__main__":
    main()
