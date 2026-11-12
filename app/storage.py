"""Сохранение файлов: фото профиля, кадры сканера, медиа из чатов."""
from __future__ import annotations

import io
import logging
import shutil
import subprocess
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
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
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


log = logging.getLogger("cofi.media")


def to_playable(rel: str, kind: str) -> str:
    """Перекодирует видео в MP4 (H.264 + AAC), голос — в M4A (AAC).

    iPhone (и Telegram на нём) не играет webm, а Chrome и Android пишут кружки и голосовые именно в webm:
    без перекодирования у получателя на iPhone чёрный кружок. Нет ffmpeg или ошибка — оставляем исходный файл.
    """
    ffmpeg = shutil.which("ffmpeg")
    src = settings.media_dir / rel
    target_ext = ".m4a" if kind == "voice" else ".mp4"
    if ffmpeg and src.exists() and kind == "video" and src.suffix in (".mp4", ".mov"):
        _faststart(ffmpeg, src)
        return rel
    # mp4/mov с телефонов iPhone и так играет; перекодируем только webm/ogg
    if not ffmpeg or not src.exists() or src.suffix not in (".webm", ".ogg"):
        return rel
    new_rel = f"{rel.rsplit('.', 1)[0]}{target_ext}"
    dst = settings.media_dir / f"{new_rel}.tmp{target_ext}"
    if kind == "voice":
        codec = ["-vn", "-c:a", "aac", "-b:a", "96k"]
    else:
        codec = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p", "-profile:v", "main",
                 "-vf", "scale=w='trunc(min(1280,iw)/2)*2':h=-2", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart"]
    try:
        subprocess.run([ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-i", str(src), *codec, str(dst)],
                       check=True, timeout=180, capture_output=True)
    except (subprocess.SubprocessError, OSError) as exc:
        log.warning("Не удалось перекодировать %s: %s", rel, (getattr(exc, "stderr", None) or b"")[-300:] or exc)
        dst.unlink(missing_ok=True)
        return rel
    dst.replace(settings.media_dir / new_rel)
    src.unlink(missing_ok=True)
    return new_rel


def _faststart(ffmpeg: str, src: Path) -> None:
    """Видео с телефона без перекодирования (качество то же): служебный индекс переносим в начало файла,
    и у получателя ролик начинает играть сразу, не дожидаясь загрузки до конца."""
    tmp = src.with_name(f"{src.stem}.fast{src.suffix}")
    try:
        subprocess.run([ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-i", str(src), "-map", "0", "-c", "copy",
                        "-movflags", "+faststart", str(tmp)], check=True, timeout=120, capture_output=True)
        tmp.replace(src)
    except (subprocess.SubprocessError, OSError) as exc:
        log.warning("faststart не удался для %s: %s", src.name, exc)
        tmp.unlink(missing_ok=True)


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
