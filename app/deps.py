from __future__ import annotations

from datetime import date, timedelta

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import ActivityDay, AuthSession, User, utcnow
from .security import hash_secret, new_session_token

COOKIE_NAME = "spark_session"


def client_ip(request: Request) -> str:
    """Адрес клиента. X-Forwarded-For сам по себе не читаем: его может подставить кто угодно.
    uvicorn (proxy_headers) берёт адрес из заголовка, только если запрос пришёл от прокси на этом же компьютере (cloudflared, nginx)."""
    return request.client.host if request.client else ""


def start_session(db: Session, user: User, request: Request, response: Response, embedded: bool = False) -> None:
    """embedded=True — вход из мини-приложения. В веб-версии Telegram оно работает во встроенном окне чужого сайта
    (web.telegram.org), и обычная cookie (SameSite=Lax) туда не передаётся: человек сразу «выходит».
    Поэтому там cookie выдаётся как SameSite=None + Partitioned: она живёт только внутри этого окна Telegram
    и не уходит на запросы с других сайтов (от подделки запросов дополнительно защищает проверка Origin в main.py)."""
    token = new_session_token()
    db.add(
        AuthSession(
            token_hash=hash_secret(token),
            user_id=user.id,
            expires_at=utcnow() + timedelta(days=settings.session_days),
            ip=client_ip(request),
        )
    )
    now = utcnow()
    if not user.last_seen_at or (now - user.last_seen_at).total_seconds() > VISIT_GAP or local_day(user.last_seen_at) != local_day(now):
        _count_visit(db, user.id, local_day(now))  # вход в аккаунт — тоже посещение
    user.last_seen_at = now
    db.commit()
    secure = settings.cookie_secure or request.url.scheme == "https"
    max_age = settings.session_days * 86400
    if embedded and secure:
        # Partitioned Starlette ставит только на Python 3.14+, поэтому заголовок собираем сами
        response.headers.append("set-cookie", f"{COOKIE_NAME}={token}; Max-Age={max_age}; Path=/; HttpOnly; Secure; SameSite=None; Partitioned")
        return
    # по https cookie входа уходит только по шифрованному каналу (в том числе через туннель cloudflared)
    response.set_cookie(COOKIE_NAME, token, max_age=max_age, httponly=True, secure=secure, samesite="lax")


def user_from_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    sess = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_secret(token)))
    if not sess or sess.expires_at < utcnow():
        return None
    user = sess.user
    if user.is_banned:
        return None
    return user


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = user_from_token(db, request.cookies.get(COOKIE_NAME))
    if not user:
        raise HTTPException(401, "Нужно войти в аккаунт")
    now = utcnow()
    gap = (now - user.last_seen_at).total_seconds() if user.last_seen_at else None
    if gap is None or gap > 60:
        today = local_day(now)
        if gap is None or gap > VISIT_GAP or local_day(user.last_seen_at) != today:
            _count_visit(db, user.id, today)
        user.last_seen_at = now
        db.commit()
    return user


VISIT_GAP = 30 * 60  # вернулся после 30 минут тишины — новое посещение


def local_day(dt) -> date:
    return (dt + timedelta(hours=settings.stats_tz_hours)).date()


def _count_visit(db: Session, user_id: int, day: date) -> None:
    row = db.get(ActivityDay, (user_id, day))
    if row:
        row.visits += 1
    else:
        db.add(ActivityDay(user_id=user_id, day=day, visits=1))


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Доступ только для администратора")
    return user
