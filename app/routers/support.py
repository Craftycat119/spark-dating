"""Поддержка и помощник по рекламе.

Пользователь (или рекламодатель без аккаунта) пишет в чат, бот сразу отвечает,
оператор видит обращение в админ-панели и отвечает в реальном времени.
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import COOKIE_NAME, user_from_token
from .. import push
from ..ratelimit import by_ip
from ..models import SupportMessage, SupportThread, User, utcnow
from ..realtime import manager, notify
from ..security import hash_secret

router = APIRouter(prefix="/api/support", tags=["support"])
GUEST_COOKIE = "cofi_support"
CATEGORIES = {"help": "Помощь", "complaint": "Жалоба", "suggestion": "Предложение", "ads": "Реклама"}

ADS_EMAIL = "craftycat119@mail.ru"
ADS_GREETING = (
    "Здравствуйте! Это раздел для рекламодателей и партнёров COFI. Расскажите о компании и задаче и оставьте контакт "
    f"(телефон, почту или Telegram) — менеджер ответит в этом чате. Почта для рекламодателей: {ADS_EMAIL}."
)
ADS_MANAGER_WILL_ANSWER = "С вами свяжется менеджер и ответит на все интересующие вопросы, в том числе об аудитории COFI."
ADS_ACCEPTED = ("Спасибо! Заявка №{id} принята. Менеджер изучит её и свяжется с вами — ответ придёт в этот чат "
                "и на контакт, если вы его оставили.")
# Сначала бот здоровается и просит описать суть, а «принято» пишет только после сообщения пользователя
GREETINGS = {
    "help": "Здравствуйте! Это поддержка COFI. Опишите, пожалуйста, ваш вопрос: что случилось и на каком экране. Можно приложить скриншот — кнопка с картинкой слева от поля.",
    "complaint": "Здравствуйте! Расскажите, на кого или на что вы хотите пожаловаться и что произошло. Если это анкета, укажите имя. Скриншот поможет разобраться быстрее — кнопка с картинкой слева от поля.",
    "suggestion": "Здравствуйте! Спасибо, что помогаете сделать COFI лучше. Напишите вашу идею или предложение.",
}
REPORT_GREETING = "Здравствуйте! Вы жалуетесь на анкету «{name}». Расскажите, пожалуйста, что произошло. Можно приложить скриншот переписки."
SUPPORT_GREETING = "Спасибо! Обращение №{id} принято. Оператор ответит прямо здесь, обычно в течение часа."


def ads_answer(text: str, db: Session) -> str | None:
    t = text.lower()
    # аудитория — первой: «Сколько пользователей?» иначе ушло бы в ответ про цену («сколько»)
    if any(w in t for w in ("аудитор", "охват", "сколько пользоват", "статист", "audience", "reach", "stat")):
        return ADS_MANAGER_WILL_ANSWER
    if any(w in t for w in ("формат", "размест", "вариант", "рассылк", "format", "placement", "newsletter", "broadcast")):
        return ("Форматы: 1) нативная карточка в ленте между анкетами, 2) баннер в списке чатов, "
                "3) рассылка через Telegram-бота COFI, 4) спецпроекты с лентой «Питомцы». "
                "Менеджер подберёт подходящий под вашу задачу.")
    if any(w in t for w in ("цен", "стоим", "бюджет", "сколько", "прайс", "price", "cost", "budget")):
        return ("Стоимость зависит от формата и срока размещения. Оставьте контакт и задачу — "
                "менеджер подготовит предложение.")
    if any(w in t for w in ("заявк", "менеджер", "связ", "контакт", "звон", "request", "manager", "contact", "call")):
        return (f"Почта для рекламодателей: {ADS_EMAIL}. Или оставьте здесь телефон, почту или Telegram "
                "и название компании, менеджер свяжется с вами.")
    return None


def _thread_out(t: SupportThread, db: Session, with_messages: bool = True) -> dict:
    out = {
        "id": t.id, "topic": t.topic, "category": t.category, "status": t.status, "contact": t.contact,
        "about_user_id": t.about_user_id, "created_at": t.created_at.isoformat() + "Z",
        "updated_at": t.updated_at.isoformat() + "Z",
        "user": {"id": t.user.id, "name": t.user.name, "email": t.user.email,
                 "telegram_username": t.user.telegram_username, "telegram_id": t.user.telegram_id} if t.user else None,
    }
    if with_messages:
        msgs = db.scalars(select(SupportMessage).where(SupportMessage.thread_id == t.id).order_by(SupportMessage.id)).all()
        out["messages"] = [msg_out(m) for m in msgs]
    return out


def msg_out(m: SupportMessage) -> dict:
    return {"id": m.id, "thread_id": m.thread_id, "author": m.author, "text": m.text, "created_at": m.created_at.isoformat() + "Z",
            "image_url": f"/api/support/threads/{m.thread_id}/images/{m.image_name}" if m.image_name else None}


def images_dir(thread_id: int):
    return settings.media_dir / "support" / str(thread_id)


def _who(request: Request, db: Session) -> tuple[User | None, str | None]:
    user = user_from_token(db, request.cookies.get(COOKIE_NAME))
    guest = request.cookies.get(GUEST_COOKIE)
    return user, (hash_secret(guest) if guest else None)


def _owned(db: Session, thread_id: int, user: User | None, guest_hash: str | None) -> SupportThread:
    t = db.get(SupportThread, thread_id)
    if not t or not ((user and t.user_id == user.id) or (guest_hash and t.guest_token_hash == guest_hash)):
        raise HTTPException(404, "Обращение не найдено")
    return t


# Статусы обращения: новое → в работе → ответ отправлен → решено / закрыто без ответа
STATUSES = {"open": "Новое", "in_work": "В работе", "answered": "Ответ отправлен", "closed": "Решено", "noreply": "Закрыто без ответа"}
ACTIVE = ("open", "in_work", "answered")  # переписка продолжается — новое сообщение человека идёт сюда же
DONE = ("closed", "noreply")


def _add(db: Session, t: SupportThread, author: str, text: str, image_name: str | None = None) -> SupportMessage:
    m = SupportMessage(thread_id=t.id, author=author, text=text, image_name=image_name)
    db.add(m)
    t.updated_at = utcnow()
    if author == "user" and t.status != "in_work":
        t.status = "open"  # человек написал снова — обращение снова ждёт ответа
    elif author == "staff":
        t.status = "answered"
    db.commit()
    db.refresh(m)
    payload = {"type": "support", "thread_id": t.id, "message": msg_out(m)}
    if author == "staff":
        from ..telegram_support import deliver_staff_reply

        deliver_staff_reply(t, text)
    if t.user_id:
        notify(t.user_id, payload)
    if author == "user":
        for admin_id in db.scalars(select(User.id).where(User.is_admin.is_(True))):
            if manager.is_online(admin_id):
                notify(admin_id, {**payload, "admin": True})
        if image_name:  # скриншот — картинкой в Telegram, а не «посмотрите в админ-панели»
            push.notify_admins_photo(db, t, str(images_dir(t.id) / image_name))
        else:
            push.notify_admins(db, t, text)
    return m


class ThreadIn(BaseModel):
    topic: str = "support"
    category: str = "help"
    text: str = Field("", max_length=4000)
    contact: str = Field("", max_length=128)
    about_user_id: int | None = None


@router.post("/threads")
def create_thread(data: ThreadIn, request: Request, response: Response, db: Session = Depends(get_db)):
    by_ip(request, "support-new", 20, 3600)
    user, guest_hash = _who(request, db)
    if data.topic not in ("support", "ads"):
        raise HTTPException(422, "Неизвестный раздел")
    if data.topic == "support" and not user:
        # без аккаунта (например, не получается войти) — можно, но нужен контакт, куда ответить
        if len(data.contact.strip()) < 3:
            raise HTTPException(422, "Укажите почту или Telegram — туда придёт ответ")
        if not data.text.strip():
            raise HTTPException(422, "Опишите, что случилось")
    category = "ads" if data.topic == "ads" else (data.category if data.category in CATEGORIES else "help")
    about = db.get(User, data.about_user_id) if data.about_user_id and user else None
    if about and (about.id == user.id or about.age_group != user.age_group):
        about = None  # жаловаться можно только на тех, кого человек мог видеть
    if not user and not guest_hash:
        token = secrets.token_urlsafe(24)
        response.set_cookie(GUEST_COOKIE, token, max_age=180 * 86400, httponly=True, samesite="lax",
                            secure=settings.cookie_secure or request.url.scheme == "https")
        guest_hash = hash_secret(token)
    t = SupportThread(topic=data.topic, category=category, user_id=user.id if user else None,
                      guest_token_hash=None if user else guest_hash, contact=data.contact.strip(),
                      about_user_id=about.id if about else None)
    db.add(t)
    db.commit()
    db.refresh(t)
    if data.topic == "ads":
        _add(db, t, "bot", ADS_GREETING)
    if data.text.strip():
        handle_user_message(db, t, data.text)
    elif data.topic == "support":
        _add(db, t, "bot", REPORT_GREETING.format(name=about.name) if about else GREETINGS[category])
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


MAX_SCREENSHOT_MB = 15
_IMAGE_NAME = __import__("re").compile(r"[0-9a-f]{32}\.jpg")


@router.post("/threads/{thread_id}/images")
def post_image(thread_id: int, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Скриншот к обращению: пересохраняем в JPEG без метаданных (в том числе координат), не больше 2000 px."""
    from ..storage import read_limited

    by_ip(request, "support-img", 30, 600)
    user, guest_hash = _who(request, db)
    t = _owned(db, thread_id, user, guest_hash)
    return msg_out(add_screenshot(db, t, read_limited(file, MAX_SCREENSHOT_MB)))


