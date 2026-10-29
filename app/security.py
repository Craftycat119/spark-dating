from __future__ import annotations

import hashlib
import hmac
import re
import secrets

import bcrypt

from .config import settings

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def password_errors(password: str) -> list[str]:
    """Правила: минимум 8 символов, хотя бы одна заглавная буква и одна цифра."""
    errors = []
    if len(password) < 8:
        errors.append("Пароль должен быть не короче 8 символов")
    if not any(c.isupper() for c in password):
        errors.append("Нужна хотя бы одна заглавная буква")
    if not any(c.isdigit() for c in password):
        errors.append("Нужна хотя бы одна цифра")
    if len(password.encode()) > 72:
        errors.append("Пароль слишком длинный (максимум 72 байта)")
    return errors


def normalize_email(email: str) -> str:
    return email.strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email)) and len(email) <= 255


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_secret(value: str) -> str:
    return hmac.new(settings.secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()


def new_session_token() -> str:
    return secrets.token_urlsafe(32)
