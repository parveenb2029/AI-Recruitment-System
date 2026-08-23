"""FastAPI application for the review console."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import Cookie, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import PermissionDenied, Principal
from ..db.auth_repository import build_auth
from ..db.models import AuditLog, Document, ReviewTask, WorkflowRun
from ..db.repository import Repository
from ..db.session import create_engine_from_config, make_session_factory

SESSION_COOKIE = "recruit_session"


class NotAuthenticated(Exception):
    """Nobody is signed in.

    Raised rather than returning a response so the handler can decide the shape:
    a browser wants a redirect to the sign-in page, an API client wants 401.
    A 401 carrying a Location header does nothing — browsers only follow
    Location on a 3xx.
    """


class Forbidden(Exception):
    """Signed in, but lacking the permission this route requires."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _wants_html(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "")

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
    auth_adapter: Any | None = None,
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

    auth = auth_adapter or build_auth(config, session_factory)

    def current_principal(
        recruit_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    ) -> Principal | None:
        if current_user is not None:
            return current_user
        return auth.principal_for_token(recruit_session or "")

    def require_login(
        principal: Principal | None = Depends(current_principal),
    ) -> Principal:
        if principal is None:
            raise NotAuthenticated
        return principal

    def require(permission: str):
        """Route-level authorization.

        Hiding a button in a template is a courtesy; anyone can still type the
        URL. Every protected route declares the permission it needs here.
        """
        def dependency(principal: Principal = Depends(require_login)) -> Principal:
            try:
                principal.require(permission)
            except PermissionDenied as denied:
                raise Forbidden(str(denied)) from denied
            return principal
        return dependency

    def highlight_threshold() -> float:
        if config is not None:
            return float(config.get("confidence.field_highlight_below", 0.60))
        return 0.60

    # -- queue -------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def queue(request: Request, session: Session = Depends(get_session),
              principal: Principal = Depends(require("review"))):
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
            {"rows": rows, "threshold": highlight_threshold(), "principal": principal},
        )

    # -- detail ------------------------------------------------------------
    @app.get("/review/{task_id}", response_class=HTMLResponse)
    def detail(task_id: int, request: Request,
               session: Session = Depends(get_session),
               principal: Principal = Depends(require("review"))):
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
                "principal": principal,
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
        principal: Principal = Depends(require_login),
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

        # A recruiter may escalate but not decide. That boundary is the
        # human-in-the-loop rule from Workflow_Spec.md section 15, and it lives
        # here rather than in the template.
        needed = {"APPROVED": "approve", "REJECTED": "reject",
                  "ESCALATED": "escalate"}[state]
        try:
            principal.require(needed)
        except PermissionDenied as denied:
            raise Forbidden(str(denied)) from denied
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
        email, role = principal.email, principal.role

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

    # -- login -------------------------------------------------------------
    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request, error: str | None = None,
                   next: str | None = None):
        return templates.TemplateResponse(
            request, "login.html",
            {"error": error, "next": next,
             "requires_login": getattr(auth, "requires_login", True)},
        )

    @app.post("/login")
    def login(email: str = Form(...), password: str = Form(...),
              next: str = Form(default="/"),
              session: Session = Depends(get_session)):
        result = auth.login(email, password)
        if result is None:
            # One message for every failure. Distinguishing "no such user" from
            # "wrong password" hands an attacker a list of valid accounts.
            Repository(session).append_audit(
                event="auth.login_failed", actor=email or "(blank)",
                actor_role=None, detail={"reason": "invalid_credentials"},
            )
            return RedirectResponse(url="/login?error=1", status_code=303)

        principal, token = result
        Repository(session).append_audit(
            event="auth.login", actor=principal.email, actor_role=principal.role,
        )
        # Only relative paths, or the ?next= parameter becomes an open redirect.
        destination = next if next.startswith("/") and not next.startswith("//") else "/"
        response = RedirectResponse(url=destination, status_code=303)
        response.set_cookie(
            SESSION_COOKIE, token,
            httponly=True,       # not readable by JavaScript
            samesite="lax",      # not sent on cross-site POSTs
            secure=bool(config.get("adapters.auth.local.secure_cookie", False))
            if config else False,
            max_age=60 * 60 * 12,
        )
        return response

    @app.post("/logout")
    def logout(recruit_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
               session: Session = Depends(get_session)):
        principal = auth.principal_for_token(recruit_session or "")
        if principal is not None:
            Repository(session).append_audit(
                event="auth.logout", actor=principal.email, actor_role=principal.role,
            )
        auth.logout(recruit_session or "")
        response = RedirectResponse(url="/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE)
        return response

    # -- audit trail (compliance) -----------------------------------------
    @app.get("/audit", response_class=HTMLResponse)
    def audit_log(request: Request, session: Session = Depends(get_session),
                  principal: Principal = Depends(require("read_audit")),
                  limit: int = 200):
        entries = list(session.scalars(
            select(AuditLog).order_by(AuditLog.occurred_at.desc(),
                                      AuditLog.id.desc()).limit(min(limit, 1000))
        ))
        return templates.TemplateResponse(
            request, "audit.html", {"entries": entries, "principal": principal},
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    # -- error handling ----------------------------------------------------
    @app.exception_handler(NotAuthenticated)
    def _not_authenticated(request: Request, _exc: NotAuthenticated):
        if _wants_html(request):
            # Preserve where they were headed so sign-in returns them there.
            target = request.url.path
            suffix = f"?next={target}" if target not in ("/", "/login") else ""
            return RedirectResponse(url=f"/login{suffix}", status_code=303)
        return JSONResponse({"detail": "Not signed in"}, status_code=401)

    @app.exception_handler(Forbidden)
    def _forbidden(request: Request, exc: Forbidden):
        if _wants_html(request):
            return templates.TemplateResponse(
                request, "forbidden.html", {"message": exc.message}, status_code=403,
            )
        return JSONResponse({"detail": exc.message}, status_code=403)

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
