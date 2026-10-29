"""Проверка настоящих нейросетей OpenCV. Пропускается, если модели не скачаны
(python -m app.cli download-models) или нет тестовой картинки из scikit-image."""
import cv2
import numpy as np
import pytest

from app.config import settings
from app.face_verify import FaceEngine, FaceError, check_profile_photo, verify_frames

models = settings.face_models_dir
if not (models / "face_recognition_sface_2021dec.onnx").exists():
    pytest.skip("модели не скачаны", allow_module_level=True)
skdata = pytest.importorskip("skimage.data")


@pytest.fixture(scope="module")
def engine():
    return FaceEngine(models)


@pytest.fixture(scope="module")
def face_img():
    return cv2.cvtColor(skdata.astronaut(), cv2.COLOR_RGB2BGR)


def test_photo_without_face_rejected(engine):
    blank = np.full((400, 300, 3), 120, dtype=np.uint8)
    with pytest.raises(FaceError):
        check_profile_photo(engine, blank)


def test_same_face_matches_but_static_photo_fails_liveness(engine, face_img):
    check_profile_photo(engine, face_img)
    res = verify_frames(engine, face_img, {"center": face_img, "left": face_img, "right": face_img})
    assert res.score > 0.8  # лицо совпало
    assert not res.ok and "живой" in res.reason  # но голова не поворачивалась


def test_different_face_does_not_match(engine, face_img):
    other = cv2.cvtColor(skdata.camera(), cv2.COLOR_GRAY2BGR)  # фотограф с камерой
    res = verify_frames(engine, face_img, {"center": other, "left": other, "right": other})
    assert not res.ok
