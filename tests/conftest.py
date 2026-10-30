import io
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="spark-test-")
os.environ["DATA_DIR"] = _tmp
os.environ["FACE_MODE"] = "dev"
os.environ["DEV_MODE"] = "1"
os.environ["SMTP_HOST"] = ""
os.environ["ADMIN_EMAILS"] = "boss@example.com"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


def jpeg_bytes(color="red") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, "JPEG")
    return buf.getvalue()


def new_client() -> TestClient:
    return TestClient(app)


def register(client, email, password="Secret123"):
    r = client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    r = client.post("/api/auth/verify-email", json={"email": email, "code": r.json()["dev_code"]})
    assert r.status_code == 200, r.text
    return r.json()


DEFAULT_INTERESTS = ("Кофейни", "Бег", "Техно")


def make_user(email, name="Тест", lat=55.75, lon=37.61, age=25, bio="Привет", gender="female",
              looking_for="any", interests=DEFAULT_INTERESTS, goals=("Свидания",)):
    c = new_client()
    register(c, email)
    r = c.put("/api/profile", json={"name": name, "age": age, "bio": bio, "gender": gender,
                                    "looking_for": looking_for, "interests": list(interests), "goals": list(goals)})
    assert r.status_code == 200, r.text
    r = c.post("/api/profile/photo", files={"file": ("a.jpg", jpeg_bytes(), "image/jpeg")})
    assert r.status_code == 200, r.text
    r = c.post("/api/profile/verify-face", json={"frames": {"center": "data:image/jpeg;base64,AAAA"}})
    assert r.json()["ok"], r.text
    assert c.post("/api/profile/location", json={"lat": lat, "lon": lon}).status_code == 200
    c.user_id = c.get("/api/auth/me").json()["id"]
    return c
