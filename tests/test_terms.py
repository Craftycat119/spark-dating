import sqlite3

from app import database
from app.ages import birth_for_age
from conftest import make_user, new_client, register


def test_terms_and_age_confirmation_required():
    c = new_client()
    register(c, "t@x.io")
    base = {"name": "Аня", "birth_date": birth_for_age(25).isoformat(), "gender": "female", "looking_for": "any"}
    assert c.put("/api/profile", json={**base, "accept_terms": True, "confirm_age": False}).status_code == 422
    assert c.put("/api/profile", json={**base, "accept_terms": False, "confirm_age": True}).status_code == 422
    me = c.put("/api/profile", json={**base, "accept_terms": True, "confirm_age": True}).json()
    assert me["terms_accepted"] and me["age_confirmation"] == "adult"


def test_teen_confirms_guardian_consent():
    c = new_client()
    register(c, "kid@x.io")
    me = c.put("/api/profile", json={"name": "Миша", "birth_date": birth_for_age(13).isoformat(), "gender": "male",
                                     "looking_for": "any", "accept_terms": True, "confirm_age": True}).json()
    assert me["age_confirmation"] == "guardian"


def test_feed_requires_current_terms(monkeypatch):
    c = make_user("f@x.io")
    assert c.get("/api/feed").status_code == 200
    monkeypatch.setattr("app.routers.feed.TERMS_VERSION", "новая-редакция")
    r = c.get("/api/feed")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "terms_required"


def test_old_database_gets_new_columns(tmp_path, monkeypatch):
    """Старая база без новых колонок обновляется при запуске, данные сохраняются."""
    from sqlalchemy import create_engine, inspect

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name VARCHAR(64))")
    con.execute("INSERT INTO users (name) VALUES ('Старый')")
    con.commit()
    con.close()
    eng = create_engine(f"sqlite:///{path}")
    monkeypatch.setattr(database, "engine", eng)
    database._add_missing_columns()
    cols = {c["name"] for c in inspect(eng).get_columns("users")}
    assert {"terms_accepted_at", "terms_version", "age_confirmation", "is_demo", "birth_date"} <= cols
    with eng.connect() as conn:
        assert conn.exec_driver_sql("SELECT name, is_demo FROM users").fetchone() == ("Старый", 0)
