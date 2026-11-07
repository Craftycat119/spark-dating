from app import config, emailer, outlook_oauth
from conftest import new_client


class FakeSMTP:
    sent = []

    def __init__(self, *a, **kw):
        self.auth_args = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, **kw):
        pass

    def ehlo(self):
        pass

    def auth(self, mech, obj, initial_response_ok=True):
        FakeSMTP.sent.append(("auth", mech, obj()))

    def login(self, user, pw):
        FakeSMTP.sent.append(("login", user, pw))

    def send_message(self, msg):
        FakeSMTP.sent.append(("send", msg["To"], msg["Subject"]))


def test_outlook_sends_with_xoauth2(monkeypatch):
    FakeSMTP.sent = []
    s = config.settings
    for k, v in {"smtp_host": "smtp-mail.outlook.com", "smtp_port": 587, "smtp_ssl": False, "smtp_auth": "outlook",
                 "smtp_user": "me@outlook.com", "smtp_from": "COFI <me@outlook.com>"}.items():
        monkeypatch.setattr(s, k, v)
    monkeypatch.setattr(emailer.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(outlook_oauth, "access_token", lambda: "TOKEN")
    assert emailer.send_code("x@y.ru", "123456", "verify")
    assert FakeSMTP.sent[0] == ("auth", "XOAUTH2", "user=me@outlook.com\x01auth=Bearer TOKEN\x01\x01")
    assert FakeSMTP.sent[1][0] == "send" and "123456" in FakeSMTP.sent[1][2]


def test_failed_email_shows_code_in_dev_and_errors_in_prod(monkeypatch):
    monkeypatch.setattr(config.settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(emailer, "send_email", lambda *a, **kw: False)
    c = new_client()
    r = c.post("/api/auth/register", json={"email": "f@x.io", "password": "Secret123"})
    assert r.status_code == 200 and r.json()["dev_code"]
    monkeypatch.setattr(config.settings, "dev_mode", False)
    r = c.post("/api/auth/register", json={"email": "g@x.io", "password": "Secret123"})
    assert r.status_code == 502
