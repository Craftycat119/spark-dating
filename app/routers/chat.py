from __future__ import annotations

import json
import logging
import time
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .. import blocks, demo, push, storage
from ..config import settings
from ..database import SessionLocal, get_db
from ..deps import COOKIE_NAME, current_user, user_from_token
from ..models import Conversation, Message, User, utcnow
from ..ratelimit import hit
from ..realtime import manager, notify
from ..serializers import conversation_out, message_out, photo_url

router = APIRouter(prefix="/api/chats", tags=["chat"])
ws_router = APIRouter()
log = logging.getLogger("spark.chat")

MEDIA_KINDS = {"image", "video", "voice", "circle"}
MEDIA_PREVIEW = {"image": "📷 Фото", "video": "🎬 Видео", "voice": "🎤 Голосовое сообщение", "circle": "⭕ Видеосообщение"}
PEER_TTL = 15  # секунд: как часто WebSocket заново проверяет, можно ли писать собеседнику
CALL_EVENTS = {"call:offer", "call:answer", "call:ice", "call:end", "call:reject", "call:busy", "call:join"}


class MessageIn(BaseModel):
    kind: str = "text"
    text: str = Field("", max_length=4000)


def get_conversation(db: Session, conv_id: int, user: User) -> Conversation:
    conv = db.get(Conversation, conv_id)
    if not conv or not conv.has(user.id) or not conv.active:
        raise HTTPException(404, "Чат не найден")
    if conv.other(user.id).age_group != user.age_group:
        raise HTTPException(404, "Чат не найден")  # кто-то сменил возрастную группу: переписка закрыта
    if blocks.between(db, user.id, conv.other(user.id).id):
        raise HTTPException(404, "Чат недоступен")  # чёрный список: переписки не видно и писать нельзя
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
    hidden = blocks.hidden_ids(db, user.id)
    for c in convs:
        if c.other(user.id).age_group != user.age_group or c.other(user.id).id in hidden:
            continue
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
            "age": other.years,
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
    hit(f"msg:{user.id}", 30, 60)  # не больше 30 сообщений в минуту
    if data.kind not in {"text", "sticker"}:
        raise HTTPException(422, "Неизвестный тип сообщения")
    text = data.text.strip()
    if not text:
        raise HTTPException(422, "Пустое сообщение")
    if data.kind == "sticker" and len(text) > 64:
        raise HTTPException(422, "Некорректный стикер")
    msg = _store(db, conv, Message(conversation_id=conv.id, sender_id=user.id, kind=data.kind, text=text))
    _publish(conv, msg)
    push.notify_message(conv.other(user.id), user.name, conv.id, "Стикер" if data.kind == "sticker" else text)
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
    hit(f"media:{user.id}", 40, 600)  # не больше 40 файлов за 10 минут: диск сервера не заполнить
    if kind not in MEDIA_KINDS:
        raise HTTPException(422, "Неизвестный тип файла")
    folder = f"chat/{conv.id}"
    if kind == "image" and storage.media_type(file.content_type, file.filename).startswith("video/"):
        kind = "video"  # телефон прислал ролик как «фото» — отправим как видео
    if kind == "image":
        rel = storage.save_image(storage.read_limited(file, settings.max_image_mb), folder)
    else:
        rel = storage.save_media_stream(file, folder, kind, settings.max_video_mb)
        rel = storage.to_playable(rel, kind)  # webm → mp4/m4a, иначе на iPhone не играет
        if kind == "video":
            storage.make_poster(rel)
    msg = _store(
        db,
        conv,
        Message(conversation_id=conv.id, sender_id=user.id, kind=kind, text=caption.strip(), media_path=rel, duration=duration),
    )
    _publish(conv, msg)
    push.notify_message(conv.other(user.id), user.name, conv.id, MEDIA_PREVIEW[kind] + (f": {caption.strip()}" if caption.strip() else ""))
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
        if other.age_group != conv.other(other.id).age_group or blocks.between(db, user_id, other.id):
            return None
        return other.id, other.is_bot


def _offer_call(call: push.PendingCall) -> bool:
    with SessionLocal() as db:
        callee = db.get(User, call.callee_id)
        return push.offer(call, callee) if callee else False


