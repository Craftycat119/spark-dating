from fastapi.testclient import TestClient

from app.main import app


def test_register_again_after_back_goes_to_code_screen():
    with TestClient(app) as c:
        r1 = c.post("/api/auth/register", json={"email": "back@example.com", "password": "Secret123"})
        assert r1.status_code == 200
        r2 = c.post("/api/auth/register", json={"email": "back@example.com", "password": "Secret123"})
        assert r2.status_code == 200 and r2.json()["status"] == "code_pending"
        code = r1.json()["dev_code"]
        assert c.post("/api/auth/verify-email", json={"email": "back@example.com", "code": code}).status_code == 200
