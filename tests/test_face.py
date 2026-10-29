import numpy as np

from app.face_verify import verify_frames


def face(nose_x, size=100):
    # x, y, w, h, правый глаз(x,y), левый глаз(x,y), нос(x,y), рот..., score
    f = np.zeros(15, dtype=np.float32)
    f[2] = f[3] = size
    f[4], f[6], f[8] = 40, 60, nose_x
    f[14] = 0.99
    return f


class FakeEngine:
    """Изображение — это словарь {'faces': [...], 'person': 'id'}."""

    def detect(self, img):
        return np.array(img["faces"]) if img["faces"] else np.zeros((0, 15))

    def feature(self, img, _face):
        return img["person"]

    def similarity(self, a, b):
        return 0.9 if a == b else 0.1


def img(person, *faces):
    return {"person": person, "faces": list(faces)}


PHOTO = img("anna", face(50))


def test_live_person_passes():
    frames = {"center": img("anna", face(50)), "left": img("anna", face(42)), "right": img("anna", face(58))}
    assert verify_frames(FakeEngine(), PHOTO, frames).ok


def test_other_person_fails():
    frames = {"center": img("bob", face(50)), "left": img("bob", face(42)), "right": img("bob", face(58))}
    r = verify_frames(FakeEngine(), PHOTO, frames)
    assert not r.ok and "не совпадает" in r.reason


def test_printed_photo_without_head_turn_fails():
    frames = {p: img("anna", face(50)) for p in ("center", "left", "right")}
    r = verify_frames(FakeEngine(), PHOTO, frames)
    assert not r.ok and "живой" in r.reason


def test_no_face_and_multiple_faces():
    assert "не найдено" in verify_frames(FakeEngine(), img("anna"), {"center": 1, "left": 1, "right": 1}).reason
    two = {"center": img("anna", face(50), face(50)), "left": img("anna", face(42)), "right": img("anna", face(58))}
    assert "несколько" in verify_frames(FakeEngine(), PHOTO, two).reason


def test_missing_pose():
    assert not verify_frames(FakeEngine(), PHOTO, {"center": img("anna", face(50))}).ok