def _log_call(conv_id: int, user_id: int, video: bool) -> dict:
    with SessionLocal() as db:
        conv = db.get(Conversation, conv_id)
        msg = _store(db, conv, Message(conversation_id=conv_id, sender_id=user_id, kind="call", text="video" if video else "audio"))
        return message_out(msg)


@ws_router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    origin = ws.headers.get("origin")
    allowed = {ws.headers.get("host"), ws.headers.get("x-forwarded-host"), urlparse(settings.base_url).netloc}
    if origin and urlparse(origin).netloc not in allowed:
        await ws.close(code=4403)  # чужой сайт не может подключиться от имени вошедшего пользователя
        return
    who = await run_in_threadpool(_ws_user, ws.cookies.get(COOKIE_NAME))
    if not who:
        await ws.close(code=4401)
        return
    user_id, user_name = who
    await manager.connect(user_id, ws)
    peers: dict[int, tuple[float, tuple[int, bool] | None]] = {}  # чат → (когда проверили, собеседник)
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
            if kind == "presence":  # страница сообщает, видна ли она: от этого зависит, слать ли уведомления в Telegram
                manager.set_visible(ws, bool(data.get("visible")))
                continue
            if kind not in CALL_EVENTS and kind != "typing":
                continue
            if kind.startswith("call:") and not settings.calls_enabled:
                continue  # звонки выключены (CALLS_ENABLED=0)
            if kind == "call:join":
                # открыли COFI кнопкой «Ответить» из Telegram: отдаём ждущий звонок и накопленные ICE-кандидаты
                p = push.take(str(data.get("call_id")), user_id)
                if not p or not manager.is_online(p.caller_id):
                    await ws.send_text(json.dumps({"type": "call:gone", "call_id": data.get("call_id")}))
                    continue
                await ws.send_text(json.dumps({"type": "call:offer", "conversation_id": p.conversation_id, "call_id": p.call_id,
                                               "sdp": p.sdp, "video": p.video, "answer_now": True,
                                               "from": {"id": p.caller_id, "name": p.caller_name}}))
                for cand in p.ice:
                    await ws.send_text(json.dumps({"type": "call:ice", "conversation_id": p.conversation_id, "call_id": p.call_id, "candidate": cand}))
                continue
            try:
                conv_id = int(data.get("conversation_id"))
            except (TypeError, ValueError):
                continue
            cached = peers.get(conv_id)
            if not cached or time.monotonic() - cached[0] > PEER_TTL:  # блокировку или удалённую пару увидим быстро
                cached = peers[conv_id] = (time.monotonic(), await run_in_threadpool(_peer, conv_id, user_id))
            if cached[1] is None:
                continue
            peer, peer_is_bot = cached[1]

            out = {k: v for k, v in data.items() if k in {"type", "conversation_id", "sdp", "candidate", "video", "call_id", "reason"}}
            out["from"] = {"id": user_id, "name": user_name}

            call_id = str(data.get("call_id"))
            if kind == "call:offer":
                if peer_is_bot:
                    await ws.send_text(json.dumps({"type": "call:unavailable", "conversation_id": conv_id, "call_id": call_id, "reason": "bot"}))
                    continue
                call = push.PendingCall(call_id=call_id, conversation_id=conv_id, caller_id=user_id, caller_name=user_name,
                                        callee_id=peer, video=bool(data.get("video")), sdp=data.get("sdp") or {})
                online = manager.is_online(peer)
                notified = await run_in_threadpool(_offer_call, call)
                if not online and not notified:
                    push.finish(call_id, "gone")
                    await ws.send_text(json.dumps({"type": "call:unavailable", "conversation_id": conv_id, "call_id": call_id, "reason": "offline"}))
                    continue
                if notified:
                    await ws.send_text(json.dumps({"type": "call:notified", "conversation_id": conv_id, "call_id": call_id}))
                msg = await run_in_threadpool(_log_call, conv_id, user_id, bool(data.get("video")))
                for uid in (user_id, peer):
                    await manager.send(uid, {"type": "message", "message": msg})
            elif kind == "call:ice":
                push.add_ice(call_id, user_id, data.get("candidate"))
            elif kind in ("call:answer", "call:end", "call:reject", "call:busy"):
                push.finish(call_id, kind.split(":")[1])
            await manager.send(peer, out)
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(user_id, ws)
