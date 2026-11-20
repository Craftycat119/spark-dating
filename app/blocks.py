"""Чёрный список."""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import Block


def hidden_ids(db: Session, user_id: int) -> set[int]:
    """Все, с кем у человека блокировка в любую сторону: друг друга не видят и не пишут."""
    rows = db.execute(select(Block.blocker_id, Block.blocked_id).where(
        or_(Block.blocker_id == user_id, Block.blocked_id == user_id))).all()
    return {b if a == user_id else a for a, b in rows}


def between(db: Session, a: int, b: int) -> bool:
    return db.scalar(select(Block.blocker_id).where(or_(
        (Block.blocker_id == a) & (Block.blocked_id == b), (Block.blocker_id == b) & (Block.blocked_id == a))).limit(1)) is not None
