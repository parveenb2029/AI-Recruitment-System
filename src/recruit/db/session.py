"""Engine and session construction."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


class DatabaseDriverMissing(RuntimeError):
    """The configured database needs a driver that is not installed."""

# SQLite by default so `pip install -e .` -> seed -> web works with no server,
# no Docker, and no database driver to compile. Postgres is the production
# target and is one config line away; see docker-compose.yml.
DEFAULT_URL = "sqlite:///./data/recruit.db"

DRIVER_HELP = {
    "psycopg": (
        "PostgreSQL is configured but its driver is not installed.\n"
        '  Install it:      pip install -e ".[postgres]"\n'
        "  Or use SQLite:   set adapters.database.url in config/organization.yaml to\n"
        "                   sqlite:///./data/recruit.db\n"
        "                   (or set DATABASE_URL, which overrides the config)"
    ),
    "psycopg2": (
        "PostgreSQL is configured but psycopg2 is not installed.\n"
        '  Install it:      pip install -e ".[postgres]"'
    ),
    "MySQLdb": ("MySQL is configured but its driver is not installed."),
}


def create_engine_from_config(config: Any | None = None, url: str | None = None,
                              echo: bool = False) -> Engine:
    """DATABASE_URL wins over config, so a container can override without edits."""
    resolved = (
        url
        or os.environ.get("DATABASE_URL")
        or (config.get("adapters.database.url") if config is not None else None)
        or DEFAULT_URL
    )
    try:
        engine = create_engine(resolved, echo=echo, future=True)
    except ModuleNotFoundError as exc:
        # SQLAlchemy raises a bare ModuleNotFoundError naming the DBAPI module.
        # On its own that tells an operator nothing about how to fix it.
        help_text = DRIVER_HELP.get(exc.name or "", "")
        raise DatabaseDriverMissing(
            f"Cannot connect to {resolved.split('://')[0]}: "
            f"the '{exc.name}' driver is not installed."
            + (f"\n\n{help_text}" if help_text else "")
        ) from exc

    # A file-backed SQLite database needs its directory to exist first.
    if engine.dialect.name == "sqlite" and engine.url.database not in (None, ":memory:"):
        Path(engine.url.database).parent.mkdir(parents=True, exist_ok=True)

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
