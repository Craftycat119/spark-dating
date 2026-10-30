from __future__ import annotations

import logging
import shutil

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from .. import face_verify, storage
from ..config import settings
from ..database import get_db
from ..deps import current_user
from ..interests import GENDERS, GOALS, INTERESTS, LOOKING_FOR, MIN_INTERESTS, clean
from ..models import Conversation, Message, User, utcnow
from ..serializers import own_profile

router = APIRouter(prefix="/api/profile", tags=["profile"])
log = logging.getLogger("spark.profile")

BIO_MAX = 500


class ProfileIn(BaseModel):
    name: str | None = Field(None, max_length=64)
    age: int | None = None
    bio: str | None = Field(None, max_length=BIO_MAX)
    gender: str | None = None
    looking_for: str | None = None
    interests: list[str] | None = None
    goals: list[str] | None = None
    email_notifications: bool | None = None
    max_distance_km: int | None = None


class FramesIn(BaseModel):
    frames: dict[str, str]


class LocationIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


@router.get("")
def get_profile(user: User = Depends(current_user)):
    return own_profile(user)


@router.put("")
def update_profile(data: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if data.name is not None:
        name = data.name.strip()
        if not name:
            raise HTTPException(422, "Укажите имя")
        user.name = name
    if data.age is not None:
        if not 18 <= data.age <= 100:
            raise HTTPException(422, "Приложение доступно только с 18 лет")
        user.age = data.age
    if data.bio is not None:
        user.bio = data.bio.strip()
    if data.gender is not None:
        if data.gender not in GENDERS:
            raise HTTPException(422, "Укажите пол")
        user.gender = data.gender
    if data.looking_for is not None:
        if data.looking_for not in LOOKING_FOR:
            raise HTTPException(422, "Укажите, кого ищете")
        user.looking_for = data.looking_for
    if data.interests is not None:
        interests = clean(data.interests, INTERESTS)
        if len(interests) < MIN_INTERESTS:
            raise HTTPException(422, f"Выберите хотя бы {MIN_INTERESTS} интереса")
        user.interests = interests
    if data.goals is not None:
        goals = clean(data.goals, GOALS)
        if not goals:
            raise HTTPException(422, "Выберите, что вы ищете")
        user.goals = goals
    if data.email_notifications is not None:
        user.email_notifications = data.email_notifications
    if data.max_distance_km is not None:
        user.max_distance_km = max(1, min(data.max_distance_km, 20000))

    db.commit()
    db.refresh(user)
    return own_profile(user)


@router.post("/photo")
def upload_photo(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = storage.read_limited(file, settings.max_image_mb)
    rel = storage.save_image(data, "photos")

    if not face_verify.is_dev_mode():
        try:
            img = face_verify.decode_image((settings.media_dir / rel).read_bytes())
            face_verify.check_profile_photo(face_verify.get_engine(), img)
        except face_verify.FaceError as exc:
            storage.delete_file(rel)
            raise HTTPException(400, str(exc)) from exc

    storage.delete_file(user.photo_path)
    user.photo_path = rel
    # Новое фото — снова нужна проверка лицом
    user.photo_verified = False
    user.photo_verified_at = None
    user.face_score = None
    db.commit()
    return own_profile(user)


@router.post("/verify-face")
def verify_face(data: FramesIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.photo_path:
        raise HTTPException(400, "Сначала загрузите фото")
    if len(data.frames) > 6 or any(len(v) > 3_000_000 for v in data.frames.values()):
        raise HTTPException(413, "Слишком большие кадры")

    if face_verify.is_dev_mode():
        result = face_verify.VerifyResult(True, 1.0)
    else:
        try:
            photo = face_verify.decode_image((settings.media_dir / user.photo_path).read_bytes())
            frames = {k: face_verify.decode_image(v) for k, v in data.frames.items()}
        except face_verify.FaceError as exc:
            return {"ok": False, "score": 0, "reason": str(exc)}
        result = face_verify.verify_frames(face_verify.get_engine(), photo, frames)

    if result.ok:
        center = data.frames.get("center")
        if center:
            import base64

            try:
                raw = base64.b64decode(center.split(",", 1)[-1])
                storage.delete_file(user.selfie_path)
                user.selfie_path = storage.save_image(raw, "selfies", max_side=800)
            except Exception:  # noqa: BLE001 — кадр для админки не критичен
                log.warning("Не удалось сохранить кадр сканера")
        user.photo_verified = True
        user.photo_verified_at = utcnow()
        user.face_score = result.score
        db.commit()
    return {"ok": result.ok, "score": round(result.score, 3), "reason": result.reason, "profile": own_profile(user)}


@router.post("/location")
def update_location(data: LocationIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.lat, user.lon = data.lat, data.lon
    user.location_updated_at = utcnow()
    if user.registration_lat is None:
        user.registration_lat, user.registration_lon = data.lat, data.lon
    db.commit()
    return {"status": "ok"}


def delete_user_completely(db: Session, user: User) -> None:
    """Полное удаление анкеты со всеми файлами, чатами и лайками."""
    convs = db.scalars(
        select(Conversation).where(or_(Conversation.user_a_id == user.id, Conversation.user_b_id == user.id))
    ).all()
    for c in convs:
        for m in db.scalars(select(Message).where(Message.conversation_id == c.id, Message.media_path.is_not(None))):
            storage.delete_file(m.media_path)
        db.execute(delete(Message).where(Message.conversation_id == c.id))
        chat_dir = settings.media_dir / "chat" / str(c.id)
        if chat_dir.exists():
            shutil.rmtree(chat_dir, ignore_errors=True)
        db.delete(c)
    storage.delete_file(user.photo_path)
    storage.delete_file(user.selfie_path)
    db.delete(user)
    db.commit()


@router.delete("")
def delete_account(user: User = Depends(current_user), db: Session = Depends(get_db)):
    delete_user_completely(db, user)
    return {"status": "deleted"}
