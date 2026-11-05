from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def bounding_box(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    """Грубый прямоугольник вокруг точки — для быстрой выборки из БД перед точным расчётом."""
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.01))
    return lat - dlat, lat + dlat, lon - dlon, lon + dlon


GRID = 0.02  # ≈2,2 км по широте: столько «шум» в координатах, которые участвуют в расчёте расстояния


def _snap(v: float) -> float:
    return (math.floor(v / GRID) + 0.5) * GRID


def public_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Расстояние для показа другим: обе точки привязаны к сетке ~2 км, результат — целые километры, минимум 1.
    Без этого, подделав свою геопозицию в трёх местах, можно вычислить, где живёт человек (трилатерация)."""
    return max(1, round(haversine_km(_snap(lat1), _snap(lon1), _snap(lat2), _snap(lon2))))
