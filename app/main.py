from __future__ import annotations

import asyncio
from urllib.parse import urlparse
import logging
from datetime import timedelta
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import assets, captcha, face_verify, telegram_bot
from .config import BASE_DIR, settings
from .ages import MIN_AGE, TEEN_GOALS
from .legal import TERMS_VERSION
from .interests import ADULT_ONLY_INTERESTS, GENDERS, LOOKING_FOR, MIN_INTERESTS, ORIENTATIONS, ORIENTATIONS_BY_GENDER, SURVEY, TEEN_GENDERS, ZODIAC
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


def _drop_adult_interests_for_teens(db: Session) -> None:
    from .models import User as _U

    changed = 0
    for u in db.scalars(select(_U).where(_U.is_bot.is_(False), _U.birth_date.is_not(None))):
        if u.age_group != "teen":
            continue
        fixed = False
        if ADULT_ONLY_INTERESTS & set(u.interests):
            u.interests = [i for i in u.interests if i not in ADULT_ONLY_INTERESTS]
            fixed = True
        if any(g not in TEEN_GOALS for g in u.goals):  # например, «Языковой обмен» — для подростков его больше нет
            u.goals = [g for g in u.goals if g in TEEN_GOALS] or ["Дружба"]
            fixed = True
        changed += fixed
    if changed:
        db.commit()
        log.info("Подросткам убраны интересы и цели «только для взрослых»: %s", changed)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    from .database import SessionLocal
    from .demo import cleanup, ensure_bots

    with SessionLocal() as db:
        if settings.demo_enabled:
            ensure_bots(db)  # боты демо-версии — один общий набор на всех гостей
        removed = cleanup(db)
        if removed:
            log.info("Удалено устаревших демо-аккаунтов: %s", removed)
        # просроченные входы и коды подтверждения больше не нужны: не копим их в базе
        from .models import AuthSession, EmailCode, utcnow

        db.execute(delete(AuthSession).where(AuthSession.expires_at < utcnow()))
        db.execute(delete(EmailCode).where(EmailCode.expires_at < utcnow() - timedelta(days=1)))
        db.commit()
        try:  # радиус по умолчанию теперь максимальный: старое умолчание (50 км) меняем один раз
            from .models import AppFlag, User as _U2

            if not db.get(AppFlag, "radius_default_7000"):
                db.execute(_U2.__table__.update().where(_U2.max_distance_km == 50).values(max_distance_km=settings.max_distance_km))
                db.add(AppFlag(key="radius_default_7000"))
                db.commit()
        except Exception:  # noqa: BLE001
            log.exception("Не удалось обновить радиус поиска по умолчанию")
        try:  # город по геопозиции для анкет, сохранённых до появления этой функции
            from .cities import city_name
            from .models import User as _U

            todo = db.scalars(select(_U).where(_U.lat.is_not(None), _U.city.is_(None))).all()
            for u in todo:
                u.city = city_name(u.lat, u.lon)
            if todo:
                db.commit()
        except Exception:  # noqa: BLE001
            log.exception("Не удалось определить города анкет")
        try:  # интересы «только для взрослых», выбранные подростками до появления ограничения
            _drop_adult_interests_for_teens(db)
        except Exception:  # noqa: BLE001
            log.exception("Не удалось убрать подросткам интересы «только для взрослых»")
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
    try:  # видео, обработка которых прервалась перезапуском, — доделать фоном
        import threading

        from .routers.chat import resume_unfinished_videos

        threading.Thread(target=resume_unfinished_videos, name="video-resume", daemon=True).start()
    except Exception:  # noqa: BLE001
        log.exception("Не удалось запустить доработку видео")
    yield
    telegram_bot.stop()


# Карта API (/docs, /redoc, /openapi.json) — только при разработке: в продакшене она облегчает поиск слабых мест
_docs = settings.dev_mode
app = FastAPI(title=settings.app_name, lifespan=lifespan, docs_url="/docs" if _docs else None,
              redoc_url="/redoc" if _docs else None, openapi_url="/openapi.json" if _docs else None)
