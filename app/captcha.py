"""Проверка на робота при входе, регистрации и сбросе пароля.

CAPTCHA=image (по умолчанию) — своя картинка с цифрами, без внешних сервисов.
CAPTCHA=turnstile — Cloudflare Turnstile (бесплатно, часто вообще без действий): нужны TURNSTILE_SITE_KEY и TURNSTILE_SECRET.
CAPTCHA=off — выключено (только для тестов и разработки).
"""
from __future__ import annotations

import base64
import io
import json
import math
import random
import secrets
import threading
import time
import urllib.parse
import urllib.request

from fastapi import HTTPException
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import settings
from .security import hash_secret

TTL = 300  # картинка действует 5 минут
_store: dict[str, tuple[str, float]] = {}  # id → (хэш ответа, когда создана)
_lock = threading.Lock()
DIGITS = "23456789"  # без 0/1, их легко спутать с буквами


def mode() -> str:
    m = settings.captcha_mode
    if m == "turnstile" and not (settings.turnstile_site_key and settings.turnstile_secret):
        return "image"  # ключи не заданы — своя картинка
    return m


def public_config() -> dict:
    return {"mode": mode(), "site_key": settings.turnstile_site_key if mode() == "turnstile" else None}


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # старый Pillow
        return ImageFont.load_default()


def new_image() -> dict:
    """Картинка 5 цифр с искажениями и шумом, ответ хранится только в виде хэша."""
    answer = "".join(random.choice(DIGITS) for _ in range(5))
    w, h = 220, 80
    img = Image.new("RGB", (w, h), (243, 233, 223))
    draw = ImageDraw.Draw(img)
    for _ in range(7):  # линии-помехи
        draw.line([(random.randint(0, w), random.randint(0, h)) for _ in range(2)],
                  fill=(random.randint(120, 200), random.randint(80, 150), random.randint(60, 120)), width=2)
    x = 14
    for ch in answer:
        glyph = Image.new("RGBA", (54, 70), (0, 0, 0, 0))
        color = (random.randint(20, 90), random.randint(10, 50), random.randint(0, 30))
        ImageDraw.Draw(glyph).text((8, 2), ch, font=_font(random.randint(40, 50)), fill=color, stroke_width=1, stroke_fill=color)
        glyph = glyph.rotate(random.uniform(-28, 28), resample=Image.BICUBIC, expand=False)
        img.paste(glyph, (x, random.randint(-2, 12)), glyph)
        x += random.randint(34, 42)
    # волна по горизонтали, чтобы цифры нельзя было вырезать по сетке
    out = Image.new("RGB", (w, h), (243, 233, 223))
    amp, period, phase = random.uniform(2, 4), random.uniform(28, 44), random.uniform(0, 6.28)
    for y in range(h):
        shift = int(amp * math.sin(y / period * 6.28 + phase))
        out.paste(img.crop((0, y, w, y + 1)), (shift, y))
    pix = ImageDraw.Draw(out)
    for _ in range(260):  # точки-шум
        pix.point((random.randrange(w), random.randrange(h)), fill=(random.randint(60, 200),) * 3)
    out = out.filter(ImageFilter.SMOOTH)
    buf = io.BytesIO()
    out.save(buf, "PNG")
    cid = secrets.token_urlsafe(12)
    now = time.time()
    with _lock:
        for k in [k for k, (_, t) in _store.items() if now - t > TTL]:
            del _store[k]
        _store[cid] = (hash_secret(answer), now)
    return {"id": cid, "image": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()}


def _check_image(cid: str, answer: str) -> bool:
    with _lock:
        rec = _store.pop(cid or "", None)  # одна попытка на картинку: перебрать варианты нельзя
    if not rec or time.time() - rec[1] > TTL:
        return False
    return secrets.compare_digest(rec[0], hash_secret((answer or "").strip()))


def _check_turnstile(token: str, ip: str) -> bool:
    data = urllib.parse.urlencode({"secret": settings.turnstile_secret, "response": token or "", "remoteip": ip}).encode()
    try:
        with urllib.request.urlopen("https://challenges.cloudflare.com/turnstile/v0/siteverify", data=data, timeout=10) as r:
            return bool(json.loads(r.read()).get("success"))
    except Exception:  # noqa: BLE001 — Cloudflare недоступен: не пускаем, чтобы проверку нельзя было обойти
        return False


def require(captcha_id: str | None, answer: str | None, ip: str) -> None:
    """Проверить ответ. Ошибка 400 с code=captcha — страница покажет новую картинку."""
    m = mode()
    if m == "off":
        return
    ok = _check_turnstile(answer or "", ip) if m == "turnstile" else _check_image(captcha_id or "", answer or "")
    if not ok:
        raise HTTPException(400, {"code": "captcha", "message": "Проверка на робота не пройдена, попробуйте ещё раз"})
