from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

engine = create_engine(
    settings.db_url,
    connect_args={"check_same_thread": False} if settings.db_url.startswith("sqlite") else {},
)


if settings.db_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()
        # Встроенный lower() в SQLite не понимает кириллицу — подменяем на питоновский
        dbapi_conn.create_function("lower", 1, lambda v: v.lower() if isinstance(v, str) else v, deterministic=True)


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  — регистрируем модели

    Base.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """Новые поля в моделях добавляются в уже существующую базу сами: анкеты и чаты не теряются.
    create_all создаёт только новые таблицы, а колонки в старых таблицах не трогает."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(engine.dialect)}'
                default = getattr(col.default, "arg", None)
                if isinstance(default, bool):
                    ddl += f" NOT NULL DEFAULT {int(default)}"
                elif isinstance(default, (int, float)):
                    ddl += f" NOT NULL DEFAULT {default}"
                elif isinstance(default, str):
                    ddl += " NOT NULL DEFAULT '" + default.replace("'", "''") + "'"
                conn.execute(text(ddl))
