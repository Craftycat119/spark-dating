"""Проверка фото на фейк: сопоставление лица на фото профиля с живым лицом с камеры.

Используются нейросети OpenCV:
  * YuNet  — находит лицо и 5 ключевых точек (глаза, нос, уголки рта);
  * SFace  — строит «отпечаток» лица (вектор 128 чисел) для сравнения.

Сканер присылает три кадра: «смотрите прямо», «поверните голову в одну сторону»,
«в другую». Проверка проходит, только если:
  1. на каждом кадре ровно одно лицо;
  2. каждый кадр похож на фото профиля (косинусная близость ≥ порога);
  3. голова действительно поворачивалась (нос смещается относительно глаз
     в разные стороны) — так нельзя пройти проверку, поднеся к камере чужую фотографию.
"""
from __future__ import annotations

import base64
import logging
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import settings

log = logging.getLogger("spark.face")

MODELS = {
    "face_detection_yunet_2023mar.onnx": "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "face_recognition_sface_2021dec.onnx": "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
}
MAX_SIDE = 800
REQUIRED_POSES = ("center", "left", "right")


class FaceError(Exception):
    """Понятная пользователю ошибка проверки."""


@dataclass
class VerifyResult:
    ok: bool
    score: float
    reason: str = ""


def download_models(models_dir: Path | None = None) -> None:
    models_dir = models_dir or settings.face_models_dir
    models_dir.mkdir(parents=True, exist_ok=True)
    for name, url in MODELS.items():
        target = models_dir / name
        if target.exists() and target.stat().st_size > 100_000:
            continue
        log.info("Скачиваю модель %s ...", name)
        tmp = target.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.rename(target)


def decode_image(data: bytes | str):
    """Принимает байты файла или data:URL, возвращает BGR-изображение (уменьшенное)."""
    import cv2

    if isinstance(data, str):
        if "," in data[:100]:
            data = data.split(",", 1)[1]
        try:
            data = base64.b64decode(data, validate=False)
        except ValueError as exc:
            raise FaceError("Не удалось прочитать кадр") from exc
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise FaceError("Не удалось прочитать изображение")
    h, w = img.shape[:2]
    scale = MAX_SIDE / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return img


class FaceEngine:
    def __init__(self, models_dir: Path):
        self.models_dir = models_dir
        self._detector = None
        self._recognizer = None

    def _load(self):
        import cv2

        if self._detector is None:
            det = self.models_dir / "face_detection_yunet_2023mar.onnx"
            rec = self.models_dir / "face_recognition_sface_2021dec.onnx"
            if not det.exists() or not rec.exists():
                download_models(self.models_dir)
            self._detector = cv2.FaceDetectorYN.create(str(det), "", (320, 320), 0.8, 0.3, 5000)
            self._recognizer = cv2.FaceRecognizerSF.create(str(rec), "")

    def detect(self, img) -> np.ndarray:
        """Возвращает массив лиц (строки по 15 чисел YuNet), самые крупные — первыми."""
        self._load()
        h, w = img.shape[:2]
        self._detector.setInputSize((w, h))
        _, faces = self._detector.detect(img)
        if faces is None:
            return np.zeros((0, 15), dtype=np.float32)
        order = np.argsort(-(faces[:, 2] * faces[:, 3]))
        return faces[order]

    def feature(self, img, face) -> np.ndarray:
        self._load()
        aligned = self._recognizer.alignCrop(img, face)
        return self._recognizer.feature(aligned)

    def similarity(self, f1, f2) -> float:
        import cv2

        self._load()
        return float(self._recognizer.match(f1, f2, cv2.FaceRecognizerSF_FR_COSINE))


def yaw(face) -> float:
    """Поворот головы: смещение носа относительно середины между глазами, в долях межглазья."""
    rx, lx, nose_x = float(face[4]), float(face[6]), float(face[8])
    eye_dist = abs(lx - rx) or 1.0
    return (nose_x - (rx + lx) / 2) / eye_dist


def main_face(engine, img, what: str):
    faces = engine.detect(img)
    if len(faces) == 0:
        raise FaceError(f"На {what} не найдено лицо")
    if len(faces) > 1 and faces[1][2] * faces[1][3] > 0.35 * faces[0][2] * faces[0][3]:
        raise FaceError(f"На {what} несколько лиц — нужно, чтобы было только ваше")
    return faces[0]


def check_profile_photo(engine, img) -> None:
    main_face(engine, img, "фото")


def verify_frames(engine, photo_img, frames: dict[str, object]) -> VerifyResult:
    """Сверяет кадры со сканера (center/left/right) с фото профиля."""
    missing = [p for p in REQUIRED_POSES if p not in frames]
    if missing:
        return VerifyResult(False, 0.0, "Сканирование не завершено — повторите все шаги")

    try:
        photo_face = main_face(engine, photo_img, "фото профиля")
        photo_feat = engine.feature(photo_img, photo_face)

        scores, yaws = [], {}
        for pose in REQUIRED_POSES:
            img = frames[pose]
            face = main_face(engine, img, "кадре с камеры")
            scores.append(engine.similarity(photo_feat, engine.feature(img, face)))
            yaws[pose] = yaw(face)
    except FaceError as exc:
        return VerifyResult(False, 0.0, str(exc))

    score = float(np.mean(scores))
    threshold = settings.face_match_threshold
    if min(scores) < threshold * 0.85 or score < threshold:
        return VerifyResult(False, score, "Лицо на камере не совпадает с лицом на фото")

    dl = yaws["left"] - yaws["center"]
    dr = yaws["right"] - yaws["center"]
    t = settings.face_yaw_threshold
    if not (abs(dl) >= t and abs(dr) >= t and dl * dr < 0):
        return VerifyResult(False, score, "Не удалось подтвердить, что перед камерой живой человек — поверните голову сильнее")

    return VerifyResult(True, score)


_engine: FaceEngine | None = None


def get_engine() -> FaceEngine:
    global _engine
    if _engine is None:
        _engine = FaceEngine(settings.face_models_dir)
    return _engine


def is_dev_mode() -> bool:
    """FACE_MODE=dev: проверка всегда проходит. Только для локальной разработки!"""
    return settings.face_mode == "dev"


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) > 1 and sys.argv[1] == "download":
        download_models()
        print("Модели скачаны в", settings.face_models_dir)