# Ошибки проверки данных (422): короткий русский текст без схемы запроса и без эха того, что прислали
_VALIDATION_TEXT = {
    "missing": "Заполните поле", "string_too_short": "Слишком короткое значение", "string_too_long": "Слишком длинный текст",
    "too_short": "Слишком мало значений", "too_long": "Слишком много значений", "json_invalid": "Неверный формат запроса",
}


@app.exception_handler(RequestValidationError)
async def _validation_error(_request: Request, exc: RequestValidationError):
    out = []
    for e in exc.errors()[:5]:
        msg = str(e.get("msg") or "")
        if e.get("type") == "value_error":  # наши проверки (возраст, интересы…) — уже понятный русский текст
            msg = msg.removeprefix("Value error, ")
        else:
            msg = _VALIDATION_TEXT.get(e.get("type", ""), "Неверное значение")
        out.append({"loc": [x for x in e.get("loc", ()) if isinstance(x, (str, int))][-2:], "msg": msg})
    return JSONResponse({"detail": out}, status_code=422)


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
        "adult_only_interests": sorted(ADULT_ONLY_INTERESTS),
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
        # имя бота из Telegram, а если связи с ним сейчас нет — из .env (TELEGRAM_BOT_USERNAME)
        "telegram_bot_username": ((telegram_bot.bot_username() if settings.telegram_bot_token else "")
                                  or settings.telegram_bot_username.lstrip("@") or None),
        "calls_enabled": settings.calls_enabled,
        "demo_enabled": settings.demo_enabled,
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


@app.api_route("/pub/broadcast/{name}", methods=["GET", "HEAD"])  # HEAD: Telegram сначала проверяет картинку им
def broadcast_image(name: str):
    """Картинка рассылки — публичная: её скачивает Telegram, чтобы показать над текстом. Только наши имена файлов."""
    import re as _re

    if not _re.fullmatch(r"[0-9a-f]{32}\.jpg", name):
        raise HTTPException(404)
    path = settings.media_dir / "broadcast" / name
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=604800"})


@app.get("/media/{rel:path}")
def media(rel: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Файлы отдаются только авторизованным: чат — участникам, кадр сканера — владельцу и админу."""
    path = resolve(rel)
    if not path:
        raise HTTPException(404)
    parts = rel.split("/")
    if parts[0] in ("photos", "gallery", "animals", "ads"):
        pass
    elif parts[0] == "selfies":
        if not user.is_admin and user.selfie_path != rel:
            raise HTTPException(403)
    elif parts[0] == "chat" and len(parts) >= 3 and parts[1].isdigit():
        if not (user.is_admin and settings.admin_read_chats):  # администрация видит файлы чатов, только если это включено
            conv = db.scalar(select(Conversation).where(Conversation.id == int(parts[1])))
            if not conv or not conv.has(user.id):
                raise HTTPException(403)
    else:
        raise HTTPException(404)
    from .storage import EXT_TYPE

    # тип файла указываем явно: Android не проигрывает голосовое, если сервер не знает .m4a и отдаёт «text/plain»
    kind = EXT_TYPE.get(path.suffix.lower())
    return FileResponse(path, media_type=kind, headers={"Cache-Control": "private, max-age=86400"})


@app.middleware("http")
async def same_origin_only(request: Request, call_next):
    """Изменяющие запросы принимаем только со своего сайта: браузер всегда ставит заголовок Origin,
    и форма или скрипт с чужого сайта не сможет действовать от имени вошедшего пользователя."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and (origin := request.headers.get("origin")):
        allowed = {request.headers.get("host"), request.headers.get("x-forwarded-host"), urlparse(settings.base_url).netloc}
        if urlparse(origin).netloc not in allowed:
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "Запрос с чужого сайта отклонён"}, status_code=403)
    return await call_next(request)


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
        "script-src 'self' https://challenges.cloudflare.com",  # только свои файлы (SDK Telegram — своя копия) и капча Cloudflare
        "style-src 'self' 'unsafe-inline'",
        "font-src 'self' data:",
        "img-src 'self' data: blob: https:",
        "media-src 'self' data: blob: mediastream:",  # mediastream: — без него Safari/Telegram на iPhone показывают камеру чёрной
        f"connect-src 'self' wss://{host} ws://{host}",
        "frame-src https://challenges.cloudflare.com",
        "worker-src 'self' blob:",
        "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org",
        "object-src 'none'", "base-uri 'self'", "form-action 'self'",
    ]))
    # окно входа/оплаты сторонних сервисов работает, но чужая вкладка не получает доступ к нашей
    h.setdefault("Cross-Origin-Opener-Policy", "same-origin-allow-popups")
    h.setdefault("Cross-Origin-Resource-Policy", "same-site")
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


