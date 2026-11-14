from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import blocks, demo, feed_index, push
from ..config import settings
from ..database import get_db
from ..deps import current_user
from ..geo import GRID, haversine_km, public_distance_km, snap
from ..interests import compatible, match_score
from ..legal import TERMS_VERSION
from ..models import Conversation, Message, Notification, Swipe, User, utcnow
from ..realtime import notify
from ..serializers import photo_url, public_card

router = APIRouter(prefix="/api/feed", tags=["feed"])
notifications_router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class SwipeIn(BaseModel):
    user_id: int
    like: bool


def _require_access(user: User) -> None:
    if not user.is_complete:
        raise HTTPException(409, {"code": "profile_incomplete", "message": "Заполните анкету и подтвердите фото"})
    if user.terms_version != TERMS_VERSION:
        raise HTTPException(409, {"code": "terms_required", "message": "Примите Пользовательское соглашение"})
    if user.lat is None:
        raise HTTPException(409, {"code": "need_location", "message": "Разрешите доступ к геопозиции"})


def visible_users():
    return select(User).where(
        User.photo_verified.is_(True),
        User.is_banned.is_(False),
        User.lat.is_not(None),
        User.birth_date.is_not(None),
        User.gender.is_not(None),
        User.name != "",
    )


def audience(q, user: User):
    """Демо-гости видят только ботов; реальные пользователи не видят ни ботов, ни гостей."""
    if user.is_demo:
        return q.where(User.is_bot.is_(True))
    return q.where(User.is_bot.is_(False), User.is_demo.is_(False))


