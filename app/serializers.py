from __future__ import annotations

from .models import Conversation, Message, User


def media_url(path: str | None) -> str | None:
    """Файлы лежат у нас, а фото демо-ботов — по внешним ссылкам."""
    if not path:
        return None
    return path if path.startswith(("http://", "https://")) else f"/media/{path}"


def photo_url(user: User) -> str | None:
    return media_url(user.photo_path)


def own_profile(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "email_verified": user.email_verified,
        "email_notifications": user.email_notifications,
        "auth_provider": user.auth_provider,
        "telegram_username": user.telegram_username,
        "name": user.name,
        "age": user.age,
        "bio": user.bio,
        "gender": user.gender,
        "looking_for": user.looking_for,
        "interests": user.interests,
        "goals": user.goals,
        "survey_done": user.survey_done,
        "photo_url": photo_url(user),
        "photos": [{"id": p.id, "url": media_url(p.path)} for p in user.photos],
        "is_demo": user.is_demo,
        "photo_verified": user.photo_verified,
        "has_location": user.lat is not None,
        "max_distance_km": user.max_distance_km,
        "is_admin": user.is_admin,
        "is_complete": user.is_complete,
    }


def public_card(user: User, match: int, common: list[str], distance_km: float | None = None) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "age": user.age,
        "bio": user.bio,
        "photo_url": photo_url(user),
        "verified": user.photo_verified,
        "interests": user.interests,
        "goals": user.goals,
        "photos_count": len(user.photos),
        "match": match,
        "common": common,
        "distance_km": None if distance_km is None else round(distance_km, 1),
    }


def message_out(m: Message) -> dict:
    return {
        "id": m.id,
        "conversation_id": m.conversation_id,
        "sender_id": m.sender_id,
        "kind": m.kind,
        "text": m.text,
        "media_url": f"/media/{m.media_path}" if m.media_path else None,
        "duration": m.duration,
        "created_at": m.created_at.isoformat() + "Z",
        "read_at": m.read_at.isoformat() + "Z" if m.read_at else None,
    }


def conversation_out(c: Conversation, me_id: int, last: Message | None, unread: int, online: bool) -> dict:
    other = c.other(me_id)
    return {
        "id": c.id,
        "active": c.active,
        "user": {
            "id": other.id,
            "name": other.name,
            "age": other.age,
            "photo_url": photo_url(other),
            "online": online,
        },
        "last_message": message_out(last) if last else None,
        "unread": unread,
        "created_at": c.created_at.isoformat() + "Z",
    }
