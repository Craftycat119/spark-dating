from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .. import demo, storage
from ..config import settings
from ..database import SessionLocal, get_db
from ..deps import COOKIE_NAME, current_user, user_from_token
from ..models import Conversation, Message, User, utcnow
from ..realtime import manager, notify
from ..serializers import conversation_out, message_out, photo_url

router = APIRouter(prefix="/api/chats", tags=["chat"])
ws_router = APIRouter()
log = logging.getLogger("spark.chat")

MEDIA_KINDS = {"image", "video", "voice", "circle"}
CALL_EVENTS = {"call:offer", "call:answer", "call:ice", "call:end", "call:reject", "call:busy"}


class MessageIn(BaseModel):
    kind: str = "text"
    text: str = Field("", max_length=4000)


def get_conversation(db: Session, conv_id: int, user: User) -> Conversation:
    conv = db.get(Conversation, conv_id)
    if not conv or not conv.has(user.id) or not conv.active:
        raise HTTPException(404, "Чат не найден")
    return conv


def _publish(conv: Conversation, msg: Message) -> None:
    payload = {"type": "message", "message": message_out(msg)}
    notify(conv.user_a_id, payload)
    notify(conv.user_b_id, payload)


def _store(db: Session, conv: Conversation, msg: Message) -> Message:
    db.add(msg)
    conv.last_message_at = utcnow()
    db.commit()
    db.refresh(msg)
    return msg


@router.get("")
def list_chats(user: User = Depends(current_user), db: Session = Depends(get_db)):
    convs = db.scalars(
        select(Conversation).where(
            Conversation.active.is_(True),
            or_(Conversation.user_a_id == user.id, Conversation.user_b_id == user.id),
        )
    ).unique().all()
    result = []
    for c in convs:
        last = db.scalar(select(Message).where(Message.conversation_id == c.id).order_by(Message.id.desc()).limit(1))
        unread = db.scalar(
            select(func.count(Message.id)).where(
                Message.conversation_id == c.id, Message.sender_id != user.id, Message.read_at.is_(None)
            )
        )
        result.append(conversation_out(c, user.id, last, unread or 0, manager.is_online(c.other(user.id).id)))
    result.sort(key=lambda x: (x["last_message"] or {}).get("created_at") or x["created_at"], reverse=True)
    return result


@router.get("/{conv_id}")
def get_chat(conv_id: int, before_id: int | None = None, limit: int = 50, user: User = Depends(current_user), db: Session = Depends(get_db)):
    conv = get_conversation(db, conv_id, user)
    q = select(Message).where(Message.conversation_id == conv.id)
    if before_id:
        q = q.where(Message.id < before_id)
    rows = db.scalars(q.order_by(Message.id.desc()).limit(max(1, min(limit, 100)))).all()
    other = conv.other(user.id)
    return {
        "id": conv.id,
        "user": {
            "id": other.id,
            "name": other.name,
            "age": other.age,
            "bio": other.bio,
            "photo_url": photo_url(other),
            "online": manager.is_online(other.id),
        },
        "messages": [message_out(m) for m in reversed(rows)],
    }


def _maybe_bot_reply(conv: Conversation, user: User, background: BackgroundTasks) -> None:
    other = conv.other(user.id)
    if other.is_bot and user.is_demo:
        background.add_task(demo.bot_reply, conv.id, other.id)


