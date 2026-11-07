from __future__ import annotations

import json
from datetime import date, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import feed_index, push
from ..interests import GENDERS, INTERESTS, LOOKING_FOR, ORIENTATIONS
from ..database import get_db
from ..deps import admin_user, local_day
from ..models import ActivityDay, AnimalPost, AuthSession, Conversation, Message, SupportThread, Swipe, User, utcnow
from ..legal import TERMS_VERSION
from ..realtime import manager
from ..security import hash_password, is_valid_email, normalize_email, password_errors
from ..serializers import media_url, message_out, photo_url
from .profile import delete_user_completely

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None


def user_row(u: User) -> dict:
    return {
        "id": u.id,
        "name": u.name,
        "age": u.years,
        "birth_date": u.birth_date.isoformat() if u.birth_date else None,
        "age_group": u.age_group,
        "age_verified": u.age_verified,
        "email": u.email,
        "email_verified": u.email_verified,
        "telegram_id": u.telegram_id,
        "telegram_username": u.telegram_username,
        "auth_provider": u.auth_provider,
        "photo_url": photo_url(u),
        "photo_verified": u.photo_verified,
        "gender_label": GENDERS.get(u.gender or ""),
        "orientation_label": ORIENTATIONS.get(u.orientation or ""),
        "show_identity": u.show_identity,
        "show_orientation": u.show_orientation,
        "looking_for_label": LOOKING_FOR.get(u.looking_for or ""),
        "interests": u.interests,
        "goals": u.goals,
        "created_at": _iso(u.created_at),
        "last_seen_at": _iso(u.last_seen_at),
        "online": manager.is_online(u.id),
        "registration_ip": u.registration_ip,
        "registration_lat": u.registration_lat,
        "registration_lon": u.registration_lon,
        "consents": {"terms": _iso(u.terms_accepted_at), "terms_version": u.terms_version, "pd": _iso(u.consent_pd_at),
                     "bio": _iso(u.consent_bio_at), "sexuality": _iso(u.consent_sexuality_at), "ip": u.consent_ip},
        "is_admin": u.is_admin,
        "is_banned": u.is_banned,
        "is_demo": u.is_demo,
        "is_bot": u.is_bot,
    }


class BanIn(BaseModel):
    banned: bool


class BroadcastIn(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)


