"""Ограничение частоты запросов: защита от подбора паролей и кодов, спама письмами и регистрациями.
Счётчики в памяти процесса (одного сервера uvicorn достаточно); после перезапуска обнуляются."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_hits: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()


def hit(key: str, limit: int, window: int) -> None:
    """Засчитать попытку. Больше limit за window секунд — 429."""
    now = time.monotonic()
    with _lock:
        q = _hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(_hits) > 50000:  # раз в долгое время чистим ключи, по которым давно не было попыток
            for k in [k for k, v in _hits.items() if not v or now - v[-1] > 3600]:
                del _hits[k]
            q = _hits[key]
        if len(q) >= limit:
            from .security_log import event

            event("сработал лимит запросов", key.split(":", 1)[-1], key.split(":", 1)[0])
            wait = int(window - (now - q[0])) + 1
            raise HTTPException(429, f"Слишком много попыток. Попробуйте через {max(1, wait // 60) if wait >= 60 else wait} {'мин' if wait >= 60 else 'с'}")
        q.append(now)


def ip_of(request: Request) -> str:
    return request.client.host if request.client else "?"


def by_ip(request: Request, action: str, limit: int, window: int) -> None:
    hit(f"{action}:ip:{ip_of(request)}", limit, window)


def reset(key: str) -> None:
    with _lock:
        _hits.pop(key, None)


def is_local_request(request: Request) -> bool:
    """Запрос с этого же компьютера напрямую, а не через туннель или прокси.
    Только таким показываем код подтверждения на экране в режиме разработки."""
    host = (request.url.hostname or "").lower()
    forwarded = any(h in request.headers for h in ("x-forwarded-for", "cf-connecting-ip", "forwarded", "x-real-ip"))
    return not forwarded and host in ("localhost", "127.0.0.1", "::1", "testserver") and ip_of(request) in ("127.0.0.1", "::1", "testclient")
