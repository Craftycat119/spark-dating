from __future__ import annotations

from . import storage
from .config import settings
from .interests import GENDERS, ORIENTATIONS, ZODIAC
from .legal import TERMS_VERSION
from .models import Conversation, Message, User


def _poster(m) -> str | None:
    if m.kind not in ("video", "circle") or not m.media_path:
        return None
    rel = storage.poster_rel(m.media_path)
    return f"/media/{rel}" if (settings.media_dir / rel).exists() else None


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
        "tg_notifications": user.tg_notifications,
        "telegram_linked": bool(user.telegram_id),
        "auth_provider": user.auth_provider,
        "telegram_username": user.telegram_username,
        "name": user.name,
        "age": user.years,
        "birth_date": user.birth_date.isoformat() if user.birth_date else None,
        "age_group": user.age_group,
        "age_verified": user.age_verified,
        "terms_accepted": bool(user.terms_accepted_at) and user.terms_version == TERMS_VERSION,
        "age_confirmation": user.age_confirmation,
        "consent_bio": bool(user.consent_bio_at),
        "consent_sexuality": bool(user.consent_sexuality_at),
        "language": user.language,
        "bio": user.bio,
        "gender": user.gender,
        "orientation": user.orientation,
        "show_identity": user.show_identity,
        "show_orientation": user.show_orientation,
        "height_cm": user.height_cm,
        "weight_kg": user.weight_kg,
        "zodiac": user.zodiac,
        "extras_done": user.extras_done,
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
        "city_name": user.city,
        "show_city": user.show_city is not False,
        "is_admin": user.is_admin,
        "is_complete": user.is_complete,
    }


def identity(user: User) -> dict:
    """Пол и ориентация для чужих глаз — только если человек разрешил их показывать."""
    return {
        "gender_label": GENDERS.get(user.gender) if user.show_identity else None,
        "orientation_label": ORIENTATIONS.get(user.orientation) if user.show_orientation else None,
        "height_cm": user.height_cm,
        "weight_kg": user.weight_kg,
        "zodiac_label": ZODIAC.get(user.zodiac),
        "city": user.city if user.show_city is not False else None,
    }


def public_card(user: User, match: int, common: list[str], distance_km: float | None = None) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "age": user.years,
        "bio": user.bio,
        "photo_url": photo_url(user),
        "verified": user.photo_verified,
        "interests": user.interests,
        "goals": user.goals,
        "photos_count": len(user.photos),
        **identity(user),
        "match": match,
        "common": common,
        "distance_km": None if distance_km is None else max(1, round(distance_km)),
    }


PREVIEW = {"image": "📷 Фото", "video": "🎬 Видео", "voice": "🎤 Голосовое", "circle": "⭕ Кружок", "sticker": "Стикер", "call": "Звонок"}


def message_preview(m: Message | None) -> dict | None:
    """Коротко о сообщении — для цитаты в ответе и плашки «Закреплено»."""
    if m is None:
        return None
    text = m.text if m.kind == "text" else (m.text if m.kind == "sticker" else PREVIEW.get(m.kind, ""))
    return {"id": m.id, "sender_id": m.sender_id, "kind": m.kind, "text": (text or "")[:140]}


def message_out(m: Message) -> dict:
    reply = None
    if m.reply_to_id:
        from sqlalchemy.orm import object_session

        db = object_session(m)
        target = db.get(Message, m.reply_to_id) if db else None
        reply = message_preview(target) if target and target.conversation_id == m.conversation_id else None
    return {
        "id": m.id,
        "conversation_id": m.conversation_id,
        "sender_id": m.sender_id,
        "kind": m.kind,
        "text": m.text,
        "media_url": f"/media/{m.media_path}" if m.media_path else None,
        "poster_url": _poster(m),
        "duration": m.duration,
        "created_at": m.created_at.isoformat() + "Z",
        "read_at": m.read_at.isoformat() + "Z" if m.read_at else None,
        "reply_to": reply,
        "edited": bool(m.edited_at),
    }


def conversation_out(c: Conversation, me_id: int, last: Message | None, unread: int, online: bool) -> dict:
    other = c.other(me_id)
    return {
        "id": c.id,
        "active": c.active,
        "user": {
            "id": other.id,
            "name": other.name,
            "age": other.years,
            "photo_url": photo_url(other),
            "online": online,
        },
        "last_message": message_out(last) if last else None,
        "unread": unread,
        "created_at": c.created_at.isoformat() + "Z",
    }
