from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import demo, emailer
from ..database import get_db
from ..deps import current_user
from ..geo import bounding_box, haversine_km
from ..interests import compatible, match_score
from ..models import Conversation, Notification, Swipe, User
from ..realtime import notify
from ..serializers import photo_url, public_card

router = APIRouter(prefix="/api/feed", tags=["feed"])
notifications_router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class SwipeIn(BaseModel):
    user_id: int
    like: bool


def _require_access(user: User) -> None:
    if not user.is_complete:
        raise HTTPException(409, {"code": "profile_incomplete", "message": "Заполните анкету и подтвердите фото"})
    if user.lat is None:
        raise HTTPException(409, {"code": "need_location", "message": "Разрешите доступ к геопозиции"})


def visible_users():
    return select(User).where(
        User.photo_verified.is_(True),
        User.is_banned.is_(False),
        User.lat.is_not(None),
        User.age.is_not(None),
        User.gender.is_not(None),
        User.name != "",
    )


def audience(q, user: User):
    """Демо-гости видят только ботов; реальные пользователи не видят ни ботов, ни гостей."""
    if user.is_demo:
        return q.where(User.is_bot.is_(True))
    return q.where(User.is_bot.is_(False), User.is_demo.is_(False))


@router.get("")
def get_feed(limit: int = 10, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Анкеты рядом, сначала с наибольшим совпадением интересов, при равенстве — ближайшие."""
    _require_access(user)
    limit = max(1, min(limit, 30))

    swiped = select(Swipe.to_user_id).where(Swipe.from_user_id == user.id)
    q = audience(visible_users(), user).where(User.id != user.id, User.id.not_in(swiped))
    radius = user.max_distance_km
    if radius < 20000:
        lat_min, lat_max, lon_min, lon_max = bounding_box(user.lat, user.lon, radius)
        q = q.where(User.lat.between(lat_min, lat_max))
        if lon_min >= -180 and lon_max <= 180:
            q = q.where(User.lon.between(lon_min, lon_max))

    my_interests, my_goals = user.interests, user.goals
    scored = []
    for other in db.scalars(q):
        if not other.survey_done:
            continue
        if not compatible(user.gender, user.looking_for, other.gender, other.looking_for):
            continue
        d = haversine_km(user.lat, user.lon, other.lat, other.lon)
        if d > radius:
            continue
        score, common = match_score(my_interests, my_goals, other.interests, other.goals)
        scored.append((score, d, common, other))
    # Группы по 10% совпадения, внутри группы — по расстоянию
    scored.sort(key=lambda x: (-(x[0] // 10), x[1]))
    return {"total": len(scored), "cards": [public_card(o, s, c, d) for s, d, c, o in scored[:limit]]}


def _notify_match(db: Session, conv: Conversation, background: BackgroundTasks) -> None:
    for me, other in ((conv.user_a, conv.user_b), (conv.user_b, conv.user_a)):
        _, common = match_score(me.interests, me.goals, other.interests, other.goals)
        payload = {
            "conversation_id": conv.id,
            "common": common,
            "user": {"id": other.id, "name": other.name, "photo_url": photo_url(other)},
        }
        db.add(Notification(user_id=me.id, kind="match", payload=json.dumps(payload, ensure_ascii=False)))
        notify(me.id, {"type": "match", **payload})
        if me.email and me.email_verified and me.email_notifications:
            background.add_task(emailer.send_match_email, me.email, other.name, common)
    db.commit()


@router.post("/swipe")
def swipe(data: SwipeIn, background: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _require_access(user)
    if data.user_id == user.id:
        raise HTTPException(400, "Нельзя лайкнуть себя")
    target = db.scalar(audience(visible_users(), user).where(User.id == data.user_id))
    if not target:
        raise HTTPException(404, "Анкета больше не доступна")

    existing = db.scalar(select(Swipe).where(Swipe.from_user_id == user.id, Swipe.to_user_id == target.id))
    if existing:
        existing.liked = data.like
    else:
        db.add(Swipe(from_user_id=user.id, to_user_id=target.id, liked=data.like))
    db.commit()

    if not data.like:
        return {"match": False}

    reverse = db.scalar(
        select(Swipe).where(Swipe.from_user_id == target.id, Swipe.to_user_id == user.id, Swipe.liked.is_(True))
    )
    if not reverse:
        return {"match": False}

    a, b = sorted((user.id, target.id))
    conv = db.scalar(select(Conversation).where(Conversation.user_a_id == a, Conversation.user_b_id == b))
    is_new = conv is None or not conv.active
    if conv is None:
        conv = Conversation(user_a_id=a, user_b_id=b)
        db.add(conv)
    conv.active = True
    db.commit()
    db.refresh(conv)
    if is_new:
        _notify_match(db, conv, background)
        if target.is_bot:
            background.add_task(demo.bot_reply, conv.id, target.id, True)
    score, common = match_score(user.interests, user.goals, target.interests, target.goals)
    return {"match": True, "conversation_id": conv.id, "user": public_card(target, score, common)}


@notifications_router.get("")
def list_notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Notification).where(Notification.user_id == user.id).order_by(Notification.id.desc()).limit(50)
    ).all()
    return [
        {"id": n.id, "kind": n.kind, "payload": json.loads(n.payload), "read": n.read, "created_at": n.created_at.isoformat() + "Z"}
        for n in rows
    ]


@notifications_router.post("/read")
def read_notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    for n in db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.read.is_(False))):
        n.read = True
    db.commit()
    return {"status": "ok"}
