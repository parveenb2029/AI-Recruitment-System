"""Schema creation and the append-only enforcement trigger.

Alembic is the pinned tool for versioned migrations (see CLAUDE.md). This module
holds the bootstrap and the one piece of DDL that cannot be expressed in the ORM:
a database-level guarantee that nobody rewrites history.
"""

from __future__ import annotations

from sqlalchemy import Engine, text

from .models import Base

# Postgres: a BEFORE trigger that rejects UPDATE and DELETE on audit_log.
# This is what makes the audit log trustworthy against someone with a psql
# prompt, not merely against our own code.
POSTGRES_APPEND_ONLY = """
CREATE OR REPLACE FUNCTION audit_log_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'audit_log is append-only: % on row % is not permitted (BR-05)',
        TG_OP, OLD.id
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_log_no_update ON audit_log;
CREATE TRIGGER trg_audit_log_no_update
    BEFORE UPDATE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();

DROP TRIGGER IF EXISTS trg_audit_log_no_delete ON audit_log;
CREATE TRIGGER trg_audit_log_no_delete
    BEFORE DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();
"""

# SQLite equivalent, so the guarantee is testable without a server.
SQLITE_APPEND_ONLY = [
    """
    CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_update
    BEFORE UPDATE ON audit_log
    BEGIN
        SELECT RAISE(ABORT, 'audit_log is append-only: UPDATE not permitted (BR-05)');
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_delete
    BEFORE DELETE ON audit_log
    BEGIN
        SELECT RAISE(ABORT, 'audit_log is append-only: DELETE not permitted (BR-05)');
    END;
    """,
]

# JSON -> JSONB on Postgres. The ORM declares JSON so SQLite works in tests;
# production wants JSONB for containment queries and GIN indexes.
POSTGRES_JSONB = [
    "ALTER TABLE requisitions ALTER COLUMN structured_jd TYPE jsonb USING structured_jd::jsonb",
    "ALTER TABLE workflow_runs ALTER COLUMN envelope TYPE jsonb USING envelope::jsonb",
    "ALTER TABLE workflow_runs ALTER COLUMN validation TYPE jsonb USING validation::jsonb",
    "ALTER TABLE review_tasks ALTER COLUMN reasons TYPE jsonb USING reasons::jsonb",
    "ALTER TABLE review_tasks ALTER COLUMN edits TYPE jsonb USING edits::jsonb",
    "ALTER TABLE audit_log ALTER COLUMN detail TYPE jsonb USING detail::jsonb",
]


def create_all(engine: Engine, *, append_only: bool = True) -> None:
    """Create every table and install the append-only guarantee."""
    Base.metadata.create_all(engine)
    if not append_only:
        return

    dialect = engine.dialect.name
    with engine.begin() as connection:
        if dialect == "postgresql":
            for statement in POSTGRES_JSONB:
                connection.execute(text(statement))
            connection.execute(text(POSTGRES_APPEND_ONLY))
        elif dialect == "sqlite":
            for statement in SQLITE_APPEND_ONLY:
                connection.execute(text(statement))


def drop_all(engine: Engine) -> None:
    """Tests only. The triggers block DELETE, not DROP TABLE."""
    dialect = engine.dialect.name
    with engine.begin() as connection:
        if dialect == "postgresql":
            connection.execute(text(
                "DROP TRIGGER IF EXISTS trg_audit_log_no_update ON audit_log"))
            connection.execute(text(
                "DROP TRIGGER IF EXISTS trg_audit_log_no_delete ON audit_log"))
        elif dialect == "sqlite":
            connection.execute(text("DROP TRIGGER IF EXISTS trg_audit_log_no_update"))
            connection.execute(text("DROP TRIGGER IF EXISTS trg_audit_log_no_delete"))
    Base.metadata.drop_all(engine)
