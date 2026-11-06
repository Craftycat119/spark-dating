"""Лента «Питомцы»: помощь и сборы, передержка, поиск хозяина.

Объявления добавляет только администрация (через админ-панель). Смотреть ленту могут все.
Кнопка «Помочь» ведёт в Telegram автора или группы, а заявка уходит туда же через бота.
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .. import storage, telegram_notify
from ..config import settings
from ..database import get_db
from ..deps import current_user
from ..geo import haversine_km
from ..models import AnimalPost, HelpRequest, User
from ..ratelimit import hit
from ..serializers import media_url

router = APIRouter(prefix="/api/animals", tags=["animals"])

# Порядок важен: так идут вкладки и объявления в ленте «Все»
CATEGORIES = {"adoption": "Ищет хозяина", "foster": "Передержка", "charity": "Помощь и сборы"}
CATEGORY_ORDER = case({k: i for i, k in enumerate(CATEGORIES)}, value=AnimalPost.category, else_=len(CATEGORIES))
MAX_PHOTOS = 5


def post_out(p: AnimalPost, me: User) -> dict:
    distance = None
    if me.lat is not None and p.lat is not None:
        distance = round(haversine_km(me.lat, me.lon, p.lat, p.lon), 1)
    return {
        "id": p.id,
        "category": p.category,
        "name": p.name,
        "species": p.species,
        "age_text": p.age_text,
        "city": p.city,
        "description": p.description,
        "contact_url": telegram_notify.normalize_contact(p.contact),
        "fundraising_open": p.fundraising_open if p.category == "charity" else None,
        "fundraising_goal": p.fundraising_goal if p.category == "charity" else "",
        "photos": [media_url(x) for x in p.photos],
        "distance_km": distance,
        "author": {"id": p.author.id, "name": p.author.name},
        "is_mine": p.author_id == me.id,
        "created_at": p.created_at.isoformat() + "Z",
    }


@router.get("")
def list_posts(category: str = "", offset: int = 0, limit: int = 20, me: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(AnimalPost).where(AnimalPost.active.is_(True))
    if category in CATEGORIES:
        q = q.where(AnimalPost.category == category)
    rows = db.scalars(q.order_by(CATEGORY_ORDER, AnimalPost.id.desc()).offset(max(offset, 0)).limit(max(1, min(limit, 50)))).all()
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    return {"total": total, "items": [post_out(p, me) for p in rows], "categories": CATEGORIES}


def _require_adult(me: User) -> None:
    if me.age_group != "adult":
        raise HTTPException(403, "Отправлять заявки можно с 18 лет")


@router.get("/{post_id}")
def get_post(post_id: int, me: User = Depends(current_user), db: Session = Depends(get_db)):
    """Подробная карточка: всё из ленты плюс число откликов."""
    post = db.get(AnimalPost, post_id)
    if not post or (not post.active and post.author_id != me.id):
        raise HTTPException(404, "Объявление не найдено")
    out = post_out(post, me)
    out["help_count"] = db.scalar(select(func.count(HelpRequest.id)).where(HelpRequest.post_id == post.id)) or 0
    return out


@router.post("")
def create_post(
    category: str = Form(...),
    name: str = Form(..., max_length=64),
    contact: str = Form(..., max_length=128),
    species: str = Form("", max_length=32),
    age_text: str = Form("", max_length=32),
    city: str = Form("", max_length=64),
    description: str = Form("", max_length=3000),
    fundraising_goal: str = Form("", max_length=64),
    files: list[UploadFile] = File(default=[]),
    me: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not me.is_admin:
        raise HTTPException(403, "Объявления добавляет администрация COFI")
    if category not in CATEGORIES:
        raise HTTPException(422, "Выберите категорию")
    if not name.strip():
        raise HTTPException(422, "Укажите кличку или название")
    if not telegram_notify.normalize_contact(contact):
        raise HTTPException(422, "Укажите Telegram: @username или ссылку t.me/…")
    if len(files) > MAX_PHOTOS:
        raise HTTPException(422, f"Не больше {MAX_PHOTOS} фото")
    photos = [storage.save_image(storage.read_limited(f, settings.max_image_mb), "animals") for f in files]
    post = AnimalPost(
        author_id=me.id, category=category, name=name.strip(), contact=contact.strip(), species=species.strip(),
        age_text=age_text.strip(), city=city.strip(), description=description.strip(),
        fundraising_goal=fundraising_goal.strip(), lat=me.lat, lon=me.lon,
    )
    post.photos = photos
    db.add(post)
    db.commit()
    db.refresh(post)
    return post_out(post, me)


class PostPatch(BaseModel):
    fundraising_open: bool | None = None
    active: bool | None = None
    description: str | None = Field(None, max_length=3000)


def _own(db: Session, post_id: int, me: User) -> AnimalPost:
    post = db.get(AnimalPost, post_id)
    if not post or (post.author_id != me.id and not me.is_admin):
        raise HTTPException(404, "Объявление не найдено")
    return post


@router.patch("/{post_id}")
def update_post(post_id: int, data: PostPatch, me: User = Depends(current_user), db: Session = Depends(get_db)):
    """Автор открывает и закрывает сбор, снимает объявление с публикации."""
    post = _own(db, post_id, me)
    if data.fundraising_open is not None:
        if post.category != "charity":
            raise HTTPException(422, "Сбор бывает только в категории «Помощь и сборы»")
        post.fundraising_open = data.fundraising_open
    if data.active is not None:
        post.active = data.active
    if data.description is not None:
        post.description = data.description.strip()
    db.commit()
    return post_out(post, me)


@router.delete("/{post_id}")
def delete_post(post_id: int, me: User = Depends(current_user), db: Session = Depends(get_db)):
    post = _own(db, post_id, me)
    for p in post.photos:
        storage.delete_file(p)
    db.delete(post)
    db.commit()
    return {"status": "deleted"}


class HelpIn(BaseModel):
    message: str = Field("", max_length=1000)
    contact: str = Field("", max_length=128)


def _deliver(request_id: int, chat_ids: list, text: str) -> None:
    from ..database import SessionLocal

    delivered = any([telegram_notify.send_message(c, text) for c in chat_ids if c])
    with SessionLocal() as db:
        r = db.get(HelpRequest, request_id)
        if r:
            r.delivered = delivered
            db.commit()


@router.post("/{post_id}/help")
def help_post(post_id: int, data: HelpIn, background: BackgroundTasks, me: User = Depends(current_user), db: Session = Depends(get_db)):
    _require_adult(me)
    hit(f"help:{me.id}", 10, 3600)  # не больше 10 заявок в час от одного человека
    post = db.get(AnimalPost, post_id)
    if not post or not post.active:
        raise HTTPException(404, "Объявление не найдено")
    if post.category == "charity" and not post.fundraising_open:
        raise HTTPException(409, "Сбор уже закрыт, спасибо!")
    contact = data.contact.strip() or (f"@{me.telegram_username}" if me.telegram_username else (me.email or ""))
    req = HelpRequest(post_id=post.id, user_id=me.id, message=data.message.strip(), contact=contact)
    db.add(req)
    db.commit()
    text = (
        f"🐾 Заявка «Хочу помочь» в COFI\n"
        f"Объявление: {post.name} ({CATEGORIES[post.category]})\n"
        f"От: {me.name}, связь: {contact or 'не указана'}\n"
        f"{('Сообщение: ' + req.message) if req.message else ''}"
    ).strip()
    # Заявка уходит в общую группу волонтёров (если настроена) и автору, если он входил через Telegram
    targets = [settings.telegram_requests_chat_id, post.author.telegram_id]
    background.add_task(_deliver, req.id, targets, text)
    return {"status": "sent", "contact_url": telegram_notify.normalize_contact(post.contact)}
