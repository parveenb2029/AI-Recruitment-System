"""Database schema.

Retires the folder-as-database design. The numbered folders `01_`–`08_` are
documentation and an optional export view; Postgres is the system of record.

The audit log is **append-only**. Enforcement is in two layers:

1. Application — `AuditLog` has no update or delete path, and the repository
   exposes no method that would produce one.
2. Database — a trigger (see `db/migrations.py`) raises on UPDATE or DELETE.

One layer alone is not enough. App-level rules are bypassed by anyone with a
psql prompt; DB-level rules are silently absent if a migration is skipped.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """JSON rather than JSONB so the same models run on SQLite in tests and
    Postgres in production. The migration upgrades these columns to JSONB on
    Postgres, where indexing and containment queries need it."""

    type_annotation_map = {dict[str, Any]: JSON}


class Requisition(Base):
    __tablename__ = "requisitions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    department: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="OPEN")
    jurisdiction: Mapped[str] = mapped_column(String(16), default="EU")
    matching_scheme: Mapped[str | None] = mapped_column(String(64))
    structured_jd: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    candidates: Mapped[list[Candidate]] = relationship(back_populates="requisition")

    __table_args__ = (
        CheckConstraint("status IN ('OPEN','ON_HOLD','CLOSED','FILLED')",
                        name="ck_requisition_status"),
    )


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    requisition_id: Mapped[str | None] = mapped_column(ForeignKey("requisitions.id"))
    # BR-02: duplicates merge under one master key rather than creating a second
    # record. Null until a merge happens.
    candidate_master_id: Mapped[str | None] = mapped_column(String(64), index=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    jurisdiction: Mapped[str] = mapped_column(String(16), default="EU")
    consent_on_file: Mapped[bool] = mapped_column(default=False)
    outcome: Mapped[str] = mapped_column(String(32), default="IN_PROGRESS")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    requisition: Mapped[Requisition | None] = relationship(back_populates="candidates")
    documents: Mapped[list[Document]] = relationship(back_populates="candidate")

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('IN_PROGRESS','HIRED','REJECTED','WITHDRAWN')",
            name="ck_candidate_outcome",
        ),
    )


class Document(Base):
    """A source file. Bytes live in object storage; this row holds the pointer.

    `content_sha256` is unique: the same bytes are never stored twice, which is
    what makes re-submitting a resume idempotent (Execution_Flow.md §8).
    """

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content_sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("candidates.id"))
    storage_uri: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(String(512))
    extension: Mapped[str] = mapped_column(String(16))
    size_bytes: Mapped[int] = mapped_column(Integer)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    ocr_used: Mapped[bool] = mapped_column(default=False)
    virus_scanned: Mapped[bool] = mapped_column(default=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    candidate: Mapped[Candidate | None] = relationship(back_populates="documents")
    runs: Mapped[list[WorkflowRun]] = relationship(back_populates="document")


class WorkflowRun(Base):
    """One execution of one workflow over one document."""

    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(16), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    requisition_id: Mapped[str | None] = mapped_column(String(64), index=True)
    candidate_id: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16))
    prompt_version: Mapped[str] = mapped_column(String(32))
    model_id: Mapped[str] = mapped_column(String(128))
    confidence_aggregate: Mapped[float] = mapped_column(Float, default=0.0)
    human_review_required: Mapped[bool] = mapped_column(default=True)
    envelope: Mapped[dict[str, Any]] = mapped_column(JSON)
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[Document | None] = relationship(back_populates="runs")
    review_tasks: Mapped[list[ReviewTask]] = relationship(back_populates="run")

    __table_args__ = (
        CheckConstraint("status IN ('SUCCESS','PARTIAL','FAILED')", name="ck_run_status"),
        # One run per workflow per document. A re-run of the same bytes returns
        # the existing row instead of duplicating work and API spend.
        UniqueConstraint("workflow_id", "document_id", name="uq_run_workflow_document"),
        Index("ix_run_review_queue", "human_review_required", "confidence_aggregate"),
    )


class ReviewTask(Base):
    __tablename__ = "review_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    state: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    reasons: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    assigned_to: Mapped[str | None] = mapped_column(String(320))
    reviewer: Mapped[str | None] = mapped_column(String(320))
    reason_code: Mapped[str | None] = mapped_column(String(64))
    edits: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[WorkflowRun] = relationship(back_populates="review_tasks")

    __table_args__ = (
        CheckConstraint(
            "state IN ('PENDING','IN_REVIEW','APPROVED','REJECTED','ESCALATED')",
            name="ck_review_state",
        ),
    )


class User(Base):
    """An operator. Passwords are stored as scrypt hashes, never plaintext."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(32), default="recruiter")
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sessions: Mapped[list[Session]] = relationship(
        back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(
            "role IN ('admin','hiring_manager','recruiter','auditor')",
            name="ck_user_role",
        ),
    )


class Session(Base):
    """A login session. The token is stored hashed, so a database dump yields
    no usable cookies."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="sessions")


class AuditLog(Base):
    """Append-only. Never updated, never deleted.

    BR-05 requires prompt version, model id, actor, timestamp, and content hash
    on every entry, retained per jurisdiction.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    event: Mapped[str] = mapped_column(String(64), index=True)
    workflow_run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    workflow_id: Mapped[str | None] = mapped_column(String(16))
    candidate_id: Mapped[str | None] = mapped_column(String(64), index=True)
    requisition_id: Mapped[str | None] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(320))
    actor_role: Mapped[str | None] = mapped_column(String(32))
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    model_id: Mapped[str | None] = mapped_column(String(128))
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # PII is masked before it reaches this table (BR-06). Full data stays in the
    # artifact store, which has its own access control.
    pii_masked: Mapped[bool] = mapped_column(default=True)
