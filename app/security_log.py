"""Журнал подозрительной активности и оповещения администрации.

Каждое событие (неудачный вход, срабатывание лимита, проваленная капча) пишется в журнал сервера с адресом.
Если за 10 минут набирается много событий, бот присылает администрации сводку: что происходит и с каких адресов.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import Counter, deque

log = logging.getLogger("cofi.security")

WINDOW = 600  # секунд
THRESHOLD = 50  # столько событий за окно — повод для оповещения
ALERT_PAUSE = 1800  # не чаще раза в 30 минут
_events: deque[tuple[float, str, str]] = deque()
_last_alert = 0.0
_lock = threading.Lock()


def event(kind: str, source: str, detail: str = "") -> None:
    """kind — что случилось, source — IP или почта, detail — подробности для журнала."""
    global _last_alert
    log.warning("Подозрительно: %s — %s%s", kind, source, f" ({detail})" if detail else "")
    now = time.time()
    with _lock:
        _events.append((now, kind, source))
        while _events and now - _events[0][0] > WINDOW:
            _events.popleft()
        if len(_events) < THRESHOLD or now - _last_alert < ALERT_PAUSE:
            return
        _last_alert = now
        kinds = Counter(k for _, k, _ in _events)
        sources = Counter(s for _, _, s in _events).most_common(5)
    text = (f"🚨 COFI: подозрительная активность — {sum(kinds.values())} событий за {WINDOW // 60} минут\n\n"
            + "\n".join(f"• {k}: {n}" for k, n in kinds.most_common())
            + "\n\nЧаще всего:\n" + "\n".join(f"• {s} — {n}" for s, n in sources)
            + "\n\nПодробности: журнал сервера (journalctl -u cofi | grep Подозрительно)")
    threading.Thread(target=_alert, args=(text,), daemon=True).start()


def _alert(text: str) -> None:
    from . import push
    from .database import SessionLocal

    if not push.enabled():
        log.error(text)
        return
    with SessionLocal() as db:
        for chat in push.admin_chats(db):
            push._send(chat, text)
