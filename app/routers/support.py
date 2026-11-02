"""Поддержка и помощник по рекламе.

Пользователь (или рекламодатель без аккаунта) пишет в чат, бот сразу отвечает,
оператор видит обращение в админ-панели и отвечает в реальном времени.
"""
from __future__ import annotations

import secrets
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import COOKIE_NAME, user_from_token
from ..models import SupportMessage, SupportThread, User, utcnow
from ..realtime import manager, notify
from ..security import hash_secret

router = APIRouter(prefix="/api/support", tags=["support"])
GUEST_COOKIE = "cofi_support"
CATEGORIES = {"help": "Помощь", "complaint": "Жалоба", "suggestion": "Предложение", "ads": "Реклама"}

ADS_GREETING = (
    "Здравствуйте! Я помощник COFI по рекламе. Расскажу о форматах, аудитории и условиях. "
    "Выберите вопрос ниже или напишите свой, а менеджер подключится к этому чату."
)
SUPPORT_GREETING = "Спасибо! Обращение №{id} принято. Оператор ответит прямо здесь, обычно в течение часа."
HANDOFF = "Передал ваш вопрос менеджеру. Ответ придёт в этот чат, а если оставите контакт, продублируем туда."


def _audience(db: Session) -> str:
    users = db.scalars(select(User).where(User.is_bot.is_(False), User.is_demo.is_(False), User.photo_verified.is_(True))).all()
    if not users:
        return "Мы только запускаемся: свежая аудитория, сейчас набираем первых пользователей."
    adults = sum(1 for u in users if u.age_group == "adult")
    top = Counter(i for u in users for i in u.interests).most_common(5)
    tops = ", ".join(f"{k} ({v})" for k, v in top) or "пока мало данных"
    return (f"Сейчас в COFI {len(users)} анкет с подтверждённым фото, из них {adults} старше 18 лет. "
            f"Популярные интересы: {tops}. Подростковая лента (14–17) для рекламы закрыта.")


def ads_answer(text: str, db: Session) -> str | None:
    t = text.lower()
    if any(w in t for w in ("формат", "размест", "вариант", "format", "placement")):
        return ("Форматы: 1) нативная карточка в ленте между анкетами, 2) баннер в списке чатов, "
                "3) спецпроект: ваш бренд в опросе интересов или в ленте «Животные» (благотворительные интеграции). "
                "Реклама показывается только взрослой аудитории.")
    if any(w in t for w in ("цен", "стоим", "бюджет", "сколько", "прайс", "price", "cost", "budget")):
        return ("Стоимость зависит от формата, гео и срока. Напишите бюджет и задачу, и менеджер пришлёт медиакит "
                "с ценами в течение рабочего дня.")
    if any(w in t for w in ("аудитор", "охват", "сколько пользоват", "статист", "audience", "reach", "stat")):
        return _audience(db)
    if any(w in t for w in ("заявк", "менеджер", "связ", "контакт", "звон", "request", "manager", "contact", "call")):
        return "Оставьте, пожалуйста, телефон, почту или Telegram и название компании. Менеджер свяжется с вами."
    return None


def _thread_out(t: SupportThread, db: Session, with_messages: bool = True) -> dict:
    out = {
        "id": t.id, "topic": t.topic, "category": t.category, "status": t.status, "contact": t.contact,
        "about_user_id": t.about_user_id, "created_at": t.created_at.isoformat() + "Z",
        "updated_at": t.updated_at.isoformat() + "Z",
        "user": {"id": t.user.id, "name": t.user.name, "email": t.user.email} if t.user else None,
    }
    if with_messages:
        msgs = db.scalars(select(SupportMessage).where(SupportMessage.thread_id == t.id).order_by(SupportMessage.id)).all()
        out["messages"] = [msg_out(m) for m in msgs]
    return out


def msg_out(m: SupportMessage) -> dict:
    return {"id": m.id, "thread_id": m.thread_id, "author": m.author, "text": m.text, "created_at": m.created_at.isoformat() + "Z"}


def _who(request: Request, db: Session) -> tuple[User | None, str | None]:
    user = user_from_token(db, request.cookies.get(COOKIE_NAME))
    guest = request.cookies.get(GUEST_COOKIE)
    return user, (hash_secret(guest) if guest else None)


