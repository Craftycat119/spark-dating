from datetime import timedelta

from app import deps
from app.database import SessionLocal
from app.models import ActivityDay, User, utcnow
from conftest import make_user


def test_admin_audience_stats():
    boss = make_user("boss@example.com")
    a, b = make_user("s1@x.io"), make_user("s2@x.io")
    for c in (a, b):
        c.get("/api/auth/me")
    # «a» вернулся через час — второе посещение за день; «b» заходил 5 дней назад
    with SessionLocal() as db:
        ua = db.get(User, a.user_id)
        ua.last_seen_at = utcnow() - timedelta(hours=1)
        old = deps.local_day(utcnow()) - timedelta(days=5)
        db.add(ActivityDay(user_id=b.user_id, day=old, visits=2))
        db.commit()
    a.get("/api/auth/me")
    aud = boss.get("/api/admin/stats").json()["audience"]
    assert aud["registered"] == 3
    per = {p["key"]: p for p in aud["periods"]}
    assert per["day"]["unique"] == 3  # boss, a, b заходили сегодня
    with SessionLocal() as db:
        assert db.get(ActivityDay, (a.user_id, deps.local_day(utcnow()))).visits == 2
    assert per["week"]["unique"] == 3 and per["week"]["visits"] >= per["day"]["visits"] + 2
    assert per["month"]["new"] == 3
