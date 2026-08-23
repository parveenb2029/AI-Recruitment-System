"""Repository — the only sanctioned way into the database.

Deliberately exposes no method that updates or deletes an audit entry. The
database trigger is the backstop; this class is the guardrail that means nobody
reaches for the backstop by accident.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditLog, Candidate, Document, Requisition, ReviewTask, WorkflowRun
from .session import session_scope  # re-exported for convenience

__all__ = ["Repository", "session_scope"]

MASK_KEYS = {"email", "phone", "full_name", "linkedin_url", "address", "date_of_birth"}


def mask_pii(payload: Any) -> Any:
    """BR-06: PII is masked in logs; full data only in the artifact store.

    Masks rather than drops, so a reviewer can still tell a field was present
    and roughly what shape it had.
    """
    if isinstance(payload, dict):
        out: dict[str, Any] = {}
        for key, value in payload.items():
            if key in MASK_KEYS and isinstance(value, str) and value:
                out[key] = f"{value[:1]}***[{len(value)}]"
            else:
                out[key] = mask_pii(value)
        return out
    if isinstance(payload, list):
        return [mask_pii(item) for item in payload]
    return payload


class Repository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # -- documents ---------------------------------------------------------
    def get_document_by_hash(self, content_sha256: str) -> Document | None:
        return self.session.scalar(
            select(Document).where(Document.content_sha256 == content_sha256)
        )

    def upsert_document(self, *, content_sha256: str, storage_uri: str, filename: str,
                        extension: str, size_bytes: int, pages: int = 0,
                        char_count: int = 0, ocr_used: bool = False,
                        virus_scanned: bool = False,
                        candidate_id: str | None = None) -> tuple[Document, bool]:
        """Returns (document, created). Same bytes are never stored twice."""
        existing = self.get_document_by_hash(content_sha256)
        if existing is not None:
            return existing, False
        document = Document(
            content_sha256=content_sha256, storage_uri=storage_uri, filename=filename,
            extension=extension, size_bytes=size_bytes, pages=pages,
            char_count=char_count, ocr_used=ocr_used, virus_scanned=virus_scanned,
            candidate_id=candidate_id,
        )
        self.session.add(document)
        self.session.flush()
        return document, True

    # -- runs --------------------------------------------------------------
    def get_run(self, run_id: str) -> WorkflowRun | None:
        return self.session.get(WorkflowRun, run_id)

    def find_run(self, workflow_id: str, document_id: int) -> WorkflowRun | None:
        return self.session.scalar(
            select(WorkflowRun).where(
                WorkflowRun.workflow_id == workflow_id,
                WorkflowRun.document_id == document_id,
            )
        )

    def save_run(self, envelope: dict[str, Any], *, document_id: int | None,
                 validation: dict[str, Any] | None = None,
                 force: bool = False) -> tuple[WorkflowRun, bool]:
        """Persist a run. Returns (run, created).

        Idempotent: the same workflow over the same document returns the stored
        run rather than re-doing the work. `force=True` overwrites, which is the
        documented manual re-run path (Workflow_Spec.md §7).
        """
        workflow_id = envelope["workflow_id"]
        if document_id is not None:
            existing = self.find_run(workflow_id, document_id)
            if existing is not None and not force:
                return existing, False
            if existing is not None and force:
                existing.status = envelope["status"]
                existing.envelope = envelope
                existing.validation = validation
                existing.confidence_aggregate = envelope.get("confidence_aggregate", 0.0)
                existing.human_review_required = envelope.get("human_review_required", True)
                self.session.flush()
                return existing, False

        run = WorkflowRun(
            id=envelope["workflow_run_id"],
            workflow_id=workflow_id,
            document_id=document_id,
            requisition_id=envelope.get("requisition_id"),
            candidate_id=envelope.get("candidate_id"),
            status=envelope["status"],
            prompt_version=envelope["prompt_version"],
            model_id=envelope["model_id"],
            confidence_aggregate=envelope.get("confidence_aggregate", 0.0),
            human_review_required=envelope.get("human_review_required", True),
            envelope=envelope,
            validation=validation,
        )
        self.session.add(run)
        self.session.flush()
        return run, True

    # -- review queue ------------------------------------------------------
    def create_review_task(self, run: WorkflowRun,
                           reasons: list[str] | None = None) -> ReviewTask:
        task = ReviewTask(
            workflow_run_id=run.id,
            reasons={"reasons": reasons or run.envelope.get("review_reasons", [])},
        )
        self.session.add(task)
        self.session.flush()
        return task

    def review_queue(self, limit: int = 50) -> list[ReviewTask]:
        """Riskiest first: lowest confidence at the top, per Human_Review.md."""
        return list(
            self.session.scalars(
                select(ReviewTask)
                .join(WorkflowRun)
                .where(ReviewTask.state.in_(("PENDING", "IN_REVIEW")))
                .order_by(WorkflowRun.confidence_aggregate.asc(), ReviewTask.created_at.asc())
                .limit(limit)
            )
        )

    def resolve_review(self, task: ReviewTask, *, reviewer: str, state: str,
                       reason_code: str | None = None,
                       edits: dict[str, Any] | None = None) -> ReviewTask:
        if state not in ("APPROVED", "REJECTED", "ESCALATED"):
            raise ValueError(f"Invalid resolution state: {state}")
        task.state = state
        task.reviewer = reviewer
        task.reason_code = reason_code
        task.edits = edits
        task.resolved_at = datetime.now(UTC)
        self.session.flush()
        return task

    # -- audit -------------------------------------------------------------
    def append_audit(self, *, event: str, actor: str, actor_role: str | None = None,
                     workflow_run_id: str | None = None, workflow_id: str | None = None,
                     candidate_id: str | None = None, requisition_id: str | None = None,
                     prompt_version: str | None = None, model_id: str | None = None,
                     content_sha256: str | None = None,
                     detail: dict[str, Any] | None = None) -> AuditLog:
        """The ONLY way to write audit history. There is no update or delete."""
        entry = AuditLog(
            event=event, actor=actor, actor_role=actor_role,
            workflow_run_id=workflow_run_id, workflow_id=workflow_id,
            candidate_id=candidate_id, requisition_id=requisition_id,
            prompt_version=prompt_version, model_id=model_id,
            content_sha256=content_sha256,
            detail=mask_pii(detail) if detail else None,
            pii_masked=True,
        )
        self.session.add(entry)
        self.session.flush()
        return entry

    def audit_trail(self, workflow_run_id: str) -> list[AuditLog]:
        return list(
            self.session.scalars(
                select(AuditLog)
                .where(AuditLog.workflow_run_id == workflow_run_id)
                .order_by(AuditLog.occurred_at.asc(), AuditLog.id.asc())
            )
        )

    # -- retention ---------------------------------------------------------
    def candidates_past_retention(self, config: Any,
                                  now: datetime | None = None) -> list[Candidate]:
        """Candidates whose retention window has closed, per jurisdiction.

        Replaces the flat 7-year rule that conflicted with GDPR storage
        limitation. Consent extends the window; it does not remove it.
        """
        reference = now or datetime.now(UTC)
        expired: list[Candidate] = []
        for candidate in self.session.scalars(select(Candidate)):
            if candidate.outcome == "HIRED":
                outcome_key = "hired_employee"
            elif candidate.consent_on_file:
                outcome_key = "unsuccessful_with_consent"
            else:
                outcome_key = "unsuccessful_candidate"
            days = config.retention_days(candidate.jurisdiction, outcome_key)
            created = candidate.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            if reference - created > timedelta(days=days):
                expired.append(candidate)
        return expired

    # -- convenience -------------------------------------------------------
    def ensure_requisition(self, requisition_id: str, **fields: Any) -> Requisition:
        existing = self.session.get(Requisition, requisition_id)
        if existing is not None:
            return existing
        requisition = Requisition(id=requisition_id, title=fields.pop("title", "Untitled"),
                                  **fields)
        self.session.add(requisition)
        self.session.flush()
        return requisition

    def ensure_candidate(self, candidate_id: str, **fields: Any) -> Candidate:
        existing = self.session.get(Candidate, candidate_id)
        if existing is not None:
            return existing
        candidate = Candidate(id=candidate_id, **fields)
        self.session.add(candidate)
        self.session.flush()
        return candidate
