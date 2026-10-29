from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import emailer
from ..config import FEEDS
from ..database import get_db
from ..deps import current_user
from ..geo import bounding_box, haversine_km
from ..models import Conversation, Match, Notification, ProfileFeed, Swipe, User, utcnow
from ..realtime import notify
from ..serializers import photo_url, public_card

router = APIRouter(prefix="/api/feed", tags=["feed"])
notifications_router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class SwipeIn(BaseModel):
    user_id: int
    like: bool


def _require_feed_access(user: User, feed: str) -> None:
    if feed not in FEEDS:
        raise HTTPException(404, "Такой ленты нет")
    if not user.is_complete:
        raise HTTPException(409, {"code": "profile_incomplete", "message": "Заполните анкету и подтвердите фото"})
    row = user.feed(feed)
    if not row or not row.enabled:
        raise HTTPException(409, {"code": "feed_disabled", "message": "Включите показ анкеты в этой ленте"})
    if user.lat is None:
        raise HTTPException(409, {"code": "need_location", "message": "Разрешите доступ к геопозиции"})


def _visible_in_feed(feed: str):
    return (
        select(User)
        .join(ProfileFeed, ProfileFeed.user_id == User.id)
        .where(
            ProfileFeed.feed == feed,
            ProfileFeed.enabled.is_(True),
            User.photo_verified.is_(True),
            User.is_banned.is_(False),
            User.lat.is_not(None),
            User.age.is_not(None),
            User.name != "",
        )
    )


@router.get("/{feed}")
def get_feed(feed: str, limit: int = 10, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _require_feed_access(user, feed)
    limit = max(1, min(limit, 30))

    swiped = select(Swipe.to_user_id).where(Swipe.from_user_id == user.id, Swipe.feed == feed)
    q = _visible_in_feed(feed).where(User.id != user.id, User.id.not_in(swiped))
    radius = user.max_distance_km
    if radius < 20000:
        lat_min, lat_max, lon_min, lon_max = bounding_box(user.lat, user.lon, radius)
        q = q.where(User.lat.between(lat_min, lat_max))
        if lon_min >= -180 and lon_max <= 180:
            q = q.where(User.lon.between(lon_min, lon_max))

    scored = []
    for other in db.scalars(q).unique():
        d = haversine_km(user.lat, user.lon, other.lat, other.lon)
        if d <= radius:
            scored.append((d, other))
    scored.sort(key=lambda x: x[0])
    return {"feed": feed, "cards": [public_card(o, feed, d) for d, o in scored[:limit]]}


def _notify_match(db: Session, conv: Conversation, feed: str, background: BackgroundTasks) -> None:
    for me, other in ((conv.user_a, conv.user_b), (conv.user_b, conv.user_a)):
        payload = {
            "conversation_id": conv.id,
            "feed": feed,
            "feed_title": FEEDS[feed],
            "user": {"id": other.id, "name": other.name, "photo_url": photo_url(other)},
        }
        db.add(Notification(user_id=me.id, kind="match", payload=json.dumps(payload, ensure_ascii=False)))
        notify(me.id, {"type": "match", **payload})
        if me.email and me.email_verified and me.email_notifications:
            background.add_task(emailer.send_match_email, me.email, other.name, FEEDS[feed])
    db.commit()


@router.post("/{feed}/swipe")
def swipe(feed: str, data: SwipeIn, background: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _require_feed_access(user, feed)
    if data.user_id == user.id:
        raise HTTPException(400, "Нельзя лайкнуть себя")
    target = db.scalar(_visible_in_feed(feed).where(User.id == data.user_id))
    if not target:
        raise HTTPException(404, "Анкета больше не доступна")

    existing = db.scalar(
        select(Swipe).where(Swipe.from_user_id == user.id, Swipe.to_user_id == target.id, Swipe.feed == feed)
    )
    if existing:
        existing.liked = data.like
        existing.created_at = utcnow()
    else:
        db.add(Swipe(from_user_id=user.id, to_user_id=target.id, feed=feed, liked=data.like))
    db.commit()

    if not data.like:
        return {"match": False}

    reverse = db.scalar(
        select(Swipe).where(
            Swipe.from_user_id == target.id, Swipe.to_user_id == user.id, Swipe.feed == feed, Swipe.liked.is_(True)
        )
    )
    if not reverse:
        return {"match": False}

    a, b = sorted((user.id, target.id))
    conv = db.scalar(select(Conversation).where(Conversation.user_a_id == a, Conversation.user_b_id == b))
    if not conv:
        conv = Conversation(user_a_id=a, user_b_id=b)
        db.add(conv)
        db.flush()
    conv.active = True
    is_new = not any(m.feed == feed for m in conv.matches)
    if is_new:
        conv.matches.append(Match(feed=feed))
    db.commit()
    db.refresh(conv)
    if is_new:
        _notify_match(db, conv, feed, background)
    return {"match": True, "conversation_id": conv.id, "user": public_card(target, feed)}


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
