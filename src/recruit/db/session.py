"""Engine and session construction."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_URL = "postgresql+psycopg://recruit:recruit@localhost:5432/recruit"


def create_engine_from_config(config: Any | None = None, url: str | None = None,
                              echo: bool = False) -> Engine:
    """DATABASE_URL wins over config, so a container can override without edits."""
    resolved = (
        url
        or os.environ.get("DATABASE_URL")
        or (config.get("adapters.database.url") if config is not None else None)
        or DEFAULT_URL
    )
    engine = create_engine(resolved, echo=echo, future=True)

    if engine.dialect.name == "sqlite":
        # SQLite ignores foreign keys unless asked. Tests would then pass while
        # Postgres rejected the same data in production.
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_connection, _record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Commit on success, roll back on any exception."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