class VersionedStatic(StaticFiles):
    """/static/v/<версия>/... — тот же файл, но браузер хранит его год без перепроверки (адрес меняется с версией)."""

    async def get_response(self, path: str, scope):
        ver, _, rest = path.partition("/")
        resp = await super().get_response(rest, scope)
        if resp.status_code == 200:
            # чужая (старая) версия: файл уже новый, кэшировать его под старым адресом нельзя
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable" if ver == assets.version() else "no-cache"
        return resp


app.mount("/static/v", VersionedStatic(directory=STATIC_DIR), name="static-v")
app.mount("/static", FreshStatic(directory=STATIC_DIR), name="static")

PAGE_HEADERS = {"Cache-Control": "no-cache"}


class ClientLogIn(BaseModel):
    kind: str = Field("", max_length=30)
    message: str = Field("", max_length=600)
    extra: str = Field("", max_length=600)
    url: str = Field("", max_length=100)
    ua: str = Field("", max_length=400)


@app.post("/api/client-log")
def client_log(data: ClientLogIn, request: Request):
    """Отчёт телефона «не запустилось / ошибка в коде» — в журнал сервера: journalctl -u cofi | grep КЛИЕНТ"""
    from .ratelimit import by_ip

    by_ip(request, "client-log", 30, 3600)
    log.warning("КЛИЕНТ %s: %s | %s | %s | %s", data.kind, data.message, data.extra, data.url, data.ua)
    return {"status": "ok"}


@app.get("/tg")
def tg_shortcut():
    """Страница для ярлыка на экране «Домой»: с ярлыка COFI открывается в Telegram, а не в браузере."""
    import html as _html

    bot = telegram_bot.bot_username() if settings.telegram_bot_token else settings.telegram_bot_username
    page = (STATIC_DIR / "tg.html").read_text(encoding="utf-8").replace("{{BOT}}", _html.escape(bot or ""))
    return HTMLResponse(page, headers=PAGE_HEADERS)


@app.get("/admin")
def admin_page():
    return HTMLResponse(assets.page("admin.html", "js/admin.js"), headers=PAGE_HEADERS)


# /pub/ не закрываем: Telegram учитывает robots.txt и без доступа не покажет картинку рассылки
ROBOTS = """User-agent: *
Allow: /$
Disallow: /api/
Disallow: /media/
Disallow: /admin
"""


@app.api_route("/robots.txt", methods=["GET", "HEAD"])
def robots():
    return PlainTextResponse(ROBOTS, headers={"Cache-Control": "public, max-age=86400"})


@app.api_route("/{path:path}", methods=["GET", "HEAD"])
def spa(path: str):
    if path.startswith(("api/", "media/", "ws")):
        raise HTTPException(404)
    # несуществующий файл (sitemap.xml, .env, wp-login.php…) — честный 404, а не главная страница
    if "." in path.rsplit("/", 1)[-1]:
        raise HTTPException(404)
    return HTMLResponse(assets.page("index.html", "js/app.js"), headers=PAGE_HEADERS)
