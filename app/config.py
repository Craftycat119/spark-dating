"""Настройки приложения. Читаются из переменных окружения и файла .env."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Минимальный парсер .env, чтобы не тянуть лишнюю зависимость."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


_load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str) -> list[str]:
    return [x.strip().lower() for x in os.environ.get(name, "").split(",") if x.strip()]


@dataclass
class Settings:
    app_name: str = os.environ.get("APP_NAME", "COFI")
    base_url: str = os.environ.get("BASE_URL", "http://localhost:8000")
    secret_key: str = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    dev_mode: bool = _bool("DEV_MODE", True)

    data_dir: Path = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
    database_url: str = os.environ.get("DATABASE_URL", "")

    cookie_secure: bool = _bool("COOKIE_SECURE", False)
    session_days: int = int(os.environ.get("SESSION_DAYS", "30"))

    # Почта
    smtp_host: str = os.environ.get("SMTP_HOST", "")
    smtp_port: int = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user: str = os.environ.get("SMTP_USER", "")
    smtp_password: str = os.environ.get("SMTP_PASSWORD", "")
    smtp_from: str = os.environ.get("SMTP_FROM", "")
    smtp_ssl: bool = _bool("SMTP_SSL", False)  # True для порта 465
    code_ttl_minutes: int = int(os.environ.get("CODE_TTL_MINUTES", "15"))

    # Telegram Login Widget
    telegram_bot_token: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    telegram_bot_username: str = os.environ.get("TELEGRAM_BOT_USERNAME", "")

    # Админы: эти почты получают права администратора автоматически
    admin_emails: list[str] = field(default_factory=lambda: _list("ADMIN_EMAILS"))

    # Проверка лица: "opencv" — настоящая сверка, "dev" — всегда успешно (только для разработки)
    face_mode: str = os.environ.get("FACE_MODE", "opencv")
    face_models_dir: Path = Path(os.environ.get("FACE_MODELS_DIR", BASE_DIR / "models"))
    face_match_threshold: float = float(os.environ.get("FACE_MATCH_THRESHOLD", "0.363"))
    face_yaw_threshold: float = float(os.environ.get("FACE_YAW_THRESHOLD", "0.12"))

    # WebRTC: STUN/TURN-серверы для звонков (JSON-массив RTCIceServer)
    ice_servers: list = field(
        default_factory=lambda: json.loads(
            os.environ.get("ICE_SERVERS", '[{"urls": "stun:stun.l.google.com:19302"}]')
        )
    )

    max_image_mb: int = 10
    max_video_mb: int = 60

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'spark.db'}"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.media_dir.mkdir(parents=True, exist_ok=True)
