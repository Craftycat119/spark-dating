from __future__ import annotations

import base64
import logging
import shutil
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from .. import face_verify, feed_index, storage, telegram_bot
from ..config import settings
from ..database import get_db
from ..deps import client_ip, current_user
from ..ages import MIN_AGE, TEEN_GOALS, years_between
from ..legal import TERMS_VERSION
from ..interests import GENDERS, GOALS, INTERESTS, LOOKING_FOR, MIN_INTERESTS, ORIENTATIONS, ORIENTATIONS_BY_GENDER, TEEN_GENDERS, ZODIAC, clean
from ..models import AnimalPost, Conversation, Message, User, UserPhoto, utcnow
from ..ratelimit import hit
from ..serializers import own_profile

router = APIRouter(prefix="/api/profile", tags=["profile"])
log = logging.getLogger("spark.profile")

BIO_MAX = 500
MAX_GALLERY = 6


class ProfileIn(BaseModel):
    name: str | None = Field(None, max_length=64)
    birth_date: date | None = None
    bio: str | None = Field(None, max_length=BIO_MAX)
    gender: str | None = None
    orientation: str | None = None
    show_identity: bool | None = None
    show_orientation: bool | None = None
    height_cm: int | None = Field(None, ge=0, le=260)  # 0 — убрать
    weight_kg: int | None = Field(None, ge=0, le=300)
    zodiac: str | None = None
    extras_done: bool | None = None
    looking_for: str | None = None
    interests: list[str] | None = None
    goals: list[str] | None = None
    tg_notifications: bool | None = None
    max_distance_km: int | None = None
    language: str | None = None
    accept_terms: bool | None = None  # отметил «Принимаю Пользовательское соглашение»
    consent_pd: bool | None = None  # отдельное согласие на обработку персональных данных
    consent_sexuality: bool | None = None  # отдельное согласие на сведения о сексуальности
    confirm_age: bool | None = None  # отметил «Мне есть 18» (или «Родитель согласен» для 14–17 лет)


class FramesIn(BaseModel):
    frames: dict[str, str]
    consent: bool = False  # отметил согласие на обработку биометрических данных


class LocationIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


@router.get("")
def get_profile(user: User = Depends(current_user)):
    return own_profile(user)


