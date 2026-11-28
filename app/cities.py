"""Город по координатам — без внешних сервисов: координаты никуда не отправляются.

Справочник app/data/cities.json.gz — города мира от 5000 жителей из GeoNames (geonames.org, лицензия CC BY 4.0),
с русскими названиями. Пересобрать: tools/build_cities.py.
"""
from __future__ import annotations

import gzip
import json
import math
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "cities.json.gz"
NEAR_KM = 25   # в этом радиусе берём самый крупный город (район Хошимина → «Хошимин», а не «Binh Thanh»)
FAR_KM = 60    # дальше — город не подписываем


@lru_cache(maxsize=1)
def _index() -> dict[tuple[int, int], list[tuple[str, float, float, int]]]:
    """Сетка 1°×1°: для поиска смотрим только соседние клетки, а не все 70 тысяч городов."""
    grid: dict[tuple[int, int], list] = {}
    try:
        rows = json.load(gzip.open(DATA, "rt", encoding="utf-8"))
    except (OSError, ValueError):
        return grid
    for name, _cc, lat, lon, pop in rows:
        grid.setdefault((math.floor(lat), math.floor(lon)), []).append((name, lat, lon, pop))
    return grid


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(min(1.0, math.sqrt(a)))


def city_name(lat: float | None, lon: float | None) -> str | None:
    if lat is None or lon is None:
        return None
    grid = _index()
    near = []
    for dlat in (-1, 0, 1):
        for dlon in (-1, 0, 1):
            for name, clat, clon, pop in grid.get((math.floor(lat) + dlat, math.floor(lon) + dlon), ()):
                d = _km(lat, lon, clat, clon)
                if d <= FAR_KM:
                    near.append((d, pop, name))
    if not near:
        return None
    close = [x for x in near if x[0] <= NEAR_KM]
    if close:
        return max(close, key=lambda x: x[1])[2]
    return min(near)[2]
