"""Отправка писем с личного ящика Outlook.com / Hotmail через OAuth2.

С сентября 2024 Microsoft не принимает SMTP с паролем (даже паролем приложения) для личных ящиков,
нужен вход через Microsoft. Один раз выполните `python -m app.cli outlook-login`: команда покажет код,
вы введёте его на microsoft.com/devicelogin и разрешите отправку писем. Токен обновления сохраняется
в data/outlook_token.json, дальше сервер сам получает свежие токены доступа.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import settings

AUTHORITY = "https://login.microsoftonline.com/consumers/oauth2/v2.0"
SCOPE = "https://outlook.office.com/SMTP.Send offline_access"
TOKEN_FILE = settings.data_dir / "outlook_token.json"

_cache: dict = {}


class OutlookAuthError(RuntimeError):
    pass


def _post(url: str, data: dict) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode())
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as ex:
        return json.loads(ex.read() or b"{}")


def _save(tok: dict) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps({"refresh_token": tok["refresh_token"]}), encoding="utf-8")


def access_token() -> str:
    """Свежий токен доступа для SMTP (кешируется до истечения)."""
    if _cache.get("token") and _cache["expires"] > time.time() + 60:
        return _cache["token"]
    if not settings.outlook_client_id:
        raise OutlookAuthError("Не задан OUTLOOK_CLIENT_ID в .env")
    if not TOKEN_FILE.exists():
        raise OutlookAuthError("Почта Outlook не подключена: выполните python -m app.cli outlook-login")
    refresh = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))["refresh_token"]
    tok = _post(f"{AUTHORITY}/token", {"client_id": settings.outlook_client_id, "grant_type": "refresh_token",
                                       "refresh_token": refresh, "scope": SCOPE})
    if "access_token" not in tok:
        raise OutlookAuthError(f"Microsoft не выдал токен: {tok.get('error_description') or tok.get('error')}. "
                               "Повторите python -m app.cli outlook-login")
    if tok.get("refresh_token"):
        _save(tok)
    _cache.update(token=tok["access_token"], expires=time.time() + int(tok.get("expires_in", 3600)))
    return tok["access_token"]


def login_interactive() -> None:
    """Вход по коду устройства: для командной строки, браузер нужен только чтобы ввести код."""
    if not settings.outlook_client_id:
        raise SystemExit("Сначала укажите OUTLOOK_CLIENT_ID в .env (как его получить, написано в README, раздел «Почта»)")
    flow = _post(f"{AUTHORITY}/devicecode", {"client_id": settings.outlook_client_id, "scope": SCOPE})
    if "device_code" not in flow:
        raise SystemExit(f"Microsoft отклонил запрос: {flow.get('error_description') or flow}")
    print(f"\n1. Откройте {flow['verification_uri']}\n2. Введите код: {flow['user_code']}\n"
          f"3. Войдите как {settings.smtp_user or 'владелец ящика'} и разрешите отправку писем\n\nЖду подтверждения…", flush=True)
    interval = int(flow.get("interval", 5))
    deadline = time.time() + int(flow.get("expires_in", 900))
    while time.time() < deadline:
        time.sleep(interval)
        tok = _post(f"{AUTHORITY}/token", {"client_id": settings.outlook_client_id, "device_code": flow["device_code"],
                                           "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        if "refresh_token" in tok:
            _save(tok)
            print(f"Готово: почта подключена, токен сохранён в {TOKEN_FILE}")
            return
        if tok.get("error") == "slow_down":
            interval += 5
        elif tok.get("error") != "authorization_pending":
            raise SystemExit(f"Не получилось: {tok.get('error_description') or tok.get('error')}")
    raise SystemExit("Время на вход вышло, запустите команду ещё раз")