@router.post("/{conv_id}/messages")
def send_message(conv_id: int, data: MessageIn, background: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    conv = get_conversation(db, conv_id, user)
    if data.kind not in {"text", "sticker"}:
        raise HTTPException(422, "Неизвестный тип сообщения")
    text = data.text.strip()
    if not text:
        raise HTTPException(422, "Пустое сообщение")
    if data.kind == "sticker" and len(text) > 64:
        raise HTTPException(422, "Некорректный стикер")
    msg = _store(db, conv, Message(conversation_id=conv.id, sender_id=user.id, kind=data.kind, text=text))
    _publish(conv, msg)
    _maybe_bot_reply(conv, user, background)
    return message_out(msg)


@router.post("/{conv_id}/media")
def send_media(
    conv_id: int,
    background: BackgroundTasks,
    kind: str = Form(...),
    duration: float | None = Form(None),
    caption: str = Form("", max_length=1000),
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    conv = get_conversation(db, conv_id, user)
    if kind not in MEDIA_KINDS:
        raise HTTPException(422, "Неизвестный тип файла")
    folder = f"chat/{conv.id}"
    if kind == "image":
        rel = storage.save_image(storage.read_limited(file, settings.max_image_mb), folder)
    else:
        data = storage.read_limited(file, settings.max_video_mb)
        rel = storage.save_media(data, file.content_type or "", folder, kind)
    msg = _store(
        db,
        conv,
        Message(conversation_id=conv.id, sender_id=user.id, kind=kind, text=caption.strip(), media_path=rel, duration=duration),
    )
    _publish(conv, msg)
    _maybe_bot_reply(conv, user, background)
    return message_out(msg)


@router.post("/{conv_id}/read")
def mark_read(conv_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    conv = get_conversation(db, conv_id, user)
    now = utcnow()
    changed = 0
    for m in db.scalars(
        select(Message).where(Message.conversation_id == conv.id, Message.sender_id != user.id, Message.read_at.is_(None))
    ):
        m.read_at = now
        changed += 1
    db.commit()
    if changed:
        notify(conv.other(user.id).id, {"type": "read", "conversation_id": conv.id})
    return {"status": "ok", "marked": changed}


@router.delete("/{conv_id}")
def unmatch(conv_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    conv = get_conversation(db, conv_id, user)
    conv.active = False
    db.commit()
    notify(conv.other(user.id).id, {"type": "unmatch", "conversation_id": conv.id})
    return {"status": "ok"}


# ---------- WebSocket: события в реальном времени и сигналинг звонков ----------

def _ws_user(token: str | None) -> tuple[int, str] | None:
    with SessionLocal() as db:
        user = user_from_token(db, token)
        return (user.id, user.name) if user else None


def _peer(conv_id: int, user_id: int) -> tuple[int, bool] | None:
    with SessionLocal() as db:
        conv = db.get(Conversation, conv_id)
        if not conv or not conv.has(user_id) or not conv.active:
            return None
        other = conv.other(user_id)
        return other.id, other.is_bot


def _log_call(conv_id: int, user_id: int, video: bool) -> dict:
    with SessionLocal() as db:
        conv = db.get(Conversation, conv_id)
        msg = _store(db, conv, Message(conversation_id=conv_id, sender_id=user_id, kind="call", text="video" if video else "audio"))
        return message_out(msg)


@ws_router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    who = await run_in_threadpool(_ws_user, ws.cookies.get(COOKIE_NAME))
    if not who:
        await ws.close(code=4401)
        return
    user_id, user_name = who
    await manager.connect(user_id, ws)
    peers: dict[int, tuple[int, bool] | None] = {}
    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            kind = data.get("type")
            if kind == "ping":
                await ws.send_text('{"type":"pong"}')
                continue
            if kind not in CALL_EVENTS and kind != "typing":
                continue
            try:
                conv_id = int(data.get("conversation_id"))
            except (TypeError, ValueError):
                continue
            if conv_id not in peers:
                peers[conv_id] = await run_in_threadpool(_peer, conv_id, user_id)
            if peers[conv_id] is None:
                continue
            peer, peer_is_bot = peers[conv_id]

            out = {k: v for k, v in data.items() if k in {"type", "conversation_id", "sdp", "candidate", "video", "call_id", "reason"}}
            out["from"] = {"id": user_id, "name": user_name}

            if kind == "call:offer":
                if peer_is_bot or not manager.is_online(peer):
                    await ws.send_text(json.dumps({
                        "type": "call:unavailable", "conversation_id": conv_id, "call_id": data.get("call_id"),
                        "reason": "bot" if peer_is_bot else "offline",
                    }))
                    continue
                msg = await run_in_threadpool(_log_call, conv_id, user_id, bool(data.get("video")))
                for uid in (user_id, peer):
                    await manager.send(uid, {"type": "message", "message": msg})
            await manager.send(peer, out)
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(user_id, ws)
