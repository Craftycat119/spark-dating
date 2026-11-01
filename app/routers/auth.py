from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import demo, emailer
from ..config import settings
from ..database import get_db
from ..deps import COOKIE_NAME, client_ip, current_user, start_session
from ..models import AuthSession, EmailCode, User, utcnow
from ..security import (
    hash_password,
    hash_secret,
    is_valid_email,
    new_code,
    normalize_email,
    password_errors,
    verify_password,
)
from ..serializers import own_profile
from ..telegram_auth import verify_telegram_auth

router = APIRouter(prefix="/api/auth", tags=["auth"])

RESEND_COOLDOWN_SECONDS = 60
MAX_CODE_ATTEMPTS = 5


class Credentials(BaseModel):
    email: str
    password: str


class EmailOnly(BaseModel):
    email: str


class CodeIn(BaseModel):
    email: str
    code: str


class ResetIn(BaseModel):
    email: str
    code: str
    password: str


def _issue_code(db: Session, email: str, purpose: str, background: BackgroundTasks) -> dict:
    last = db.scalar(
        select(EmailCode)
        .where(EmailCode.email == email, EmailCode.purpose == purpose)
        .order_by(EmailCode.id.desc())
    )
    if last and (utcnow() - last.created_at).total_seconds() < RESEND_COOLDOWN_SECONDS:
        wait = RESEND_COOLDOWN_SECONDS - int((utcnow() - last.created_at).total_seconds())
        raise HTTPException(429, f"Новый код можно запросить через {wait} с")

    code = new_code()
    db.add(
        EmailCode(
            email=email,
            purpose=purpose,
            code_hash=hash_secret(code),
            expires_at=utcnow() + timedelta(minutes=settings.code_ttl_minutes),
        )
    )
    db.commit()
    background.add_task(emailer.send_code, email, code, purpose)
    result: dict = {"status": "code_sent", "email": email}
    if settings.dev_mode and not settings.smtp_host:
        result["dev_code"] = code  # удобно при локальной разработке без SMTP
    return result


def _check_code(db: Session, email: str, code: str, purpose: str) -> None:
    rec = db.scalar(
        select(EmailCode)
        .where(EmailCode.email == email, EmailCode.purpose == purpose, EmailCode.used.is_(False))
        .order_by(EmailCode.id.desc())
    )
    if not rec or rec.expires_at < utcnow():
        raise HTTPException(400, "Код устарел — запросите новый")
    if rec.attempts >= MAX_CODE_ATTEMPTS:
        raise HTTPException(400, "Слишком много попыток — запросите новый код")
    rec.attempts += 1
    if rec.code_hash != hash_secret(code.strip()):
        db.commit()
        raise HTTPException(400, "Неверный код")
    rec.used = True
    db.commit()


@router.post("/register")
def register(data: Credentials, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    email = normalize_email(data.email)
    if not is_valid_email(email):
        raise HTTPException(422, "Некорректная почта")
    errors = password_errors(data.password)
    if errors:
        raise HTTPException(422, "; ".join(errors))

    user = db.scalar(select(User).where(User.email == email))
    if user and user.email_verified:
        raise HTTPException(409, "Аккаунт с этой почтой уже существует — войдите")
    if not user:
        user = User(
            email=email,
            auth_provider="email",
            registration_ip=client_ip(request),
            registration_user_agent=request.headers.get("user-agent", "")[:512],
            is_admin=email in settings.admin_emails,
        )
        db.add(user)
    user.password_hash = hash_password(data.password)
    db.commit()
    return _issue_code(db, email, "verify", background)


@router.post("/resend-code")
def resend_code(data: EmailOnly, background: BackgroundTasks, db: Session = Depends(get_db)):
    email = normalize_email(data.email)
    user = db.scalar(select(User).where(User.email == email))
    if not user or user.email_verified:
        raise HTTPException(400, "Нечего подтверждать")
    return _issue_code(db, email, "verify", background)


@router.post("/verify-email")
def verify_email(data: CodeIn, request: Request, response: Response, db: Session = Depends(get_db)):
    email = normalize_email(data.email)
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        raise HTTPException(404, "Аккаунт не найден")
    _check_code(db, email, data.code, "verify")
    user.email_verified = True
    db.commit()
    start_session(db, user, request, response)
    return own_profile(user)


@router.post("/login")
def login(data: Credentials, request: Request, response: Response, background: BackgroundTasks, db: Session = Depends(get_db)):
    email = normalize_email(data.email)
    user = db.scalar(select(User).where(User.email == email))
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "Неверная почта или пароль")
    if user.is_banned:
        raise HTTPException(403, "Аккаунт заблокирован")
    if not user.email_verified:
        try:
            extra = _issue_code(db, email, "verify", background)
        except HTTPException:
            extra = {}
        raise HTTPException(403, {"code": "email_not_verified", "message": "Подтвердите почту — мы отправили код", **extra})
    if email in settings.admin_emails and not user.is_admin:
        user.is_admin = True
    start_session(db, user, request, response)
    return own_profile(user)


@router.post("/forgot-password")
def forgot_password(data: EmailOnly, background: BackgroundTasks, db: Session = Depends(get_db)):
    email = normalize_email(data.email)
    user = db.scalar(select(User).where(User.email == email))
    if user and user.email_verified:
        return _issue_code(db, email, "reset", background)
    # Не раскрываем, есть ли такой аккаунт
    return {"status": "code_sent", "email": email}


@router.post("/reset-password")
def reset_password(data: ResetIn, request: Request, response: Response, db: Session = Depends(get_db)):
    email = normalize_email(data.email)
    errors = password_errors(data.password)
    if errors:
        raise HTTPException(422, "; ".join(errors))
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        raise HTTPException(400, "Неверный код")
    _check_code(db, email, data.code, "reset")
    user.password_hash = hash_password(data.password)
    for s in db.scalars(select(AuthSession).where(AuthSession.user_id == user.id)):
        db.delete(s)
    db.commit()
    start_session(db, user, request, response)
    return own_profile(user)


@router.post("/telegram")
def telegram_login(data: dict, request: Request, response: Response, db: Session = Depends(get_db)):
    if not settings.telegram_bot_token:
        raise HTTPException(503, "Вход через Telegram не настроен")
    if not verify_telegram_auth(data, settings.telegram_bot_token):
        raise HTTPException(401, "Telegram не подтвердил вход")

    tg_id = int(data["id"])
    user = db.scalar(select(User).where(User.telegram_id == tg_id))
    if not user:
        user = User(
            telegram_id=tg_id,
            telegram_username=data.get("username"),
            auth_provider="telegram",
            name=(data.get("first_name") or "")[:64],
            registration_ip=client_ip(request),
            registration_user_agent=request.headers.get("user-agent", "")[:512],
        )
        db.add(user)
        db.commit()
    elif user.is_banned:
        raise HTTPException(403, "Аккаунт заблокирован")
    else:
        user.telegram_username = data.get("username") or user.telegram_username
    start_session(db, user, request, response)
    return own_profile(user)


@router.post("/demo")
def demo_login(request: Request, response: Response, db: Session = Depends(get_db)):
    """Вход в демо без регистрации: готовая анкета и 10 анкет-ботов рядом."""
    guest = demo.create_guest(db, client_ip(request), request.headers.get("user-agent", ""))
    start_session(db, guest, request, response)
    return own_profile(guest)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        sess = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_secret(token)))
        if sess:
            db.delete(sess)
            db.commit()
    response.delete_cookie(COOKIE_NAME)
    return {"status": "ok"}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return own_profile(user)
