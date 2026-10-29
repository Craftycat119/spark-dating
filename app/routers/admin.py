from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import emailer
from ..config import FEEDS
from ..database import get_db
from ..deps import admin_user
from ..models import AuthSession, Conversation, Match, Message, ProfileFeed, Swipe, User, utcnow
from ..realtime import manager
from ..serializers import message_out, photo_url
from .profile import delete_user_completely

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None


def user_row(u: User) -> dict:
    return {
        "id": u.id,
        "name": u.name,
        "age": u.age,
        "email": u.email,
        "email_verified": u.email_verified,
        "telegram_id": u.telegram_id,
        "telegram_username": u.telegram_username,
        "auth_provider": u.auth_provider,
        "photo_url": photo_url(u),
        "photo_verified": u.photo_verified,
        "feeds": u.active_feeds,
        "created_at": _iso(u.created_at),
        "last_seen_at": _iso(u.last_seen_at),
        "online": manager.is_online(u.id),
        "registration_ip": u.registration_ip,
        "registration_lat": u.registration_lat,
        "registration_lon": u.registration_lon,
        "is_admin": u.is_admin,
        "is_banned": u.is_banned,
    }


class BanIn(BaseModel):
    banned: bool


class BroadcastIn(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)


@router.get("/stats")
def stats(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    day_ago = utcnow() - timedelta(days=1)
    per_feed = {
        key: db.scalar(select(func.count(ProfileFeed.id)).where(ProfileFeed.feed == key, ProfileFeed.enabled.is_(True))) or 0
        for key in FEEDS
    }
    return {
        "users": db.scalar(select(func.count(User.id))) or 0,
        "verified": db.scalar(select(func.count(User.id)).where(User.photo_verified.is_(True))) or 0,
        "new_24h": db.scalar(select(func.count(User.id)).where(User.created_at >= day_ago)) or 0,
        "banned": db.scalar(select(func.count(User.id)).where(User.is_banned.is_(True))) or 0,
        "online": len(manager.connections),
        "matches": db.scalar(select(func.count(Match.id))) or 0,
        "messages": db.scalar(select(func.count(Message.id))) or 0,
        "per_feed": per_feed,
        "feed_titles": FEEDS,
    }


@router.get("/users")
def users(q: str = "", feed: str = "", page: int = 1, per_page: int = 30, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    query = select(User)
    if q:
        like = f"%{q.strip().lower()}%"
        conds = [func.lower(User.name).like(like), func.lower(User.email).like(like), func.lower(User.telegram_username).like(like)]
        if q.strip().isdigit():
            conds.append(User.id == int(q.strip()))
        query = query.where(or_(*conds))
    if feed in FEEDS:
        query = query.join(ProfileFeed).where(ProfileFeed.feed == feed, ProfileFeed.enabled.is_(True))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    per_page = max(1, min(per_page, 100))
    rows = db.scalars(query.order_by(User.id.desc()).offset((max(page, 1) - 1) * per_page).limit(per_page)).unique().all()
    return {"total": total, "page": page, "per_page": per_page, "items": [user_row(u) for u in rows]}


def _get_user(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Пользователь не найден")
    return u


@router.get("/users/{user_id}")
def user_detail(user_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    u = _get_user(db, user_id)
    convs = db.scalars(
        select(Conversation).where(or_(Conversation.user_a_id == u.id, Conversation.user_b_id == u.id))
    ).unique().all()
    sessions = db.scalars(select(AuthSession).where(AuthSession.user_id == u.id).order_by(AuthSession.id.desc()).limit(20)).all()
    return {
        **user_row(u),
        "bio": u.bio,
        "use_common_bio": u.use_common_bio,
        "feed_bios": {f.feed: {"enabled": f.enabled, "bio": f.bio} for f in u.feeds},
        "selfie_url": f"/media/{u.selfie_path}" if u.selfie_path else None,
        "face_score": u.face_score,
        "photo_verified_at": _iso(u.photo_verified_at),
        "registration_user_agent": u.registration_user_agent,
        "lat": u.lat,
        "lon": u.lon,
        "location_updated_at": _iso(u.location_updated_at),
        "likes_given": db.scalar(select(func.count(Swipe.id)).where(Swipe.from_user_id == u.id, Swipe.liked.is_(True))) or 0,
        "likes_received": db.scalar(select(func.count(Swipe.id)).where(Swipe.to_user_id == u.id, Swipe.liked.is_(True))) or 0,
        "sessions": [{"ip": s.ip, "created_at": _iso(s.created_at)} for s in sessions],
        "conversations": [_conv_row(db, c) for c in convs],
    }


def _conv_row(db: Session, c: Conversation) -> dict:
    return {
        "id": c.id,
        "active": c.active,
        "feeds": sorted({m.feed for m in c.matches}),
        "users": [{"id": x.id, "name": x.name, "photo_url": photo_url(x)} for x in (c.user_a, c.user_b)],
        "messages": db.scalar(select(func.count(Message.id)).where(Message.conversation_id == c.id)) or 0,
        "last_message_at": _iso(c.last_message_at),
        "created_at": _iso(c.created_at),
    }


@router.post("/users/{user_id}/ban")
def ban(user_id: int, data: BanIn, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    u = _get_user(db, user_id)
    if u.id == admin.id:
        raise HTTPException(400, "Нельзя заблокировать себя")
    u.is_banned = data.banned
    db.commit()
    return user_row(u)


@router.post("/users/{user_id}/reset-verification")
def reset_verification(user_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    u = _get_user(db, user_id)
    u.photo_verified = False
    u.photo_verified_at = None
    db.commit()
    return user_row(u)


@router.delete("/users/{user_id}")
def remove_user(user_id: int, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    u = _get_user(db, user_id)
    if u.id == admin.id:
        raise HTTPException(400, "Свою анкету удаляйте из настроек профиля")
    delete_user_completely(db, u)
    return {"status": "deleted"}


@router.get("/conversations")
def conversations(user_id: int | None = None, page: int = 1, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    q = select(Conversation)
    if user_id:
        q = q.where(or_(Conversation.user_a_id == user_id, Conversation.user_b_id == user_id))
    rows = db.scalars(
        q.order_by(Conversation.last_message_at.desc().nulls_last(), Conversation.id.desc()).offset((max(page, 1) - 1) * 50).limit(50)
    ).unique().all()
    return [_conv_row(db, c) for c in rows]


@router.get("/conversations/{conv_id}")
def conversation_messages(conv_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    c = db.get(Conversation, conv_id)
    if not c:
        raise HTTPException(404, "Чат не найден")
    msgs = db.scalars(select(Message).where(Message.conversation_id == c.id).order_by(Message.id)).all()
    return {**_conv_row(db, c), "items": [message_out(m) for m in msgs]}


@router.post("/broadcast")
def broadcast(data: BroadcastIn, background: BackgroundTasks, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    emails = db.scalars(
        select(User.email).where(
            User.email.is_not(None), User.email_verified.is_(True), User.email_notifications.is_(True), User.is_banned.is_(False)
        )
    ).all()

    def _send_all():
        for e in emails:
            emailer.send_broadcast(e, data.subject, data.body)

    background.add_task(_send_all)
    return {"status": "queued", "recipients": len(emails)}
