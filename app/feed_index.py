"""Анкеты для подбора в памяти, в уже подготовленном виде.

Раньше каждый показ ленты заново читал из базы и разбирал все анкеты: при 2000 пользователей это ~50 мс работы
процессора на запрос, и под нагрузкой лента отвечала секундами. Теперь список собирается раз в 20 секунд
(или сразу, если кто-то изменил анкету), а запрос ленты только проходит по готовым данным.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass

from .ages import group_for, years_between
from .geo import haversine_km, snap
from .interests import MIN_INTERESTS
from .models import User

TTL = 20


@dataclass(slots=True)
class Candidate:
    id: int
    group: str | None
    gender: str | None
    looking: str | None
    slat: float  # координаты, привязанные к сетке ~2 км: точное место никто не вычислит
    slon: float
    interests: list
    goals: frozenset
    is_bot: bool
    is_demo: bool


_items: list[Candidate] = []
_built = 0.0
_dirty = True
_lock = threading.Lock()


def invalidate() -> None:
    """Кто-то изменил анкету, пол, геопозицию или его заблокировали: пересобрать при следующем запросе."""
    global _dirty
    _dirty = True


def candidates(db) -> list[Candidate]:
    global _items, _built, _dirty
    if not _dirty and time.monotonic() - _built < TTL:
        return _items
    with _lock:
        if not _dirty and time.monotonic() - _built < TTL:
            return _items
        _dirty = False  # изменения во время сборки снова поднимут флаг
        from .routers.feed import visible_users  # тот же фильтр «кого вообще можно показывать»

        rows = db.execute(visible_users().with_only_columns(
            User.id, User.birth_date, User.gender, User.looking_for, User.lat, User.lon,
            User.interests_json, User.goals_json, User.is_bot, User.is_demo))
        items = []
        for uid, birth, gender, looking, lat, lon, interests_json, goals_json, is_bot, is_demo in rows:
            interests, goals = json.loads(interests_json or "[]"), json.loads(goals_json or "[]")
            if len(interests) < MIN_INTERESTS or not goals:
                continue  # опрос не пройден — в ленте не показываем
            items.append(Candidate(uid, group_for(years_between(birth)), gender, looking, snap(lat), snap(lon),
                                   interests, frozenset(goals), bool(is_bot), bool(is_demo)))
        _items, _built = items, time.monotonic()
        return _items


def distance(user_lat: float, user_lon: float, c: Candidate) -> int:
    return max(1, round(haversine_km(snap(user_lat), snap(user_lon), c.slat, c.slon)))
