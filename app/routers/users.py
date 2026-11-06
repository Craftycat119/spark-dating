"""Подробная анкета другого человека."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import blocks
from ..database import get_db
from ..deps import current_user
from ..geo import public_distance_km
from ..interests import compatible, match_score
from ..models import Block, Conversation, Swipe, User
from ..realtime import manager, notify
from ..serializers import identity, media_url, photo_url
from .feed import audience, visible_users

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/{user_id}")
def user_profile(user_id: int, me: User = Depends(current_user), db: Session = Depends(get_db)):
    """Анкету видно, если человек мог бы попасть вам в ленту или у вас уже пара.
    Написать можно только при паре: тогда в ответе есть conversation_id."""
    if user_id == me.id:
        raise HTTPException(400, "Это ваша анкета")
    a, b = sorted((me.id, user_id))
    conv = db.scalar(
        select(Conversation).where(Conversation.user_a_id == a, Conversation.user_b_id == b, Conversation.active.is_(True))
    )
    other = db.scalar(audience(visible_users(), me).where(User.id == user_id))
    if conv is None:
        if not other or not me.is_complete:
            raise HTTPException(404, "Анкета не найдена")
        if not compatible(me.gender, me.looking_for, other.gender, other.looking_for):
            raise HTTPException(404, "Анкета не найдена")
    else:
        other = db.get(User, user_id)
        if not other or other.is_banned:
            raise HTTPException(404, "Анкета не найдена")
    if other.age_group != me.age_group:
        raise HTTPException(404, "Анкета не найдена")  # подростки и взрослые изолированы
    if blocks.between(db, me.id, other.id):
        raise HTTPException(404, "Анкета не найдена")  # чёрный список

    score, common = match_score(me.interests, me.goals, other.interests, other.goals)
    distance = None
    if me.lat is not None and other.lat is not None:
        distance = public_distance_km(me.lat, me.lon, other.lat, other.lon)
    liked = db.scalar(
        select(Swipe.liked).where(Swipe.from_user_id == me.id, Swipe.to_user_id == other.id)
    )
    return {
        "id": other.id,
        "name": other.name,
        "age": other.years,
        "bio": other.bio,
        "verified": other.photo_verified,
        "photos": [u for u in [photo_url(other)] if u] + [media_url(p.path) for p in other.photos],
        "interests": other.interests,
        "goals": other.goals,
        **identity(other),
        "common": common,
        "match": score,
        "distance_km": distance,
        "online": manager.is_online(other.id),
        "liked": bool(liked),
        "conversation_id": conv.id if conv else None,
    }


# ---------- Чёрный список ----------

@router.post("/{user_id}/block")
def block_user(user_id: int, me: User = Depends(current_user), db: Session = Depends(get_db)):
    """Заблокировать: человек больше не сможет писать, вы пропадёте из ленты и чатов друг друга."""
    if user_id == me.id:
        raise HTTPException(400, "Нельзя заблокировать себя")
    other = db.get(User, user_id)
    if not other:
        raise HTTPException(404, "Анкета не найдена")
    if not db.get(Block, (me.id, user_id)):
        db.add(Block(blocker_id=me.id, blocked_id=user_id))
        try:
            db.commit()
        except IntegrityError:  # двойное нажатие: блокировка уже есть
            db.rollback()
    a, b = sorted((me.id, user_id))
    conv = db.scalar(select(Conversation).where(Conversation.user_a_id == a, Conversation.user_b_id == b))
    if conv:
        notify(user_id, {"type": "unmatch", "conversation_id": conv.id})  # у собеседника чат пропадёт сразу
    return {"status": "blocked"}


@router.delete("/{user_id}/block")
def unblock_user(user_id: int, me: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.get(Block, (me.id, user_id))
    if row:
        db.delete(row)
        db.commit()
    return {"status": "unblocked"}


blocks_router = APIRouter(prefix="/api/blocks", tags=["blocks"])


@blocks_router.get("")
def my_blocks(me: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Block).where(Block.blocker_id == me.id).order_by(Block.created_at.desc())).all()
    people = {u.id: u for u in db.scalars(select(User).where(User.id.in_([r.blocked_id for r in rows])))}
    return [{"id": r.blocked_id, "name": people[r.blocked_id].name, "photo_url": photo_url(people[r.blocked_id])}
            for r in rows if r.blocked_id in people]
