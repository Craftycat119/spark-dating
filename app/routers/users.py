"""Подробная анкета другого человека."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user
from ..geo import haversine_km
from ..interests import compatible, match_score
from ..models import Conversation, Swipe, User
from ..realtime import manager
from ..serializers import photo_url
from .feed import visible_users

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
    other = db.scalar(visible_users().where(User.id == user_id))
    if conv is None:
        if not other or not me.is_complete or not compatible(me.gender, me.looking_for, other.gender, other.looking_for):
            raise HTTPException(404, "Анкета не найдена")
    else:
        other = db.get(User, user_id)
        if not other or other.is_banned:
            raise HTTPException(404, "Анкета не найдена")

    score, common = match_score(me.interests, me.goals, other.interests, other.goals)
    distance = None
    if me.lat is not None and other.lat is not None:
        distance = round(haversine_km(me.lat, me.lon, other.lat, other.lon), 1)
    liked = db.scalar(
        select(Swipe.liked).where(Swipe.from_user_id == me.id, Swipe.to_user_id == other.id)
    )
    return {
        "id": other.id,
        "name": other.name,
        "age": other.age,
        "bio": other.bio,
        "verified": other.photo_verified,
        "photos": [u for u in [photo_url(other)] if u] + [f"/media/{p.path}" for p in other.photos],
        "interests": other.interests,
        "goals": other.goals,
        "common": common,
        "match": score,
        "distance_km": distance,
        "online": manager.is_online(other.id),
        "liked": bool(liked),
        "conversation_id": conv.id if conv else None,
    }
