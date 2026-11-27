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
    "video/x-m4v": ".mp4",
    "video/3gpp": ".mp4",
}
# Телефон иногда не указывает тип файла (пусто или application/octet-stream) — тогда смотрим на расширение
EXT_TYPE = {".mov": "video/quicktime", ".mp4": "video/mp4", ".m4v": "video/x-m4v", ".webm": "video/webm", ".3gp": "video/3gpp",
            ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".mp3": "audio/mpeg", ".wav": "audio/wav"}


def media_type(content_type: str | None, filename: str | None) -> str:
    base = (content_type or "").split(";")[0].strip().lower()
    if base and base != "application/octet-stream":
        return base
    return EXT_TYPE.get(Path(filename or "").suffix.lower(), base)
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


def save_media_stream(upload: UploadFile, folder: str, kind: str, max_mb: int) -> str:
    """Видео/голос пишем на диск кусками, не держа весь файл в памяти (ролики с телефона бывают по 100+ МБ)."""
    base_type = media_type(upload.content_type, upload.filename)
    ext = (AUDIO_EXT if kind == "voice" else VIDEO_EXT).get(base_type)
    if not ext:
        raise HTTPException(415, f"Формат {base_type or 'неизвестен'} не поддерживается")
    path, rel = _target(folder, ext)
    limit, size = max_mb * 1024 * 1024, 0
    try:
        with path.open("wb") as out:
            while chunk := upload.file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"Файл больше {max_mb} МБ")
                out.write(chunk)
        if not size:
            raise HTTPException(400, "Пустой файл")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
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
    if kind == "circle":
        return _normalize_circle(ffmpeg, rel) if ffmpeg and src.exists() else rel
    if ffmpeg and src.exists() and kind == "video" and src.suffix in (".mp4", ".mov", ".m4v", ".3gp"):
        return _compatible_video(ffmpeg, rel)
    # mp4/mov с телефонов iPhone и так играет; перекодируем только webm/ogg
    if not ffmpeg or not src.exists() or src.suffix not in (".webm", ".ogg"):
        return rel
    new_rel = f"{rel.rsplit('.', 1)[0]}{target_ext}"
    dst = settings.media_dir / f"{new_rel}.tmp{target_ext}"
    if kind == "voice":
        codec = ["-vn", "-c:a", "aac", "-b:a", "96k"]
    else:
        codec = _h264_args(1920, crf=23, preset="faster", fps=_fps(_probe(src)))
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


