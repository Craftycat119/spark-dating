from __future__ import annotations

from datetime import timedelta

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import AuthSession, User, utcnow
from .security import hash_secret, new_session_token

COOKIE_NAME = "spark_session"


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def start_session(db: Session, user: User, request: Request, response: Response) -> None:
    token = new_session_token()
    db.add(
        AuthSession(
            token_hash=hash_secret(token),
            user_id=user.id,
            expires_at=utcnow() + timedelta(days=settings.session_days),
            ip=client_ip(request),
        )
    )
    user.last_seen_at = utcnow()
    db.commit()
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )


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
    if not user.last_seen_at or (now - user.last_seen_at).total_seconds() > 60:
        user.last_seen_at = now
        db.commit()
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Доступ только для администратора")
    return user