def add_screenshot(db: Session, t: SupportThread, raw: bytes) -> SupportMessage:
    """Сохранить картинку в обращение (с сайта или из Telegram) и показать её оператору."""
    import io
    import uuid

    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        pic = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(400, "Это не картинка. Пришлите скриншот или фото") from exc
    pic.thumbnail((2000, 2000))
    name = f"{uuid.uuid4().hex}.jpg"
    folder = images_dir(t.id)
    folder.mkdir(parents=True, exist_ok=True)
    pic.save(folder / name, "JPEG", quality=85)
    return _add(db, t, "user", "", image_name=name)


@router.get("/threads/{thread_id}/images/{name}")
def get_image(thread_id: int, name: str, request: Request, db: Session = Depends(get_db)):
    """Скриншот видят только автор обращения и администрация."""
    if not _IMAGE_NAME.fullmatch(name):
        raise HTTPException(404)
    user, guest_hash = _who(request, db)
    if not (user and user.is_admin):
        _owned(db, thread_id, user, guest_hash)
    path = images_dir(thread_id) / name
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


class MessageIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


@router.post("/threads/{thread_id}/messages")
def post_message(thread_id: int, data: MessageIn, request: Request, db: Session = Depends(get_db)):
    by_ip(request, "support-msg", 60, 600)
    user, guest_hash = _who(request, db)
    return handle_user_message(db, _owned(db, thread_id, user, guest_hash), data.text)


def handle_user_message(db: Session, t: SupportThread, text: str, greet: bool = True) -> dict:
    m = _add(db, t, "user", text.strip())
    first = db.scalar(select(SupportMessage.id).where(SupportMessage.thread_id == t.id, SupportMessage.author == "user").order_by(SupportMessage.id)) == m.id
    if t.topic == "ads":
        # первое сообщение — «заявка принята»; дальше бот отвечает только на понятные вопросы, остальное — менеджеру
        if first:
            _add(db, t, "bot", ADS_ACCEPTED.format(id=t.id))
        answer = ads_answer(text, db)
        if answer:
            _add(db, t, "bot", answer)
    elif first and greet:
        _add(db, t, "bot", SUPPORT_GREETING.format(id=t.id))
    return msg_out(m)
