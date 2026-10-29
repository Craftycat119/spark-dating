"""Сохранение файлов: фото профиля, кадры сканера, медиа из чатов."""
from __future__ import annotations

import io
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from .config import settings

VIDEO_EXT = {
    "video/webm": ".webm",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
}
AUDIO_EXT = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-m4a": ".m4a",
    "video/webm": ".webm",  # Chrome пишет голос как webm
}


def _target(folder: str, ext: str) -> tuple[Path, str]:
    rel = f"{folder}/{uuid.uuid4().hex}{ext}"
    path = settings.media_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    return path, rel


def read_limited(upload: UploadFile, max_mb: int) -> bytes:
    data = upload.file.read(max_mb * 1024 * 1024 + 1)
    if len(data) > max_mb * 1024 * 1024:
        raise HTTPException(413, f"Файл больше {max_mb} МБ")
    if not data:
        raise HTTPException(400, "Пустой файл")
    return data


def save_image(data: bytes, folder: str, max_side: int = 1600) -> str:
    """Пересохраняет картинку в JPEG: поворот по EXIF, удаление метаданных (в т.ч. GPS)."""
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(400, "Это не изображение") from exc
    img.thumbnail((max_side, max_side))
    path, rel = _target(folder, ".jpg")
    img.save(path, "JPEG", quality=88)
    return rel


def save_media(data: bytes, content_type: str, folder: str, kind: str) -> str:
    base_type = (content_type or "").split(";")[0].strip().lower()
    table = AUDIO_EXT if kind == "voice" else VIDEO_EXT
    ext = table.get(base_type)
    if not ext:
        raise HTTPException(415, f"Формат {base_type or 'неизвестен'} не поддерживается")
    path, rel = _target(folder, ext)
    path.write_bytes(data)
    return rel


def delete_file(rel: str | None) -> None:
    if not rel:
        return
    path = (settings.media_dir / rel).resolve()
    if settings.media_dir.resolve() in path.parents and path.exists():
        path.unlink()


def resolve(rel: str) -> Path | None:
    root = settings.media_dir.resolve()
    path = (root / rel).resolve()
    if root not in path.parents or not path.is_file():
        return None
    return path