def _owned(db: Session, thread_id: int, user: User | None, guest_hash: str | None) -> SupportThread:
    t = db.get(SupportThread, thread_id)
    if not t or not ((user and t.user_id == user.id) or (guest_hash and t.guest_token_hash == guest_hash)):
        raise HTTPException(404, "Обращение не найдено")
    return t


def _add(db: Session, t: SupportThread, author: str, text: str) -> SupportMessage:
    m = SupportMessage(thread_id=t.id, author=author, text=text)
    db.add(m)
    t.updated_at = utcnow()
    if author == "user" and t.status == "closed":
        t.status = "open"
    db.commit()
    db.refresh(m)
    payload = {"type": "support", "thread_id": t.id, "message": msg_out(m)}
    if t.user_id:
        notify(t.user_id, payload)
    if author == "user":
        for admin_id in db.scalars(select(User.id).where(User.is_admin.is_(True))):
            if manager.is_online(admin_id):
                notify(admin_id, {**payload, "admin": True})
    return m


class ThreadIn(BaseModel):
    topic: str = "support"
    category: str = "help"
    text: str = Field("", max_length=4000)
    contact: str = Field("", max_length=128)
    about_user_id: int | None = None


@router.post("/threads")
def create_thread(data: ThreadIn, request: Request, response: Response, db: Session = Depends(get_db)):
    user, guest_hash = _who(request, db)
    if data.topic not in ("support", "ads"):
        raise HTTPException(422, "Неизвестный раздел")
    if data.topic == "support" and not user:
        raise HTTPException(401, "Чтобы написать в поддержку, войдите в аккаунт")
    category = "ads" if data.topic == "ads" else (data.category if data.category in CATEGORIES else "help")
    if not user and not guest_hash:
        token = secrets.token_urlsafe(24)
        response.set_cookie(GUEST_COOKIE, token, max_age=180 * 86400, httponly=True, samesite="lax")
        guest_hash = hash_secret(token)
    t = SupportThread(topic=data.topic, category=category, user_id=user.id if user else None,
                      guest_token_hash=None if user else guest_hash, contact=data.contact.strip(),
                      about_user_id=data.about_user_id)
    db.add(t)
    db.commit()
    db.refresh(t)
    if data.topic == "ads":
        _add(db, t, "bot", ADS_GREETING)
    if data.text.strip():
        handle_user_message(db, t, data.text)
    elif data.topic == "support":
        _add(db, t, "bot", SUPPORT_GREETING.format(id=t.id))
    return _thread_out(t, db)


@router.get("/threads")
def my_threads(request: Request, db: Session = Depends(get_db)):
    user, guest_hash = _who(request, db)
    conds = []
    if user:
        conds.append(SupportThread.user_id == user.id)
    if guest_hash:
        conds.append(SupportThread.guest_token_hash == guest_hash)
    if not conds:
        return []
    from sqlalchemy import or_

    rows = db.scalars(select(SupportThread).where(or_(*conds)).order_by(SupportThread.updated_at.desc())).unique().all()
    return [_thread_out(t, db, with_messages=False) for t in rows]


@router.get("/threads/{thread_id}")
def get_thread(thread_id: int, request: Request, db: Session = Depends(get_db)):
    user, guest_hash = _who(request, db)
    return _thread_out(_owned(db, thread_id, user, guest_hash), db)


class MessageIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


@router.post("/threads/{thread_id}/messages")
def post_message(thread_id: int, data: MessageIn, request: Request, db: Session = Depends(get_db)):
    user, guest_hash = _who(request, db)
    return handle_user_message(db, _owned(db, thread_id, user, guest_hash), data.text)


def handle_user_message(db: Session, t: SupportThread, text: str) -> dict:
    m = _add(db, t, "user", text.strip())
    first = db.scalar(select(SupportMessage.id).where(SupportMessage.thread_id == t.id, SupportMessage.author == "user").order_by(SupportMessage.id)) == m.id
    if t.topic == "ads":
        answer = ads_answer(text, db)
        _add(db, t, "bot", answer or HANDOFF)
    elif first and not db.scalar(select(SupportMessage.id).where(SupportMessage.thread_id == t.id, SupportMessage.author == "bot")):
        _add(db, t, "bot", SUPPORT_GREETING.format(id=t.id))
    return msg_out(m)
