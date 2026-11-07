"""WebSocket-соединения: новые сообщения, уведомления о метчах, сигналинг звонков."""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict

import anyio
from anyio.from_thread import run as run_from_thread
from fastapi import WebSocket

log = logging.getLogger("spark.ws")


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: dict[int, set[WebSocket]] = defaultdict(set)
        self.hidden: set[WebSocket] = set()  # вкладка или мини-приложение свёрнуты (сообщает страница)

    async def connect(self, user_id: int, ws: WebSocket) -> None:
        await ws.accept()
        self.connections[user_id].add(ws)

    def disconnect(self, user_id: int, ws: WebSocket) -> None:
        self.connections[user_id].discard(ws)
        self.hidden.discard(ws)
        if not self.connections[user_id]:
            self.connections.pop(user_id, None)

    def is_online(self, user_id: int) -> bool:
        return bool(self.connections.get(user_id))

    def set_visible(self, ws: WebSocket, visible: bool) -> None:
        (self.hidden.discard if visible else self.hidden.add)(ws)

    def is_active(self, user_id: int) -> bool:
        """Есть хотя бы одна открытая и видимая на экране вкладка COFI."""
        return any(ws not in self.hidden for ws in self.connections.get(user_id, ()))

    async def send(self, user_id: int, payload: dict) -> None:
        text = json.dumps(payload, ensure_ascii=False, default=str)
        for ws in list(self.connections.get(user_id, ())):
            try:
                await ws.send_text(text)
            except Exception:  # noqa: BLE001 — соединение уже закрыто
                self.disconnect(user_id, ws)


manager = ConnectionManager()
_loop: asyncio.AbstractEventLoop | None = None


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Запоминаем цикл событий сервера: из потока Telegram-бота события шлём через него."""
    global _loop
    _loop = loop


def notify(user_id: int, payload: dict) -> None:
    """Отправить событие из синхронного обработчика (FastAPI выполняет их в пуле потоков)."""
    try:
        run_from_thread(manager.send, user_id, payload)
    except RuntimeError:
        # Вызов не из рабочего потока anyio (например, из уже асинхронного кода)
        try:
            asyncio.get_running_loop().create_task(manager.send(user_id, payload))
        except RuntimeError:
            if _loop and _loop.is_running():  # чужой поток, например Telegram-бот
                asyncio.run_coroutine_threadsafe(manager.send(user_id, payload), _loop)
            else:
                log.debug("Нет event loop для уведомления пользователя %s", user_id)
    except anyio.get_cancelled_exc_class():
        pass