@router.put("")
def update_profile(data: ProfileIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if data.name is not None:
        name = data.name.strip()
        if not name:
            raise HTTPException(422, "Укажите имя")
        user.name = name
    if data.birth_date is not None and data.birth_date != user.birth_date:
        if user.birth_date is not None:
            raise HTTPException(403, "Дату рождения можно изменить только через поддержку")
        years = years_between(data.birth_date)
        if years < MIN_AGE:
            raise HTTPException(422, f"COFI доступен с {MIN_AGE} лет")
        if years > 100:
            raise HTTPException(422, "Проверьте дату рождения")
        user.birth_date = data.birth_date
        user.age = years
        if user.age_group == "teen":
            # до 18 лет только дружба: убираем «свидания» и «серьёзные отношения»
            user.goals = [g for g in user.goals if g in TEEN_GOALS]
    if data.accept_terms is not None or data.confirm_age is not None:
        if not data.accept_terms:
            raise HTTPException(422, "Чтобы продолжить, примите Пользовательское соглашение")
        if not data.confirm_age:
            raise HTTPException(422, "Подтвердите возраст" if user.age_group == "adult" else "Нужно согласие родителя или законного представителя")
        if not data.consent_pd:
            raise HTTPException(422, "Чтобы продолжить, дайте согласие на обработку персональных данных")
        user.terms_accepted_at = user.consent_pd_at = utcnow()
        user.consent_ip = client_ip(request)
        user.terms_version = TERMS_VERSION
        user.age_confirmation = "adult" if user.age_group == "adult" else "guardian"
    if data.language in ("ru", "en"):
        user.language = data.language
    if data.bio is not None:
        user.bio = data.bio.strip()
    if data.gender is not None:
        if data.gender not in GENDERS:
            raise HTTPException(422, "Укажите пол")
        if data.gender not in TEEN_GENDERS and user.age_group == "teen":
            raise HTTPException(422, "В ленте «Дружба» можно выбрать «Парень» или «Девушка»")
        user.gender = data.gender
    if user.age_group == "teen" and user.gender not in (None, *TEEN_GENDERS):
        user.gender = None  # дату указали после пола: подросток выбирает пол заново
    if data.consent_sexuality:
        user.consent_sexuality_at = user.consent_sexuality_at or utcnow()
    if data.orientation is not None:
        if data.orientation and data.orientation != user.orientation and not user.consent_sexuality_at and user.age_group != "teen":
            raise HTTPException(422, "Чтобы указать сексуальность, дайте согласие на обработку этих сведений")
        if data.orientation and data.orientation not in ORIENTATIONS_BY_GENDER.get(user.gender or "", ORIENTATIONS):
            raise HTTPException(422, "Этот вариант сексуальности не подходит к выбранному полу")
        user.orientation = data.orientation or None
    if user.orientation and user.orientation not in ORIENTATIONS_BY_GENDER.get(user.gender or "", ORIENTATIONS):
        user.orientation = None  # сменили пол: «гей» / «лесби» могли перестать подходить
    if user.age_group == "teen":
        user.orientation = None  # до 18 лет сексуальность не спрашиваем и не храним
    if data.show_identity is not None:
        user.show_identity = data.show_identity
    if data.show_orientation is not None:
        user.show_orientation = data.show_orientation
    if data.height_cm is not None:
        if data.height_cm and not 100 <= data.height_cm <= 250:
            raise HTTPException(422, "Рост — от 100 до 250 см")
        user.height_cm = data.height_cm or None
    if data.weight_kg is not None:
        if data.weight_kg and not 30 <= data.weight_kg <= 250:
            raise HTTPException(422, "Вес — от 30 до 250 кг")
        user.weight_kg = data.weight_kg or None
    if user.age_group == "teen":
        user.weight_kg = None  # до 18 лет вес не спрашиваем и не показываем
    if data.zodiac is not None:
        if data.zodiac and data.zodiac not in ZODIAC:
            raise HTTPException(422, "Неизвестный знак зодиака")
        user.zodiac = data.zodiac or None
    if data.extras_done is not None:
        user.extras_done = data.extras_done
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
        if user.age_group == "teen" and any(g not in TEEN_GOALS for g in goals):
            raise HTTPException(422, "До 18 лет доступна только дружба")
        if not goals:
            raise HTTPException(422, "Выберите, что вы ищете")
        user.goals = goals
    if data.tg_notifications is not None:
        user.tg_notifications = data.tg_notifications
    if data.max_distance_km is not None:
        user.max_distance_km = max(1, min(data.max_distance_km, 20000))

    db.commit()
    feed_index.invalidate()  # лента увидит изменения сразу
    db.refresh(user)
    return own_profile(user)


@router.post("/telegram-link")
def telegram_link(user: User = Depends(current_user)):
    """Подключить уведомления в Telegram к аккаунту, созданному по почте."""
    if not settings.telegram_bot_token or not telegram_bot.bot_username():
        raise HTTPException(503, "Telegram-бот не настроен: администратору нужно указать TELEGRAM_BOT_TOKEN в .env")
    return {"url": telegram_bot.new_link(user.id)}


@router.post("/photo")
def upload_photo(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    hit(f"face:{user.id}", 20, 600)  # проверка лица нагружает процессор
    data = storage.read_limited(file, settings.max_image_mb)
    rel = storage.save_image(data, "photos")

    if not face_verify.is_dev_mode():
        try:
            img = face_verify.decode_image((settings.media_dir / rel).read_bytes())
            face_verify.check_profile_photo(face_verify.get_engine(), img)
        except face_verify.FaceError as exc:
            storage.delete_file(rel)
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — сломались модели или OpenCV: говорим понятно, детали в терминале
            storage.delete_file(rel)
            log.exception("Проверка фото не запустилась")
            raise HTTPException(500, "Проверка лица не запустилась, подробности в окне терминала с сервером") from exc

    storage.delete_file(user.photo_path)
    user.photo_path = rel
    # Новое фото — снова нужна проверка лицом
    user.photo_verified = False
    user.photo_verified_at = None
    user.face_score = None
    db.commit()
    feed_index.invalidate()  # лента увидит изменения сразу
    return own_profile(user)


@router.post("/photos")
def add_photo(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    if len(user.photos) >= MAX_GALLERY:
        raise HTTPException(400, f"Можно добавить не больше {MAX_GALLERY} фото")
    rel = storage.save_image(storage.read_limited(file, settings.max_image_mb), "gallery")
    user.photos.append(UserPhoto(path=rel))
    db.commit()
    db.refresh(user)
    return own_profile(user)


@router.delete("/photos/{photo_id}")
def delete_photo(photo_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    photo = next((p for p in user.photos if p.id == photo_id), None)
    if not photo:
        raise HTTPException(404, "Фото не найдено")
    storage.delete_file(photo.path)
    user.photos.remove(photo)
    db.commit()
    db.refresh(user)
    return own_profile(user)


@router.post("/verify-face")
def verify_face(data: FramesIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.photo_path:
        raise HTTPException(400, "Сначала загрузите фото")
    if data.consent and not user.consent_bio_at:
        user.consent_bio_at = utcnow()
    if not user.consent_bio_at:
        raise HTTPException(422, "Для проверки нужно согласие на обработку биометрических данных")
    hit(f"face:{user.id}", 20, 600)
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
    feed_index.invalidate()  # лента увидит изменения сразу
    return {"ok": result.ok, "score": round(result.score, 3), "reason": result.reason, "profile": own_profile(user)}


@router.post("/location")
def update_location(data: LocationIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.is_demo:
        return {"status": "ok"}  # демо всегда «в Москве», рядом с ботами
    user.lat, user.lon = data.lat, data.lon
    user.location_updated_at = utcnow()
    if user.registration_lat is None:
        user.registration_lat, user.registration_lon = data.lat, data.lon
    db.commit()
    feed_index.invalidate()  # лента увидит изменения сразу
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
    for post in db.scalars(select(AnimalPost).where(AnimalPost.author_id == user.id)):
        for path in post.photos:
            storage.delete_file(path)
    storage.delete_file(user.photo_path)
    storage.delete_file(user.selfie_path)
    for p in user.photos:
        storage.delete_file(p.path)
    db.delete(user)
    db.commit()
    feed_index.invalidate()  # лента увидит изменения сразу


@router.delete("")
def delete_account(user: User = Depends(current_user), db: Session = Depends(get_db)):
    delete_user_completely(db, user)
    return {"status": "deleted"}
