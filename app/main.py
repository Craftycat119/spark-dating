from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import captcha, face_verify, telegram_bot
from .config import BASE_DIR, settings
from .ages import MIN_AGE, TEEN_GOALS
from .legal import TERMS_VERSION
from .interests import GENDERS, LOOKING_FOR, MIN_INTERESTS, ORIENTATIONS, ORIENTATIONS_BY_GENDER, SURVEY, TEEN_GENDERS, ZODIAC
from .database import get_db, init_db
from .deps import current_user
from .models import Conversation, User
from .realtime import set_loop
from .seed_pets import seed_pets
from .routers import admin, animals, auth, chat, feed, profile, support, users
from .storage import resolve

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("spark")
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    from .database import SessionLocal
    from .demo import cleanup

    with SessionLocal() as db:
        removed = cleanup(db)
        if removed:
            log.info("Удалено устаревших демо-аккаунтов: %s", removed)
        # просроченные входы и коды подтверждения больше не нужны: не копим их в базе
        from .models import AuthSession, EmailCode, utcnow

        db.execute(delete(AuthSession).where(AuthSession.expires_at < utcnow()))
        db.execute(delete(EmailCode).where(EmailCode.expires_at < utcnow() - timedelta(days=1)))
        db.commit()
        try:  # готовые объявления «Питомцы» из app/seed/pets
            seed_pets(db)
        except Exception:  # noqa: BLE001 — объявления не должны мешать запуску
            log.exception("Не удалось добавить готовые объявления о питомцах")
    if settings.secret_key == "dev-secret-change-me" and not settings.dev_mode:
        log.error("SECRET_KEY не задан! Установите его в .env перед запуском в продакшене.")
    if settings.dev_mode and settings.base_url.startswith("https://") and "localhost" not in settings.base_url:
        log.warning("DEV_MODE=1 при публичном адресе %s. Коды на экране показываются только при входе с localhost, "
                    "но для настоящего сайта поставьте DEV_MODE=0 и SECRET_KEY", settings.base_url)
    if face_verify.is_dev_mode():
        log.warning("FACE_MODE=dev — проверка лица ОТКЛЮЧЕНА. Не используйте в продакшене.")
    set_loop(asyncio.get_running_loop())
    telegram_bot.start()
    yield
    telegram_bot.stop()


# Карта API (/docs, /redoc, /openapi.json) — только при разработке: в продакшене она облегчает поиск слабых мест
_docs = settings.dev_mode
app = FastAPI(title=settings.app_name, lifespan=lifespan, docs_url="/docs" if _docs else None,
              redoc_url="/redoc" if _docs else None, openapi_url="/openapi.json" if _docs else None)
app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(feed.router)
app.include_router(feed.notifications_router)
app.include_router(chat.router)
app.include_router(chat.ws_router)
app.include_router(users.router)
app.include_router(users.blocks_router)
app.include_router(animals.router)
app.include_router(support.router)
app.include_router(admin.router)


@app.get("/api/config")
def public_config():
    return {
        "app_name": settings.app_name,
        "survey": SURVEY,
        "teen_goals": TEEN_GOALS,
        "min_age": MIN_AGE,
        "terms_version": TERMS_VERSION,
        "captcha": captcha.public_config(),
        "genders": GENDERS,
        "teen_genders": TEEN_GENDERS,
        "orientations": ORIENTATIONS,
        "orientations_by_gender": ORIENTATIONS_BY_GENDER,
        "zodiac": ZODIAC,
        "looking_for": LOOKING_FOR,
        "min_interests": MIN_INTERESTS,
        "telegram_bot_username": telegram_bot.bot_username() if settings.telegram_bot_token else None,
        "calls_enabled": settings.calls_enabled,
        "stats_tz_hours": settings.stats_tz_hours,  # часовой пояс админ-панели
        "ice_servers": settings.stun_servers,  # без паролей TURN: их выдаёт /api/calls/ice только вошедшим
        "face_dev_mode": face_verify.is_dev_mode(),
    }


@app.get("/api/calls/ice")
def call_ice_servers(user: User = Depends(current_user)):
    """Серверы для звонка. Пароль TURN — только вошедшим и временный (на час), если задан TURN_SECRET."""
    if not settings.calls_enabled:
        raise HTTPException(403, "Звонки выключены")
    if settings.turn_secret and settings.turn_urls:
        import base64
        import hashlib
        import hmac
        import time

        username = f"{int(time.time()) + 3600}:{user.id}"
        password = base64.b64encode(hmac.new(settings.turn_secret.encode(), username.encode(), hashlib.sha1).digest()).decode()
        return settings.stun_servers + [{"urls": settings.turn_urls, "username": username, "credential": password}]
    return settings.ice_servers


@app.get("/media/{rel:path}")
def media(rel: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Файлы отдаются только авторизованным: чат — участникам, кадр сканера — владельцу и админу."""
    path = resolve(rel)
    if not path:
        raise HTTPException(404)
    parts = rel.split("/")
    if parts[0] in ("photos", "gallery", "animals"):
        pass
    elif parts[0] == "selfies":
        if not user.is_admin and user.selfie_path != rel:
            raise HTTPException(403)
    elif parts[0] == "chat" and len(parts) >= 3 and parts[1].isdigit():
        if not user.is_admin:
            conv = db.scalar(select(Conversation).where(Conversation.id == int(parts[1])))
            if not conv or not conv.has(user.id):
                raise HTTPException(403)
    else:
        raise HTTPException(404)
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Защитные заголовки: браузер не угадывает тип файлов, сайт нельзя встроить на чужую страницу
    (кроме Telegram Web для мини-приложения), адрес страницы не утекает на другие сайты."""
    response = await call_next(request)
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    host = request.headers.get("host", "")
    h.setdefault("Content-Security-Policy", "; ".join([
        "default-src 'self'",
        "script-src 'self' https://telegram.org https://challenges.cloudflare.com",  # только свои файлы, Telegram и капча Cloudflare
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com data:",
        "img-src 'self' data: blob: https:",
        "media-src 'self' data: blob:",
        f"connect-src 'self' wss://{host} ws://{host}",
        "frame-src https://challenges.cloudflare.com",
        "worker-src 'self' blob:",
        "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org",
        "object-src 'none'", "base-uri 'self'", "form-action 'self'",
    ]))
    h.setdefault("Permissions-Policy", "camera=(self), microphone=(self), geolocation=(self), payment=()")
    if request.url.scheme == "https":
        h.setdefault("Strict-Transport-Security", "max-age=31536000")
    if request.url.path.startswith("/api/"):
        h.setdefault("Cache-Control", "no-store")  # личные данные из API не оседают в кэше браузера и прокси
    return response


class FreshStatic(StaticFiles):
    """Браузер каждый раз сверяет файл с сервером (ETag), поэтому после обновления не показывает старую версию."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app.mount("/static", FreshStatic(directory=STATIC_DIR), name="static")


@app.get("/admin")
def admin_page():
    return FileResponse(STATIC_DIR / "admin.html", headers={"Cache-Control": "no-cache"})


@app.get("/{path:path}")
def spa(path: str, request: Request):
    if path.startswith(("api/", "media/", "ws")):
        raise HTTPException(404)
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})
