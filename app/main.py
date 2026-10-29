from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import face_verify
from .config import BASE_DIR, FEEDS, settings
from .database import get_db, init_db
from .deps import current_user
from .models import Conversation, User
from .routers import admin, auth, chat, feed, profile
from .storage import resolve

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("spark")
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    if settings.secret_key == "dev-secret-change-me" and not settings.dev_mode:
        log.error("SECRET_KEY не задан! Установите его в .env перед запуском в продакшене.")
    if face_verify.is_dev_mode():
        log.warning("FACE_MODE=dev — проверка лица ОТКЛЮЧЕНА. Не используйте в продакшене.")
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(feed.router)
app.include_router(feed.notifications_router)
app.include_router(chat.router)
app.include_router(chat.ws_router)
app.include_router(admin.router)


@app.get("/api/config")
def public_config():
    return {
        "app_name": settings.app_name,
        "feeds": FEEDS,
        "telegram_bot_username": settings.telegram_bot_username if settings.telegram_bot_token else None,
        "ice_servers": settings.ice_servers,
        "face_dev_mode": face_verify.is_dev_mode(),
    }


@app.get("/media/{rel:path}")
def media(rel: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Файлы отдаются только авторизованным: чат — участникам, кадр сканера — владельцу и админу."""
    path = resolve(rel)
    if not path:
        raise HTTPException(404)
    parts = rel.split("/")
    if parts[0] == "photos":
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


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/admin")
def admin_page():
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/{path:path}")
def spa(path: str, request: Request):
    if path.startswith(("api/", "media/", "ws")):
        raise HTTPException(404)
    return FileResponse(STATIC_DIR / "index.html")
