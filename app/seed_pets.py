"""Готовые объявления «Питомцы» (папка app/seed/pets): при запуске сервера добавляются в базу один раз.

Автор — первый администратор. Что уже добавлено, отмечено в базе (таблица app_flags), поэтому объявление,
которое администратор удалил, при следующем запуске не появится снова.
Добавить вручную: python -m app.cli seed-pets
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import storage
from .models import AnimalPost, AppFlag, User

log = logging.getLogger("cofi.pets")
SEED_DIR = Path(__file__).resolve().parent / "seed" / "pets"
CITY_COORDS = {"Нячанг": (12.2388, 109.1967)}


def seed_pets(db: Session) -> int:
    """Добавляет новые объявления из app/seed/pets. Возвращает, сколько добавлено."""
    items = json.loads((SEED_DIR / "pets.json").read_text(encoding="utf-8"))
    done = set(db.scalars(select(AppFlag.key).where(AppFlag.key.like("pet:%"))))
    todo = [p for p in items if f"pet:{p['key']}" not in done]
    if not todo:
        return 0
    author = db.scalar(select(User).where(User.is_admin.is_(True), User.is_bot.is_(False)).order_by(User.id))
    if not author:
        log.info("Объявления о питомцах (%s шт.) добавятся, когда появится администратор: откройте админ-панель или перезапустите сервер", len(todo))
        return 0
    for p in reversed(todo):  # лента показывает новые первыми: так первое объявление из списка окажется сверху
        lat, lon = CITY_COORDS.get(p["city"], (author.lat, author.lon))
        post = AnimalPost(author_id=author.id, category=p["category"], name=p["name"], species=p["species"],
                          age_text=p["age_text"], city=p["city"], description=p["description"],
                          contact=p.get("contact", ""), fundraising_goal=p.get("fundraising_goal", ""), lat=lat, lon=lon)
        # первым идёт фото с карточкой о питомце
        post.photos = [storage.save_image((SEED_DIR / name).read_bytes(), "animals") for name in p["photos"]]
        db.add(post)
        db.add(AppFlag(key=f"pet:{p['key']}"))
    db.commit()
    log.info("Добавлено объявлений о питомцах: %s", len(todo))
    return len(todo)
