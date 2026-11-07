from __future__ import annotations

import json
from datetime import date, datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
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
from .ages import group_for, years_between
from .interests import MIN_INTERESTS


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
    tg_notifications: Mapped[bool] = mapped_column(Boolean, default=True)  # сообщения, пары и звонки через Telegram-бота

    # Вход через Telegram
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(64))

    auth_provider: Mapped[str] = mapped_column(String(16), default="email")  # email | telegram

    # Профиль
    name: Mapped[str] = mapped_column(String(64), default="")
    age: Mapped[int | None] = mapped_column(Integer)  # кеш; источник правды — birth_date
    birth_date: Mapped[date | None] = mapped_column(Date)
    age_verified: Mapped[bool] = mapped_column(Boolean, default=False)  # возраст подтверждён документом (вручную админом)
    # Согласие с Пользовательским соглашением и подтверждение возраста при регистрации
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime)
    terms_version: Mapped[str | None] = mapped_column(String(16))
    # "adult" — подтвердил, что ему есть 18; "guardian" — 14–17 лет, подтвердил согласие родителя
    age_confirmation: Mapped[str | None] = mapped_column(String(16))
    consent_pd_at: Mapped[datetime | None] = mapped_column(DateTime)  # согласие на обработку персональных данных
    consent_bio_at: Mapped[datetime | None] = mapped_column(DateTime)  # согласие на биометрию (проверка лица)
    consent_sexuality_at: Mapped[datetime | None] = mapped_column(DateTime)  # согласие на сведения о сексуальности
    consent_ip: Mapped[str | None] = mapped_column(String(64))  # с какого адреса приняты документы
    language: Mapped[str] = mapped_column(String(8), default="ru")
    gender: Mapped[str | None] = mapped_column(String(16))  # male | female | nonbinary
    orientation: Mapped[str | None] = mapped_column(String(16))  # сексуальность: hetero | bi | gay | lesbian | queer | ace | pan (с 18 лет)
    show_identity: Mapped[bool] = mapped_column(Boolean, default=True)  # показывать пол в анкете
    show_orientation: Mapped[bool] = mapped_column(Boolean, default=True)  # показывать сексуальность в анкете
    # Необязательные поля анкеты
    height_cm: Mapped[int | None] = mapped_column(Integer)
    weight_kg: Mapped[int | None] = mapped_column(Integer)
    zodiac: Mapped[str | None] = mapped_column(String(16))
    extras_done: Mapped[bool] = mapped_column(Boolean, default=False)  # прошёл (или пропустил) шаги «рост, вес, знак»
    looking_for: Mapped[str | None] = mapped_column(String(16))  # male | female | any
    bio: Mapped[str] = mapped_column(Text, default="")
    interests_json: Mapped[str] = mapped_column(Text, default="[]")
    goals_json: Mapped[str] = mapped_column(Text, default="[]")

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
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)  # гость демо-режима
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False, index=True)  # анкета-бот для демо

    photos: Mapped[list[UserPhoto]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="UserPhoto.id"
    )

    @property
    def interests(self) -> list[str]:
        return json.loads(self.interests_json or "[]")

    @interests.setter
    def interests(self, values: list[str]) -> None:
        self.interests_json = json.dumps(values, ensure_ascii=False)

    @property
    def goals(self) -> list[str]:
        return json.loads(self.goals_json or "[]")

    @goals.setter
    def goals(self, values: list[str]) -> None:
        self.goals_json = json.dumps(values, ensure_ascii=False)

    @property
    def survey_done(self) -> bool:
        return len(self.interests) >= MIN_INTERESTS and bool(self.goals)

    @property
    def years(self) -> int | None:
        return years_between(self.birth_date) if self.birth_date else None

    @property
    def age_group(self) -> str | None:
        return group_for(self.years)

    @property
    def is_complete(self) -> bool:
        """Анкета готова к показу в ленте."""
        return bool(
            self.name and self.age_group and self.gender and self.looking_for
            and self.survey_done and self.photo_path and self.photo_verified
        )


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
    __table_args__ = (UniqueConstraint("from_user_id", "to_user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    from_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    to_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    liked: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Conversation(Base):
    """Пара (взаимный лайк) и её чат."""

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

    def other(self, user_id: int) -> User:
        return self.user_b if self.user_a_id == user_id else self.user_a

    def has(self, user_id: int) -> bool:
        return user_id in (self.user_a_id, self.user_b_id)


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


class UserPhoto(Base):
    """Дополнительные фото в анкете (основное фото проверено сканером, эти нет)."""

    __tablename__ = "user_photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AnimalPost(Base):
    """Объявление в ленте «Питомцы»."""

    __tablename__ = "animal_posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(16), index=True)  # charity | foster | adoption
    name: Mapped[str] = mapped_column(String(64))
    species: Mapped[str] = mapped_column(String(32), default="")
    age_text: Mapped[str] = mapped_column(String(32), default="")
    city: Mapped[str] = mapped_column(String(64), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    contact: Mapped[str] = mapped_column(String(128))  # @username или ссылка t.me/… на человека или группу
    fundraising_open: Mapped[bool] = mapped_column(Boolean, default=True)
    fundraising_goal: Mapped[str] = mapped_column(String(64), default="")
    photos_json: Mapped[str] = mapped_column(Text, default="[]")
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    author: Mapped[User] = relationship(lazy="joined")

    @property
    def photos(self) -> list[str]:
        return json.loads(self.photos_json or "[]")

    @photos.setter
    def photos(self, values: list[str]) -> None:
        self.photos_json = json.dumps(values, ensure_ascii=False)


class HelpRequest(Base):
    """Заявка «Хочу помочь» по объявлению о животном."""

    __tablename__ = "help_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("animal_posts.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    message: Mapped[str] = mapped_column(Text, default="")
    contact: Mapped[str] = mapped_column(String(128), default="")
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SupportThread(Base):
    """Обращение в поддержку или к помощнику по рекламе."""

    __tablename__ = "support_threads"

    id: Mapped[int] = mapped_column(primary_key=True)
    topic: Mapped[str] = mapped_column(String(16), index=True)  # support | ads
    category: Mapped[str] = mapped_column(String(16), default="help")  # help | complaint | suggestion | ads
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    guest_token_hash: Mapped[str | None] = mapped_column(String(128), index=True)  # рекламодатель без аккаунта
    contact: Mapped[str] = mapped_column(String(128), default="")
    about_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | closed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    user: Mapped[User | None] = relationship(foreign_keys=[user_id], lazy="joined")


class SupportMessage(Base):
    __tablename__ = "support_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("support_threads.id", ondelete="CASCADE"), index=True)
    author: Mapped[str] = mapped_column(String(8))  # user | staff | bot
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ActivityDay(Base):
    """Заходы пользователя по дням: для статистики «сколько людей заходило за день, неделю, месяц».
    Одна строка на человека в день; visits — сколько раз он возвращался после перерыва больше 30 минут."""

    __tablename__ = "activity_days"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    visits: Mapped[int] = mapped_column(Integer, default=1)


class Block(Base):
    """Чёрный список: blocked не может писать blocker'у, они не видят друг друга в ленте и чатах."""

    __tablename__ = "blocks"

    blocker_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    blocked_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