@router.get("/stats")
def stats(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    day_ago = utcnow() - timedelta(days=1)
    counts: dict[str, int] = {}
    for raw in db.scalars(select(User.interests_json)):
        for item in json.loads(raw or "[]"):
            counts[item] = counts.get(item, 0) + 1
    top = sorted(counts.items(), key=lambda x: -x[1])[:10]
    return {
        "users": db.scalar(select(func.count(User.id))) or 0,
        "verified": db.scalar(select(func.count(User.id)).where(User.photo_verified.is_(True))) or 0,
        "new_24h": db.scalar(select(func.count(User.id)).where(User.created_at >= day_ago)) or 0,
        "banned": db.scalar(select(func.count(User.id)).where(User.is_banned.is_(True))) or 0,
        "online": len(manager.connections),
        "matches": db.scalar(select(func.count(Conversation.id))) or 0,
        "messages": db.scalar(select(func.count(Message.id))) or 0,
        "top_interests": [{"name": k, "count": v} for k, v in top],
        "audience": _audience(db),
    }


def _audience(db: Session) -> dict:
    """Сколько настоящих людей (без ботов и гостей демо) зарегистрировано, в сети и заходило за периоды."""
    real = (User.is_bot.is_(False), User.is_demo.is_(False))
    today = local_day(utcnow())
    real_ids = select(User.id).where(*real)
    online_ids = [uid for uid in list(manager.connections) if manager.is_online(uid)]
    out = {
        "registered": db.scalar(select(func.count(User.id)).where(*real)) or 0,
        "online": db.scalar(select(func.count(User.id)).where(User.id.in_(online_ids), *real)) or 0 if online_ids else 0,
        "periods": [],
    }
    for key, label, days in (("day", "Сегодня", 1), ("week", "За 7 дней", 7), ("month", "За 30 дней", 30)):
        since = today - timedelta(days=days - 1)
        act = select(ActivityDay).where(ActivityDay.day >= since, ActivityDay.user_id.in_(real_ids)).subquery()
        out["periods"].append({
            "key": key, "label": label,
            "unique": db.scalar(select(func.count(func.distinct(act.c.user_id)))) or 0,
            "visits": db.scalar(select(func.coalesce(func.sum(act.c.visits), 0))) or 0,
            "new": db.scalar(select(func.count(User.id)).where(*real, User.created_at >= utcnow() - timedelta(days=days))) or 0,
        })
    return out


@router.get("/users")
def users(q: str = "", interest: str = "", page: int = 1, per_page: int = 30, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    query = select(User)
    if q:
        like = f"%{q.strip().lower()}%"
        conds = [func.lower(User.name).like(like), func.lower(User.email).like(like), func.lower(User.telegram_username).like(like)]
        if q.strip().isdigit():
            conds.append(User.id == int(q.strip()))
        query = query.where(or_(*conds))
    if interest in INTERESTS:
        query = query.where(User.interests_json.like(f'%"{interest}"%'))
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
        "selfie_url": f"/media/{u.selfie_path}" if u.selfie_path else None,
        "gallery": [media_url(p.path) for p in u.photos],
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
    feed_index.invalidate()
    return user_row(u)


@router.post("/users/{user_id}/reset-verification")
def reset_verification(user_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    u = _get_user(db, user_id)
    u.photo_verified = False
    u.photo_verified_at = None
    db.commit()
    feed_index.invalidate()
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
    """Новость всем через Telegram-бота. Почта используется только для кодов подтверждения."""
    if not push.enabled():
        raise HTTPException(503, "Telegram-бот не настроен: укажите TELEGRAM_BOT_TOKEN в .env")
    chats = db.scalars(select(User.telegram_id).where(
        User.telegram_id.is_not(None), User.tg_notifications.is_(True), User.is_banned.is_(False), User.is_bot.is_(False))).all()
    background.add_task(push.broadcast, list(chats), f"📣 {data.subject}\n\n{data.body}")
    return {"status": "queued", "recipients": len(chats)}


# ---------- Возраст ----------

class BirthIn(BaseModel):
    birth_date: date
    verified: bool = True


class AdminIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    email: str = ""
    password: str = ""
    telegram: str = ""  # @username или числовой id: если человек уже входил через Telegram


@router.post("/admins")
def add_admin(data: AdminIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Администратор без анкеты: только имя и значок «Администрация». Вход по почте и паролю или через Telegram."""
    tg = data.telegram.strip().lstrip("@")
    if tg:
        user = db.scalar(select(User).where(or_(func.lower(User.telegram_username) == tg.lower(),
                                                User.telegram_id == (int(tg) if tg.isdigit() else -1))))
        if not user:
            raise HTTPException(404, "Такой человек ещё не входил в COFI через Telegram. Пусть откроет бота и войдёт, потом повторите")
    else:
        email = normalize_email(data.email)
        if not is_valid_email(email):
            raise HTTPException(422, "Укажите почту или Telegram")
        if errors := password_errors(data.password):
            raise HTTPException(422, "; ".join(errors))
        user = db.scalar(select(User).where(User.email == email))
        if not user:
            user = User(email=email, auth_provider="email")
            db.add(user)
        user.password_hash = hash_password(data.password)
        user.email_verified = True
    user.name = data.name.strip()
    user.is_admin = True
    user.terms_accepted_at, user.terms_version = utcnow(), TERMS_VERSION
    db.commit()
    return user_row(user)


@router.post("/users/{user_id}/birth-date")
def set_birth_date(user_id: int, data: BirthIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Исправить дату рождения по обращению в поддержку и отметить, что возраст проверен по документу."""
    from ..ages import MIN_AGE, years_between

    u = _get_user(db, user_id)
    years = years_between(data.birth_date)
    if years < MIN_AGE or years > 100:
        raise HTTPException(422, f"Проверьте дату: получается {years} лет. COFI доступен с {MIN_AGE} лет")
    u.birth_date = data.birth_date
    u.age = years_between(data.birth_date)
    u.age_verified = data.verified
    db.commit()
    feed_index.invalidate()
    return user_row(u)


# ---------- Поддержка и реклама ----------

@router.get("/support")
def support_threads(topic: str = "", status: str = "", _: User = Depends(admin_user), db: Session = Depends(get_db)):
    from .support import _thread_out

    q = select(SupportThread)
    if topic in ("support", "ads"):
        q = q.where(SupportThread.topic == topic)
    if status in ("open", "closed"):
        q = q.where(SupportThread.status == status)
    rows = db.scalars(q.order_by(SupportThread.updated_at.desc()).limit(100)).unique().all()
    out = []
    for t in rows:
        item = _thread_out(t, db)
        item["last"] = item["messages"][-1] if item["messages"] else None
        item.pop("messages")
        out.append(item)
    return out


@router.get("/support/{thread_id}")
def support_thread(thread_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    from .support import _thread_out

    t = db.get(SupportThread, thread_id)
    if not t:
        raise HTTPException(404, "Обращение не найдено")
    return _thread_out(t, db)


class StaffReply(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@router.post("/support/{thread_id}/reply")
def support_reply(thread_id: int, data: StaffReply, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    from .support import _add, msg_out

    t = db.get(SupportThread, thread_id)
    if not t:
        raise HTTPException(404, "Обращение не найдено")
    return msg_out(_add(db, t, "staff", data.text.strip()))


class StatusIn(BaseModel):
    status: str


@router.post("/support/{thread_id}/status")
def support_status(thread_id: int, data: StatusIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    t = db.get(SupportThread, thread_id)
    if not t or data.status not in ("open", "closed"):
        raise HTTPException(404, "Обращение не найдено")
    t.status = data.status
    db.commit()
    return {"status": t.status}


# ---------- Животные ----------

@router.get("/animals")
def animals(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    from ..models import HelpRequest
    from .animals import CATEGORIES

    rows = db.scalars(select(AnimalPost).order_by(AnimalPost.id.desc()).limit(200)).unique().all()
    return [{
        "id": p.id, "category": CATEGORIES.get(p.category, p.category), "name": p.name, "contact": p.contact,
        "author": {"id": p.author.id, "name": p.author.name}, "active": p.active,
        "fundraising_open": p.fundraising_open if p.category == "charity" else None,
        "photos": [media_url(x) for x in p.photos], "created_at": _iso(p.created_at),
        "requests": db.scalar(select(func.count(HelpRequest.id)).where(HelpRequest.post_id == p.id)) or 0,
    } for p in rows]


@router.get("/help-requests")
def help_requests(status: str = "", _: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Заявки «Хочу помочь», отправленные через приложение: кто, по какому объявлению, контакт и сообщение."""
    from ..models import HelpRequest
    from .animals import CATEGORIES

    q = select(HelpRequest).order_by(HelpRequest.id.desc()).limit(300)
    if status in ("new", "done"):
        q = q.where(HelpRequest.status == status)
    out = []
    for r in db.scalars(q):
        post, user = db.get(AnimalPost, r.post_id), db.get(User, r.user_id)
        out.append({
            "id": r.id, "status": r.status, "message": r.message, "contact": r.contact, "delivered": r.delivered,
            "created_at": _iso(r.created_at),
            "post": {"id": post.id, "name": post.name, "category": CATEGORIES.get(post.category, post.category)} if post else None,
            "user": {"id": user.id, "name": user.name, "telegram_username": user.telegram_username, "email": user.email} if user else None,
        })
    return {"items": out, "new": db.scalar(select(func.count(HelpRequest.id)).where(HelpRequest.status == "new")) or 0}


@router.post("/help-requests/{request_id}/status")
def help_request_status(request_id: int, data: StatusIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    from ..models import HelpRequest

    r = db.get(HelpRequest, request_id)
    if not r or data.status not in ("new", "done"):
        raise HTTPException(404, "Заявка не найдена")
    r.status = data.status
    db.commit()
    return {"status": r.status}


@router.delete("/animals/{post_id}")
def delete_animal(post_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    from .. import storage

    p = db.get(AnimalPost, post_id)
    if not p:
        raise HTTPException(404, "Объявление не найдено")
    for x in p.photos:
        storage.delete_file(x)
    db.delete(p)
    db.commit()
    return {"status": "deleted"}
