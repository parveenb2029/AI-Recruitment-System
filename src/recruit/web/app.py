"""FastAPI application for the review console."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..db.models import Document, ReviewTask, WorkflowRun
from ..db.repository import Repository
from ..db.session import create_engine_from_config, make_session_factory

TEMPLATES = Path(__file__).resolve().parent / "templates"

# Reason codes a reviewer can pick when rejecting. Free text is not offered:
# rejections need to be aggregable, or the quality loop in Phase 4 has nothing
# to learn from.
REJECT_REASONS = [
    ("FABRICATED_CONTENT", "Evidence not in the source document"),
    ("WRONG_EXTRACTION", "Fields extracted incorrectly"),
    ("WRONG_DOCUMENT", "Not this candidate's document"),
    ("UNREADABLE_SOURCE", "Source document unusable"),
    ("DUPLICATE", "Duplicate of an existing candidate"),
    ("OTHER", "Other — see note"),
]


def create_app(
    session_factory: Any | None = None,
    config: Any | None = None,
    current_user: Any | None = None,
) -> FastAPI:
    app = FastAPI(title="Review Console", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=str(TEMPLATES))

    if session_factory is None:
        session_factory = make_session_factory(create_engine_from_config(config))

    def get_session():
        session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def actor() -> tuple[str, str]:
        """Identity for the audit log. Single-user until Phase 5.1 adds real auth."""
        if current_user is not None:
            return current_user.email, current_user.role
        if config is not None:
            return (
                config.get("adapters.auth.single_user.email", "operator@localhost"),
                config.get("adapters.auth.single_user.role", "admin"),
            )
        return "operator@localhost", "admin"

    def highlight_threshold() -> float:
        if config is not None:
            return float(config.get("confidence.field_highlight_below", 0.60))
        return 0.60

    # -- queue -------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def queue(request: Request, session: Session = Depends(get_session)):
        repo = Repository(session)
        tasks = repo.review_queue(limit=100)
        rows = []
        for task in tasks:
            run = session.get(WorkflowRun, task.workflow_run_id)
            profile = (run.envelope.get("results") or {}).get("profile") or {}
            personal = profile.get("personal_info") or {}
            flags = run.envelope.get("flags") or []
            rows.append({
                "task": task,
                "run": run,
                "name": personal.get("full_name") or "(no name extracted)",
                "requisition": run.requisition_id or "-",
                "confidence": run.confidence_aggregate,
                "reasons": (task.reasons or {}).get("reasons", []),
                "hallucination": "POTENTIAL_HALLUCINATION" in flags,
            })
        return templates.TemplateResponse(
            request, "queue.html",
            {"rows": rows, "threshold": highlight_threshold()},
        )

    # -- detail ------------------------------------------------------------
    @app.get("/review/{task_id}", response_class=HTMLResponse)
    def detail(task_id: int, request: Request, session: Session = Depends(get_session)):
        task = session.get(ReviewTask, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="No such review task")
        run = session.get(WorkflowRun, task.workflow_run_id)
        document = session.get(Document, run.document_id) if run.document_id else None

        envelope = run.envelope
        results = envelope.get("results") or {}
        profile = results.get("profile") or {}
        confidences: dict[str, float] = results.get("field_confidence") or {}

        # Source text lives on the ENVELOPE, not in results: the results schema
        # sets additionalProperties:false, so stashing it there would fail
        # validation on every run.
        source_text = envelope.get("source_text") or ""
        segments = _segment_source(source_text, envelope.get("evidence") or [])

        fields = _flatten_profile(profile, confidences, envelope.get("evidence") or [])

        return templates.TemplateResponse(
            request, "detail.html",
            {
                "task": task,
                "run": run,
                "document": document,
                "envelope": envelope,
                "fields": fields,
                "segments": segments,
                "validation": run.validation or {},
                "threshold": highlight_threshold(),
                "reject_reasons": REJECT_REASONS,
                "has_source": bool(source_text),
            },
        )

    # -- resolve -----------------------------------------------------------
    @app.post("/review/{task_id}/resolve")
    def resolve(
        task_id: int,
        decision: str = Form(...),
        reason_code: str = Form(default=""),
        note: str = Form(default=""),
        edits: str = Form(default=""),
        session: Session = Depends(get_session),
    ):
        task = session.get(ReviewTask, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="No such review task")
        if task.state in ("APPROVED", "REJECTED"):
            raise HTTPException(status_code=409, detail="This task is already resolved")

        state = {"approve": "APPROVED", "reject": "REJECTED",
                 "escalate": "ESCALATED"}.get(decision)
        if state is None:
            raise HTTPException(status_code=400, detail=f"Unknown decision: {decision}")
        if state == "REJECTED" and not reason_code:
            raise HTTPException(status_code=400,
                                detail="A rejection needs a reason code")

        parsed_edits: dict[str, Any] | None = None
        if edits.strip():
            try:
                parsed_edits = json.loads(edits)
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400,
                                    detail=f"Edits are not valid JSON: {exc}") from exc

        repo = Repository(session)
        run = session.get(WorkflowRun, task.workflow_run_id)
        email, role = actor()

        repo.resolve_review(task, reviewer=email, state=state,
                            reason_code=reason_code or None, edits=parsed_edits)

        repo.append_audit(
            event=f"review.{state.lower()}",
            actor=email, actor_role=role,
            workflow_run_id=run.id, workflow_id=run.workflow_id,
            candidate_id=run.candidate_id, requisition_id=run.requisition_id,
            prompt_version=run.prompt_version, model_id=run.model_id,
            detail={"reason_code": reason_code or None, "note": note or None,
                    "edited_fields": sorted(parsed_edits) if parsed_edits else []},
        )
        return RedirectResponse(url="/", status_code=303)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


# -- helpers ------------------------------------------------------------------
def _segment_source(source_text: str, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Split the source into plain and highlighted segments.

    Done server-side rather than with client-side search, because searching for
    the snippet text in the browser would highlight the wrong occurrence
    whenever a phrase appears twice. The offsets are authoritative.
    """
    if not source_text:
        return []

    spans = []
    for index, item in enumerate(evidence):
        start, end = item.get("char_start"), item.get("char_end")
        valid = isinstance(start, int) and isinstance(end, int)
        if valid and 0 <= start < end <= len(source_text):
            spans.append((start, end, index, item.get("field", "")))
    spans.sort()

    segments: list[dict[str, Any]] = []
    cursor = 0
    for start, end, index, field in spans:
        if start < cursor:      # overlapping citations; keep the first
            continue
        if start > cursor:
            segments.append({"text": source_text[cursor:start], "index": None, "field": None})
        segments.append({"text": source_text[start:end], "index": index, "field": field})
        cursor = end
    if cursor < len(source_text):
        segments.append({"text": source_text[cursor:], "index": None, "field": None})
    return segments


def _flatten_profile(
    profile: dict[str, Any],
    confidences: dict[str, float],
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Flatten the profile into displayable rows keyed by JSON Pointer."""
    evidence_by_pointer: dict[str, int] = {}
    for index, item in enumerate(evidence):
        pointer = item.get("pointer")
        if pointer:
            evidence_by_pointer.setdefault(pointer.replace("/profile", "", 1), index)

    rows: list[dict[str, Any]] = []

    def walk(node: Any, pointer: str, label: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{pointer}/{key}", key.replace("_", " "))
        elif isinstance(node, list):
            if node and all(not isinstance(v, (dict, list)) for v in node):
                rows.append(_row(pointer, label, ", ".join(str(v) for v in node)))
            else:
                for index, value in enumerate(node):
                    walk(value, f"{pointer}/{index}", f"{label} {index + 1}")
        else:
            if node is None or node == "":
                return
            rows.append(_row(pointer, label, node))

    def _row(pointer: str, label: str, value: Any) -> dict[str, Any]:
        return {
            "pointer": pointer,
            "label": label,
            "value": value,
            "confidence": confidences.get(pointer),
            "evidence_index": evidence_by_pointer.get(pointer),
        }

    walk(profile, "", "")
    return rows
