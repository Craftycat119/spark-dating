from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Вход по почте
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_notifications: Mapped[bool] = mapped_column(Boolean, default=True)

    # Вход через Telegram
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(64))

    auth_provider: Mapped[str] = mapped_column(String(16), default="email")  # email | telegram

    # Профиль (один на все ленты)
    name: Mapped[str] = mapped_column(String(64), default="")
    age: Mapped[int | None] = mapped_column(Integer)
    bio: Mapped[str] = mapped_column(Text, default="")  # единое описание
    use_common_bio: Mapped[bool] = mapped_column(Boolean, default=True)

    photo_path: Mapped[str | None] = mapped_column(String(255))
    photo_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    photo_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    face_score: Mapped[float | None] = mapped_column(Float)
    selfie_path: Mapped[str | None] = mapped_column(String(255))  # кадр со сканера, видит только админ

    # Геопозиция
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    location_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    max_distance_km: Mapped[int] = mapped_column(Integer, default=50)

    # Данные о регистрации (для админки)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    registration_ip: Mapped[str | None] = mapped_column(String(64))
    registration_user_agent: Mapped[str | None] = mapped_column(String(512))
    registration_lat: Mapped[float | None] = mapped_column(Float)
    registration_lon: Mapped[float | None] = mapped_column(Float)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)

    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)

    feeds: Mapped[list[ProfileFeed]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    def feed(self, key: str) -> ProfileFeed | None:
        return next((f for f in self.feeds if f.feed == key), None)

    def bio_for(self, key: str) -> str:
        if self.use_common_bio:
            return self.bio
        f = self.feed(key)
        return (f.bio if f and f.bio else self.bio) or ""

    @property
    def active_feeds(self) -> list[str]:
        return [f.feed for f in self.feeds if f.enabled]

    @property
    def is_complete(self) -> bool:
        """Анкета готова к показу в лентах."""
        return bool(self.name and self.photo_path and self.photo_verified and self.age)


class ProfileFeed(Base):
    """В какой ленте показывается пользователь и с каким описанием."""

    __tablename__ = "profile_feeds"
    __table_args__ = (UniqueConstraint("user_id", "feed"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    feed: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    bio: Mapped[str] = mapped_column(Text, default="")

    user: Mapped[User] = relationship(back_populates="feeds")


class EmailCode(Base):
    __tablename__ = "email_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    purpose: Mapped[str] = mapped_column(String(16))  # verify | reset
    code_hash: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuthSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    ip: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[User] = relationship(lazy="joined")


class Swipe(Base):
    __tablename__ = "swipes"
    __table_args__ = (UniqueConstraint("from_user_id", "to_user_id", "feed"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    from_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    to_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    feed: Mapped[str] = mapped_column(String(16))
    liked: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Conversation(Base):
    """Один чат на пару людей, даже если метч случился в нескольких лентах."""

    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("user_a_id", "user_b_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_a_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    user_b_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    user_a: Mapped[User] = relationship(foreign_keys=[user_a_id], lazy="joined")
    user_b: Mapped[User] = relationship(foreign_keys=[user_b_id], lazy="joined")
    matches: Mapped[list[Match]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", lazy="selectin"
    )

    def other(self, user_id: int) -> User:
        return self.user_b if self.user_a_id == user_id else self.user_a

    def has(self, user_id: int) -> bool:
        return user_id in (self.user_a_id, self.user_b_id)


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("conversation_id", "feed"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    feed: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="matches")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # text | image | video | voice | circle | sticker | call
    kind: Mapped[str] = mapped_column(String(16), default="text")
    text: Mapped[str] = mapped_column(Text, default="")
    media_path: Mapped[str | None] = mapped_column(String(255))
    duration: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