def _normalize_circle(ffmpeg: str, rel: str) -> str:
    """Кружок из любого телефона — к одному виду, который показывается везде: H.264 Main, 480×480, ровно 30 кадров/с.
    Запись с камеры через canvas на iPhone даёт «плавающую» частоту кадров — на части айфонов такой ролик
    играет только звук на чёрном фоне. После перекодирования — нормальная картинка."""
    src = settings.media_dir / rel
    new_rel = f"{rel.rsplit('.', 1)[0]}.mp4"
    dst = settings.media_dir / f"{new_rel}.tmp.mp4"
    codec = ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p",
             "-profile:v", "main", "-level", "3.1",
             # out_range=tv + yuv420p: запись с canvas помечена «полным» диапазоном (yuvj420p) — такой H.264
             # аппаратный декодер iPhone иногда показывает чёрным при живом звуке. Приводим к обычному видео-диапазону
             "-vf", "scale=480:480:force_original_aspect_ratio=increase:out_range=tv,crop=480:480,fps=30,format=yuv420p",
             "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
             "-c:a", "aac", "-b:a", "96k", "-ar", "44100", "-movflags", "+faststart"]
    try:
        subprocess.run([ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-i", str(src), *codec, str(dst)],
                       check=True, timeout=180, capture_output=True)
    except (subprocess.SubprocessError, OSError) as exc:
        log.warning("Не удалось подготовить кружок %s: %s", rel, (getattr(exc, "stderr", None) or b"")[-300:] or exc)
        dst.unlink(missing_ok=True)
        return rel
    dst.replace(settings.media_dir / new_rel)
    if new_rel != rel:
        src.unlink(missing_ok=True)
    make_poster(new_rel)
    return new_rel


def circle_ok(rel: str) -> bool:
    """Кружок уже в общем виде (H.264, 480×480, обычный видео-диапазон yuv420p)? Тогда перекодировать не нужно."""
    probe = shutil.which("ffprobe")
    path = settings.media_dir / rel
    if not probe or not path.exists():
        return True
    try:
        out = subprocess.run([probe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,width,height,pix_fmt",
                              "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=30).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return True
    return out == "h264,480,480,yuv420p"


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


def poster_rel(rel: str) -> str:
    return f"{rel.rsplit('.', 1)[0]}.poster.jpg"


def make_poster(rel: str) -> None:
    """Первый кадр видео картинкой: в чате ролик сразу виден, а не серым квадратом (iPhone сам кадр не рисует)."""
    ffmpeg = shutil.which("ffmpeg")
    src = settings.media_dir / rel
    if not ffmpeg or not src.exists():
        return
    dst = settings.media_dir / poster_rel(rel)
    try:
        subprocess.run([ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-ss", "0.1", "-i", str(src), "-frames:v", "1",
                        "-vf", "scale=w='min(720,iw)':h=-2", "-q:v", "4", str(dst)], check=True, timeout=60, capture_output=True)
    except (subprocess.SubprocessError, OSError) as exc:
        log.warning("Не удалось сделать превью %s: %s", rel, exc)
        dst.unlink(missing_ok=True)


def delete_file(rel: str | None) -> None:
    if not rel:
        return
    if not rel.endswith(".poster.jpg"):
        delete_file(poster_rel(rel))  # превью видео уходит вместе с ним
    path = (settings.media_dir / rel).resolve()
    if settings.media_dir.resolve() in path.parents and path.exists():
        path.unlink()


def resolve(rel: str) -> Path | None:
    root = settings.media_dir.resolve()
    path = (root / rel).resolve()
    if root not in path.parents or not path.is_file():
        return None
    return path


# ---------- Видео, которое играет везде (в том числе на старых Android) ----------
# Самый совместимый вариант: H.264 Main, 8 бит (yuv420p), не больше 1080p и 30 кадров/с, звук AAC, индекс в начале файла.
# Чего не любят старые телефоны: HEVC (H.265) с iPhone, 10-битное HDR-видео, 4K, 60 кадров/с, звук Opus.
COMPAT_MAX_SIDE = 1920
HEAVY_BITRATE = 5_000_000  # выше — пережимаем «на глаз без потерь» (CRF 22), если файл станет заметно меньше


def _probe(path: Path) -> dict:
    """Что внутри видео: кодеки, размер, частота кадров, битрейт. Пусто — ffprobe нет или файл битый."""
    probe = shutil.which("ffprobe")
    if not probe:
        return {}
    try:
        out = subprocess.run([probe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
                             capture_output=True, text=True, timeout=60).stdout
        import json as _json

        return _json.loads(out or "{}")
    except (subprocess.SubprocessError, OSError, ValueError):
        return {}


def _stream(info: dict, kind: str) -> dict:
    return next((s for s in info.get("streams", []) if s.get("codec_type") == kind), {})


def _fps(info: dict) -> float:
    v = _stream(info, "video")
    for key in ("avg_frame_rate", "r_frame_rate"):
        num, _, den = (v.get(key) or "0/1").partition("/")
        try:
            if float(den or 1) and float(num) / float(den or 1) > 0:
                return float(num) / float(den or 1)
        except ValueError:
            continue
    return 0.0


def _h264_args(max_side: int, crf: int, preset: str, fps: float = 0.0, audio: bool = True, maxrate: str | None = None) -> list[str]:
    """Параметры ffmpeg для совместимого H.264. Ширина и высота — чётные (иначе x264 падает), без увеличения."""
    vf = f"scale=w='trunc(min({max_side},iw)/2)*2':h='trunc(min({max_side},ih)/2)*2':force_original_aspect_ratio=decrease:out_range=tv"
    vf += ",scale=trunc(iw/2)*2:trunc(ih/2)*2"  # после уменьшения стороны снова чётные
    if fps > 30.5:
        vf += ",fps=30"
    vf += ",format=yuv420p"
    args = ["-map", "0:v:0", "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-profile:v", "main",
            "-level", "4.0" if max_side > 1280 else "3.1", "-pix_fmt", "yuv420p", "-vf", vf,
            "-color_range", "tv", "-movflags", "+faststart", "-map_metadata", "-1"]
    if maxrate:  # потолок битрейта: ролик в анкете начинает играть быстро даже по мобильной сети
        args += ["-maxrate", maxrate, "-bufsize", f"{int(maxrate.rstrip('k')) * 2}k"]
    if audio:
        args = ["-map", "0:a:0?", *args, "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "44100"]
    else:
        args.append("-an")
    return args


def _video_problem(info: dict) -> str | None:
    """Почему ролик может не играть на части телефонов (None — играет везде)."""
    v, a = _stream(info, "video"), _stream(info, "audio")
    if not v:
        return "нет видео"
    if v.get("codec_name") != "h264":
        return f"кодек {v.get('codec_name')}"
    if v.get("pix_fmt") not in ("yuv420p", "yuvj420p"):
        return f"цвет {v.get('pix_fmt')}"  # 10-битное HDR и т. п.
    if max(int(v.get("width") or 0), int(v.get("height") or 0)) > COMPAT_MAX_SIDE:
        return "больше 1080p"
    if _fps(info) > 30.5:
        return "больше 30 кадров/с"
    if a and a.get("codec_name") not in ("aac", "mp3"):
        return f"звук {a.get('codec_name')}"
    return None


def video_ok(rel: str) -> bool:
    """Видео уже в формате, который играет везде? (Нет ffprobe или файла — считаем, что да: трогать нечего.)"""
    path = settings.media_dir / rel
    if path.suffix == ".webm":
        return False
    info = _probe(path) if path.exists() else {}
    return not info or _video_problem(info) is None


def _compatible_video(ffmpeg: str, rel: str) -> str:
    """Видео с телефона: если формат подходит всем — только переносим индекс в начало (без потери качества);
    если нет (HEVC, HDR, 4K, 60 к/с) — перекодируем в H.264; слишком «тяжёлое» — пережимаем, если станет заметно меньше."""
    src = settings.media_dir / rel
    info = _probe(src)
    problem = _video_problem(info) if info else None
    bitrate = int((info.get("format") or {}).get("bit_rate") or 0)
    if not info or (problem is None and bitrate <= HEAVY_BITRATE):
        _faststart(ffmpeg, src)
        return rel
    new_rel = f"{rel.rsplit('.', 1)[0]}.mp4"
    dst = settings.media_dir / f"{new_rel}.tmp.mp4"
    try:
        subprocess.run([ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-i", str(src),
                        *_h264_args(COMPAT_MAX_SIDE, crf=22, preset="faster", fps=_fps(info)), str(dst)],
                       check=True, timeout=900, capture_output=True)
    except (subprocess.SubprocessError, OSError) as exc:
        log.warning("Видео %s не перекодировалось (%s): %s", rel, problem or "сжатие", (getattr(exc, "stderr", None) or b"")[-300:] or exc)
        dst.unlink(missing_ok=True)
        _faststart(ffmpeg, src)
        return rel
    if problem is None and dst.stat().st_size > src.stat().st_size * 0.85:
        dst.unlink(missing_ok=True)  # сжатие почти ничего не дало — оставляем оригинал
        _faststart(ffmpeg, src)
        return rel
    log.info("Видео %s: %s → H.264, %d → %d КБ", rel, problem or "сжато", src.stat().st_size // 1024, dst.stat().st_size // 1024)
    dst.replace(settings.media_dir / new_rel)
    if new_rel != rel:
        src.unlink(missing_ok=True)
    return new_rel


CLIP_SECONDS = 15  # короткое видео в анкете: не длиннее 15 секунд (длиннее — берём первые 15)
CLIP_SOURCE_MAX_SECONDS = 60  # длиннее минуты не принимаем: человек ждал бы загрузку ради 15 секунд
CLIP_MAX_MB = 100


def is_clip(content_type: str | None, filename: str | None) -> bool:
    """GIF или видео (в анкету идут роликом), а не обычное фото."""
    ctype, name = (content_type or "").lower(), (filename or "").lower()
    return ctype.startswith("video/") or ctype == "image/gif" or name.endswith((".gif", ".mp4", ".mov", ".webm", ".m4v", ".3gp"))


def save_gallery_clip(upload: UploadFile, max_mb: int) -> str:
    """GIF или короткое видео для анкеты → MP4 (H.264, без звука, до 720 px, до 15 с), играет по кругу.
    Перекодирование убирает метаданные (в том числе координаты съёмки) и делает ролик лёгким."""
    if not shutil.which("ffmpeg"):
        raise HTTPException(415, "Видео и GIF сейчас не принимаются, добавьте фото")
    src_path, _ = _target("gallery", ".src")
    limit, size = max_mb * 1024 * 1024, 0
    try:
        with src_path.open("wb") as out:
            while chunk := upload.file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"Файл больше {max_mb} МБ")
                out.write(chunk)
    except BaseException:
        src_path.unlink(missing_ok=True)
        raise
    if not size:
        src_path.unlink(missing_ok=True)
        raise HTTPException(400, "Пустой файл")
    return clip_from_file(src_path)


def clip_from_file(src_path: Path) -> str:
    """Готовый файл на диске (загружен целиком или собран из частей) → ролик для анкеты. Исходник удаляется."""
    import subprocess as _sp

    ffmpeg = shutil.which("ffmpeg")
    try:
        if not ffmpeg:
            raise HTTPException(415, "Видео и GIF сейчас не принимаются, добавьте фото")
        info = _probe(src_path)
        duration = float((info.get("format") or {}).get("duration") or 0)
        if info and not _stream(info, "video"):
            raise HTTPException(415, "Это не видео и не GIF. Выберите другой файл")
        if duration > CLIP_SOURCE_MAX_SECONDS + 0.5:
            raise HTTPException(422, f"Видео длиннее {CLIP_SOURCE_MAX_SECONDS} секунд. Обрежьте его в галерее телефона "
                                     f"(в анкету попадут первые {CLIP_SECONDS} секунд) и выберите снова")
        dst, rel = _target("gallery", ".mp4")
        cmd = [ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-i", str(src_path), "-t", str(CLIP_SECONDS),
               *_h264_args(720, crf=23, preset="medium", fps=_fps(info), audio=False, maxrate="1500k"), str(dst)]
        try:
            _sp.run(cmd, check=True, timeout=180, capture_output=True)
        except (_sp.SubprocessError, OSError) as exc:
            dst.unlink(missing_ok=True)
            raise HTTPException(415, "Не получилось обработать видео. Попробуйте другой файл") from exc
        make_poster(rel)  # первый кадр картинкой: в профиле видно, что за ролик, даже если телефон не запускает видео сам
        return rel
    finally:
        src_path.unlink(missing_ok=True)
