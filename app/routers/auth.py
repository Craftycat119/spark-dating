from __future__ import annotations

import hashlib
import logging
import hmac
import json
import time
from datetime import timedelta
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import captcha, demo, emailer, telegram_bot
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
from ..ratelimit import by_ip, hit, is_local_request, reset
from ..serializers import own_profile

log = logging.getLogger("cofi.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])

RESEND_COOLDOWN_SECONDS = 60
MAX_CODE_ATTEMPTS = 5


class Credentials(BaseModel):
    email: str
    password: str
    captcha_id: str | None = None  # id картинки (CAPTCHA=image)
    captcha: str | None = None  # ответ: цифры с картинки или токен Turnstile


class EmailOnly(BaseModel):
    email: str
    captcha_id: str | None = None
    captcha: str | None = None


@router.get("/captcha")
def get_captcha(request: Request):
    """Новая картинка для проверки на робота."""
    by_ip(request, "captcha", 60, 600)
    if captcha.mode() != "image":
        return captcha.public_config()
    return {**captcha.public_config(), **captcha.new_image()}


class CodeIn(BaseModel):
    email: str
    code: str


class ResetIn(BaseModel):
    email: str
    code: str
    password: str


DUMMY_HASH = hash_password("timing-equalizer-9")


def _issue_code(db: Session, email: str, purpose: str, request: Request) -> dict:
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
    # Код отправляем сразу, а не в фоне: если почта не настроена или сломалась, человек узнает об этом здесь
    sent = emailer.send_code(email, code, purpose)
    result: dict = {"status": "code_sent", "email": email}
    delivered = sent and bool(settings.smtp_host)  # без SMTP письмо только печатается в терминал сервера
    if not delivered and settings.dev_mode and is_local_request(request):
        # Код на экране — только когда открыли сайт на этом же компьютере (localhost).
        # Через туннель или из интернета так нельзя: иначе любой зарегистрируется на чужую почту или сбросит чужой пароль.
        result["dev_code"] = code
    elif not settings.smtp_host:
        raise HTTPException(503, "Почта на сервере не настроена, письмо с кодом не отправить. Войдите через Telegram")
    elif not sent:
        raise HTTPException(502, "Не удалось отправить письмо с кодом. Попробуйте позже или войдите через Telegram")
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
def register(data: Credentials, request: Request, db: Session = Depends(get_db)):
    by_ip(request, "register", 10, 3600)
    captcha.require(data.captcha_id, data.captcha, client_ip(request))
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
    try:
        return _issue_code(db, email, "verify", request)
    except HTTPException as ex:
        # Вернулись «Назад» с экрана кода и снова нажали «Создать аккаунт»: письмо уже ушло,
        # пускаем на экран кода, старый код по-прежнему действует
        if ex.status_code != 429:
            raise
        return {"status": "code_pending", "email": email, "detail": ex.detail}


@router.post("/resend-code")
def resend_code(data: EmailOnly, request: Request, db: Session = Depends(get_db)):
    by_ip(request, "resend", 10, 3600)
    email = normalize_email(data.email)
    user = db.scalar(select(User).where(User.email == email))
    if not user or user.email_verified:
        raise HTTPException(400, "Нечего подтверждать")
    return _issue_code(db, email, "verify", request)


@router.post("/verify-email")
def verify_email(data: CodeIn, request: Request, response: Response, db: Session = Depends(get_db)):
    by_ip(request, "verify", 30, 600)
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
def login(data: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    by_ip(request, "login", 30, 600)
    hit(f"login:email:{normalize_email(data.email)}", 10, 900)  # подбор пароля к одной почте с разных адресов
    captcha.require(data.captcha_id, data.captcha, client_ip(request))
    email = normalize_email(data.email)
    user = db.scalar(select(User).where(User.email == email))
    ok = verify_password(data.password, (user.password_hash if user else None) or DUMMY_HASH)  # одинаковое время для любой почты
    if not user or not ok:
        raise HTTPException(401, "Неверная почта или пароль")
    if user.is_banned:
        raise HTTPException(403, "Аккаунт заблокирован")
    if not user.email_verified:
        try:
            extra = _issue_code(db, email, "verify", request)
        except HTTPException:
            extra = {}
        raise HTTPException(403, {"code": "email_not_verified", "message": "Подтвердите почту — мы отправили код", **extra})
    if email in settings.admin_emails and not user.is_admin:
        user.is_admin = True
    reset(f"login:email:{email}")
    start_session(db, user, request, response)
    return own_profile(user)


@router.post("/forgot-password")
def forgot_password(data: EmailOnly, request: Request, db: Session = Depends(get_db)):
    by_ip(request, "forgot", 10, 3600)
    captcha.require(data.captcha_id, data.captcha, client_ip(request))
    email = normalize_email(data.email)
    user = db.scalar(select(User).where(User.email == email))
    if user and user.email_verified:
        return _issue_code(db, email, "reset", request)
    # Не раскрываем, есть ли такой аккаунт
    return {"status": "code_sent", "email": email}


@router.post("/reset-password")
def reset_password(data: ResetIn, request: Request, response: Response, db: Session = Depends(get_db)):
    by_ip(request, "reset", 20, 600)
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


class TelegramPoll(BaseModel):
    token: str


@router.post("/telegram/start")
def telegram_start(request: Request):
    """Начать вход через бота: ссылка t.me/<бот>?start=login_<токен>."""
    by_ip(request, "tg-start", 20, 600)
    if not settings.telegram_bot_token or not telegram_bot.bot_username():
        raise HTTPException(503, "Вход через Telegram не настроен: администратору нужно указать TELEGRAM_BOT_TOKEN в .env")
    return telegram_bot.new_login(_device_label(request.headers.get("user-agent", "")))


@router.post("/telegram/poll")
def telegram_poll(data: TelegramPoll, request: Request, response: Response, db: Session = Depends(get_db)):
    p = telegram_bot.take_login(data.token)
    if not p:
        raise HTTPException(410, "Ссылка для входа устарела, нажмите «Войти через Telegram» ещё раз")
    if p.status == "pending":
        return {"status": "pending"}
    if p.status == "declined":
        raise HTTPException(403, "Вход отменён в Telegram")

    user = _telegram_user(db, p.user, request)
    start_session(db, user, request, response)
    return {"status": "ok", "user": own_profile(user)}


def _telegram_user(db: Session, tg: dict, request: Request) -> User:
    """Находит аккаунт по Telegram id или создаёт новый."""
    user = db.scalar(select(User).where(User.telegram_id == tg["id"]))
    if not user:
        user = User(
            telegram_id=tg["id"],
            telegram_username=tg.get("username"),
            auth_provider="telegram",
            name=(tg.get("first_name") or "")[:64],
            registration_ip=client_ip(request),
            registration_user_agent=request.headers.get("user-agent", "")[:512],
        )
        db.add(user)
        db.commit()
    elif user.is_banned:
        raise HTTPException(403, "Аккаунт заблокирован")
    else:
        user.telegram_username = tg.get("username") or user.telegram_username
    return user


class WebAppIn(BaseModel):
    init_data: str


@router.post("/telegram/webapp")
def telegram_webapp(data: WebAppIn, request: Request, response: Response, db: Session = Depends(get_db)):
    """Вход в мини-приложении: Telegram передаёт подписанные данные о пользователе (initData)."""
    by_ip(request, "tg-webapp", 30, 600)
    if not settings.telegram_bot_token:
        raise HTTPException(503, "Вход через Telegram не настроен")
    tg = verify_webapp_init_data(data.init_data, settings.telegram_bot_token)
    if not tg:
        log.warning("Вход из мини-приложения отклонён: подпись Telegram не совпала или данные старше часа. "
                    "Проверьте, что TELEGRAM_BOT_TOKEN в .env — от того же бота, в котором открыто приложение (после /revoke токен новый)")
        raise HTTPException(401, "Telegram не подтвердил вход")
    user = _telegram_user(db, tg, request)
    start_session(db, user, request, response)
    return own_profile(user)


def verify_webapp_init_data(init_data: str, bot_token: str, max_age: int = 3600) -> dict | None:
    """Проверка подписи initData: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app"""
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    if not received or not hmac.compare_digest(hmac.new(secret, check.encode(), hashlib.sha256).hexdigest(), received):
        return None
    try:
        if time.time() - int(pairs.get("auth_date", 0)) > max_age:
            return None
        user = json.loads(pairs.get("user", "{}"))
    except (TypeError, ValueError):
        return None
    return user if user.get("id") else None


def _device_label(ua: str) -> str:
    """Коротко, с какого устройства входят: показываем в боте перед подтверждением."""
    os_name = next((n for k, n in [("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"),
                                     ("Mac OS", "macOS"), ("Linux", "Linux")] if k in ua), "")
    browser = next((n for k, n in [("YaBrowser", "Яндекс Браузер"), ("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox", "Firefox"),
                                     ("Chrome", "Chrome"), ("Safari", "Safari")] if k in ua), "браузер")
    return f"{browser}, {os_name}" if os_name else browser


class DemoIn(BaseModel):
    teen: bool = False


@router.post("/demo")
def demo_login(request: Request, response: Response, data: DemoIn | None = None, db: Session = Depends(get_db)):
    """Вход в демо без регистрации: готовая анкета и анкеты-боты рядом («Знакомства» 18+ или «Дружба» до 18 лет)."""
    by_ip(request, "demo", 15, 3600)
    guest = demo.create_guest(db, client_ip(request), request.headers.get("user-agent", ""), teen=bool(data and data.teen))
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