@router.get("")
def get_feed(limit: int = 10, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Анкеты рядом, сначала с наибольшим совпадением интересов, при равенстве — ближайшие."""
    _require_access(user)
    limit = max(1, min(limit, 30))

    # анкеты второго круга (recycled_at) снова в ленте; остальные свайпнутые — нет
    swiped = set(db.scalars(select(Swipe.to_user_id).where(Swipe.from_user_id == user.id, Swipe.recycled_at.is_(None)))) | blocks.hidden_ids(db, user.id)
    liked_before = set(db.scalars(select(Swipe.to_user_id).where(Swipe.from_user_id == user.id, Swipe.recycled_at.is_not(None))))
    radius = min(user.max_distance_km or 50, settings.max_distance_km)  # не дальше 7000 км, даже если сохранено больше
    my_set, my_n, my_goals = set(user.interests), len(user.interests), set(user.goals)
    # всё о себе считаем один раз, а не для каждой из тысяч анкет
    me_id, me_demo, me_group, me_gender, me_looking = user.id, bool(user.is_demo), user.age_group, user.gender, user.looking_for
    me_slat, me_slon = snap(user.lat), snap(user.lon)
    max_dlat = radius / 111.0 + GRID
    scored = []
    for c in feed_index.candidates(db):
        if c.id == me_id or c.id in swiped or c.group != me_group:
            continue  # подростки и взрослые никогда не видят друг друга
        if (c.is_bot if me_demo else (c.is_bot or c.is_demo)) != me_demo:
            continue  # демо-гости видят только ботов, настоящие люди — только настоящих
        if abs(c.slat - me_slat) > max_dlat:
            continue  # заведомо дальше радиуса — без точного расчёта
        if not compatible(me_gender, me_looking, c.gender, c.looking):
            continue
        d = max(1, round(haversine_km(me_slat, me_slon, c.slat, c.slon)))
        if d > radius:
            continue
        # то же, что match_score, но на готовых множествах
        common = [i for i in c.interests if i in my_set]
        interest_part = len(common) / (min(my_n, len(c.interests)) or 1)
        goal_part = len(my_goals & c.goals) / (min(len(my_goals), len(c.goals)) or 1) if my_goals and c.goals else 0
        same_goal = bool(my_goals & c.goals)
        scored.append((round(100 * (0.8 * interest_part + 0.2 * goal_part)), d, common, c.id, same_goal))
    # Сначала те, кто ищет то же, что и вы (отношения / дружба / общение); дальше группы по 10% совпадения,
    # внутри группы — по расстоянию
    scored.sort(key=lambda x: (not x[4], -(x[0] // 10), x[1]))
    top = scored[:limit]
    people = {u.id: u for u in db.scalars(select(User).where(User.id.in_([t[3] for t in top])))}
    skipped = 0
    if not top:  # лента кончилась — сколько анкет можно пролистать по второму кругу (пропущенные и лайкнутые без пары)
        skipped = len(_second_round(db, user))
    cards = []
    for sc, d, c, oid, _ in top:
        if oid in people:
            card = public_card(people[oid], sc, c, d)
            card["liked_before"] = oid in liked_before
            cards.append(card)
    return {"total": len(scored), "skipped": skipped, "cards": cards}


def _second_round(db: Session, user: User) -> list[Swipe]:
    """Свайпы, анкеты которых можно показать снова: пропущенные и лайкнутые, если пары ещё нет."""
    paired = set()
    for c in db.scalars(select(Conversation).where(Conversation.active.is_(True),
                                                   (Conversation.user_a_id == user.id) | (Conversation.user_b_id == user.id))):
        paired.add(c.other(user.id).id)
    rows = db.scalars(select(Swipe).where(Swipe.from_user_id == user.id, Swipe.recycled_at.is_(None))).all()
    return [s for s in rows if s.to_user_id not in paired]


@router.get("/likes")
def likes(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Раздел «Отклики»: взаимные (есть чат), кого лайкнули вы, кто лайкнул вас. Писать — только при взаимной."""
    _require_access(user)
    hidden = blocks.hidden_ids(db, user.id)

    def people(ids):
        ids = [i for i in ids if i not in hidden]
        if not ids:
            return {}
        rows = db.scalars(audience(select(User), user).where(User.id.in_(ids), User.is_banned.is_(False),
                                                             User.name != "", User.birth_date.is_not(None))).all()
        return {u.id: u for u in rows if u.age_group == user.age_group}

    def card(u, at, conversation_id=None):
        return {"id": u.id, "name": u.name, "age": u.years, "photo_url": photo_url(u), "verified": u.photo_verified,
                "city": u.city if u.show_city is not False else None, "at": at.isoformat() + "Z" if at else None,
                "conversation_id": conversation_id}

    convs = db.scalars(select(Conversation).where(Conversation.active.is_(True),
                                                  (Conversation.user_a_id == user.id) | (Conversation.user_b_id == user.id))
                       .order_by(Conversation.created_at.desc())).all()
    pair = {c.other(user.id).id: c for c in convs}
    mine = db.execute(select(Swipe.to_user_id, Swipe.created_at).where(Swipe.from_user_id == user.id, Swipe.liked.is_(True))
                      .order_by(Swipe.created_at.desc())).all()
    theirs = db.execute(select(Swipe.from_user_id, Swipe.created_at).where(Swipe.to_user_id == user.id, Swipe.liked.is_(True))
                        .order_by(Swipe.created_at.desc())).all()
    i_liked = {uid for uid, _ in mine}
    found = people(list(pair) + [uid for uid, _ in mine] + [uid for uid, _ in theirs])
    return {
        "mutual": [card(found[uid], c.created_at, c.id) for uid, c in pair.items() if uid in found],
        "sent": [card(found[uid], at) for uid, at in mine if uid in found and uid not in pair],
        "received": [card(found[uid], at) for uid, at in theirs if uid in found and uid not in pair and uid not in i_liked],
    }


@router.post("/restart")
def restart(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Анкеты закончились — второй круг: пропущенные и лайкнутые (без пары) снова в ленте.
    Лайк при этом не пропадает: ответит взаимностью — будет пара. Чёрный список и пары — не возвращаются."""
    _require_access(user)
    now = utcnow()
    n = 0
    for s in _second_round(db, user):
        if s.liked:
            s.recycled_at = now
        else:
            db.delete(s)
        n += 1
    db.commit()
    return {"restored": n}


def _notify_match(db: Session, conv: Conversation, background: BackgroundTasks) -> None:
    for me, other in ((conv.user_a, conv.user_b), (conv.user_b, conv.user_a)):
        _, common = match_score(me.interests, me.goals, other.interests, other.goals)
        payload = {
            "conversation_id": conv.id,
            "common": common,
            "user": {"id": other.id, "name": other.name, "photo_url": photo_url(other)},
        }
        db.add(Notification(user_id=me.id, kind="match", payload=json.dumps(payload, ensure_ascii=False)))
        notify(me.id, {"type": "match", **payload})
        push.notify_match(me, other.name, conv.id)
    db.commit()


@router.post("/swipe")
def swipe(data: SwipeIn, background: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _require_access(user)
    if data.user_id == user.id:
        raise HTTPException(400, "Нельзя лайкнуть себя")
    target = db.scalar(audience(visible_users(), user).where(User.id == data.user_id))
    if not target or target.age_group != user.age_group:
        raise HTTPException(404, "Анкета больше не доступна")

    if blocks.between(db, user.id, target.id) or not compatible(user.gender, user.looking_for, target.gender, target.looking_for):
        raise HTTPException(404, "Анкета больше не доступна")
    existing = db.scalar(select(Swipe).where(Swipe.from_user_id == user.id, Swipe.to_user_id == target.id))
    if existing:
        # «Дальше» на втором круге по уже лайкнутой анкете лайк НЕ снимает — просто листаем дальше.
        # Снять лайк можно только явно: «Вернуть последнюю анкету» или в разделе «Отклики».
        if not (existing.liked and existing.recycled_at is not None and not data.like):
            existing.liked = data.like
        existing.recycled_at = None  # свайпнули на втором круге — анкета снова уходит из ленты
    else:
        db.add(Swipe(from_user_id=user.id, to_user_id=target.id, liked=data.like))
    db.commit()

    if not data.like:
        return {"match": False}

    reverse = db.scalar(
        select(Swipe).where(Swipe.from_user_id == target.id, Swipe.to_user_id == user.id, Swipe.liked.is_(True))
    )
    if not reverse:
        return {"match": False}
    if reverse.recycled_at is not None:  # их лайк был на втором круге — теперь пара, из ленты анкета уходит
        reverse.recycled_at = None

    a, b = sorted((user.id, target.id))
    conv = db.scalar(select(Conversation).where(Conversation.user_a_id == a, Conversation.user_b_id == b))
    is_new = conv is None or not conv.active
    if conv is None:
        conv = Conversation(user_a_id=a, user_b_id=b)
        db.add(conv)
    conv.active = True
    try:
        db.commit()
    except IntegrityError:  # оба лайкнули друг друга в одну секунду: пару уже создал второй запрос
        db.rollback()
        conv = db.scalar(select(Conversation).where(Conversation.user_a_id == a, Conversation.user_b_id == b))
        is_new = False
    db.refresh(conv)
    if is_new:
        _notify_match(db, conv, background)
        if target.is_bot:
            background.add_task(demo.bot_reply, conv.id, target.id, True)
    score, common = match_score(user.interests, user.goals, target.interests, target.goals)
    return {"match": True, "conversation_id": conv.id, "user": public_card(target, score, common)}


class UndoIn(BaseModel):
    user_id: int


@router.post("/undo")
def undo(data: UndoIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Вернуть анкету, пролистанную по ошибке, или отменить лайк.
    Если лайк уже дал пару и в чате есть сообщения, отменить нельзя: пару удаляют из чата."""
    swipe = db.scalar(select(Swipe).where(Swipe.from_user_id == user.id, Swipe.to_user_id == data.user_id))
    if not swipe:
        raise HTTPException(404, "Нечего отменять")
    a, b = sorted((user.id, data.user_id))
    conv = db.scalar(select(Conversation).where(Conversation.user_a_id == a, Conversation.user_b_id == b))
    if swipe.liked and conv is not None and conv.active:
        has_messages = db.scalar(select(Message.id).where(Message.conversation_id == conv.id, Message.kind != "call").limit(1))
        if has_messages:
            raise HTTPException(409, "У вас уже есть переписка. Удалить пару можно в чате")
        conv.active = False
        notify(conv.other(user.id).id, {"type": "unmatch", "conversation_id": conv.id})
    was_like = swipe.liked
    db.delete(swipe)
    db.commit()
    target = db.get(User, data.user_id)
    if target is None or target.is_banned or blocks.between(db, user.id, target.id):
        raise HTTPException(404, "Анкета больше не доступна")  # удалили, заблокировали или вы в чёрном списке
    score, common = match_score(user.interests, user.goals, target.interests, target.goals)
    d = public_distance_km(user.lat, user.lon, target.lat, target.lon) if user.lat is not None and target.lat is not None else None
    return {"undone": "like" if was_like else "skip", "card": public_card(target, score, common, d)}


@notifications_router.get("")
def list_notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Notification).where(Notification.user_id == user.id).order_by(Notification.id.desc()).limit(50)
    ).all()
    return [
        {"id": n.id, "kind": n.kind, "payload": json.loads(n.payload), "read": n.read, "created_at": n.created_at.isoformat() + "Z"}
        for n in rows
    ]


@notifications_router.post("/read")
def read_notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    for n in db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.read.is_(False))):
        n.read = True
    db.commit()
    return {"status": "ok"}
