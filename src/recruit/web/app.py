"""FastAPI application for the review console."""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

from fastapi import Cookie, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import confidence, firstrun, hosting
from ..auth import (
    ROLES,
    AuthError,
    PermissionDenied,
    Principal,
    check_password_quality,
)
from ..db.auth_repository import build_auth
from ..db.models import AuditLog, Document, ReviewTask, WorkflowRun
from ..db.repository import Repository
from ..db.session import create_engine_from_config, make_session_factory
from . import humanize

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
# The wording lives in `humanize` so the dropdown, the audit sentence, and the
# rejection summary cannot drift into three different phrasings of one reason.
REJECT_REASONS = list(humanize.REJECT_REASONS.items())

# Roles an administrator can assign, with the wording the console uses. Built
# from the auth module's ROLES so a new role cannot appear in one place and not
# the other.
ROLE_CHOICES = [(r, humanize.ROLES.get(r, r)) for r in ROLES]


def create_app(
    session_factory: Any | None = None,
    config: Any | None = None,
    current_user: Any | None = None,
    auth_adapter: Any | None = None,
) -> FastAPI:
    app = FastAPI(title="Review Console", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=str(TEMPLATES))
    # Plain-language filters. Registered here rather than imported per template
    # so there is one place to see everything the console translates, and one
    # place a test can enumerate.
    templates.env.filters.update({
        "event_title": humanize.event_title,
        "describe_event": humanize.describe_event,
        "actor_name": humanize.actor_name,
        "role_name": humanize.role_name,
        "state_name": humanize.state_name,
        "review_reason": humanize.review_reason,
        "reject_reason": humanize.reject_reason,
        "rule_name": humanize.rule_name,
        "severity_name": humanize.severity_name,
        "confidence_phrase": humanize.confidence_phrase,
        "detail_pairs": humanize.detail_pairs,
        "is_concerning": humanize.is_concerning,
        "field_label": humanize.field_label,
        "field_value": humanize.field_value,
    })

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
        confidences: dict[str, float] = confidence.read(results)

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

    # -- first run ----------------------------------------------------------
    # The one step that a non-technical person could not complete: the very
    # first password was generated into a server log. The policy about who may
    # claim the first account lives in `recruit.firstrun`, not here, so that the
    # rule can be read and tested without starting a web server.
    def _setup_closed() -> None:
        """404, never 403.

        A 403 says "there is a configured console at this address", which is a
        true fact about somebody else's system that a stranger should not be
        able to harvest by probing. 404 says nothing at all.
        """
        raise HTTPException(status_code=404, detail="Not found")

    def _setup_page(request: Request, *, token: str | None,
                    problem: str | None = None, email: str = "",
                    status_code: int = 200):
        return templates.TemplateResponse(
            request, "setup.html",
            {"problem": problem, "email": email, "token": token or "",
             "token_required": firstrun.token_is_required()},
            status_code=status_code,
        )

    @app.get("/setup", response_class=HTMLResponse)
    def setup_form(request: Request, token: str | None = None):
        if not firstrun.setup_is_available(auth):
            _setup_closed()
        if not firstrun.token_matches(token):
            # Deliberately the same answer as "setup is finished". Telling a
            # prober that the token was merely wrong confirms both that setup is
            # open and that guessing is worth continuing.
            _setup_closed()
        return _setup_page(request, token=token)

    @app.post("/setup", response_class=HTMLResponse)
    def setup_submit(request: Request,
                     email: str = Form(...),
                     password: str = Form(...),
                     confirm: str = Form(default=""),
                     display_name: str = Form(default=""),
                     token: str = Form(default=""),
                     session: Session = Depends(get_session)):
        # Re-checked on POST rather than trusted from the GET. The form is a
        # convenience; the route is the boundary, the same way every other
        # permission in this console is enforced at the route and not in a
        # template.
        if not firstrun.setup_is_available(auth) or not firstrun.token_matches(token):
            _setup_closed()

        if confirm and password != confirm:
            return _setup_page(request, token=token, email=email,
                               problem="Those two passwords are not the same.",
                               status_code=400)
        try:
            check_password_quality(password)
            principal = auth.create_user(
                email, password,
                display_name=display_name.strip() or humanize.actor_name(email),
                role="admin",
            )
        except AuthError as denied:
            return _setup_page(request, token=token, email=email,
                               problem=str(denied), status_code=400)

        # Sign them in rather than sending them to a login screen to retype the
        # password they chose four seconds ago. `login` is used rather than
        # minting a token here so there is one code path that issues sessions.
        #
        # **Before the audit write, deliberately.** The auth adapter opens its
        # own database session; writing to the request's session first takes a
        # write lock that the adapter's session then waits on, and on SQLite —
        # the default install, per hard rule 9 — that is a deadlock, not a
        # slowdown. Found by the tests for this route, on the database everyone
        # who installs this actually gets.
        result = auth.login(email, password)

        Repository(session).append_audit(
            event="auth.first_run_setup", actor=principal.email,
            actor_role=principal.role,
            detail={"account": principal.email, "via": "browser"},
        )

        response = RedirectResponse(url="/", status_code=303)
        if result is not None:
            _, session_token = result
            response.set_cookie(
                SESSION_COOKIE, session_token,
                httponly=True, samesite="lax",
                secure=hosting.secure_cookie(config) if config else False,
                max_age=60 * 60 * 12,
            )
        return response

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
            secure=hosting.secure_cookie(config)
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

    # -- team ---------------------------------------------------------------
    # The permission `manage_users` has existed on the admin role since Phase
    # 5.1 and was never wired to anything, because accounts were created from a
    # terminal. That assumption breaks the moment someone deploys this with one
    # click and has no terminal to use.
    def _accounts_or_none():
        """Accounts, or None when the configured adapter has no notion of them.

        `single_user` mode has one hardcoded operator and no user table. Showing
        an empty team page there would suggest everyone had been deleted.
        """
        lister = getattr(auth, "accounts", None)
        return lister() if callable(lister) else None

    def _team_page(request: Request, principal: Principal, *,
                   invited: tuple[str, str] | None = None,
                   problem: str | None = None,
                   status_code: int = 200):
        return templates.TemplateResponse(
            request, "team.html",
            {
                "accounts": _accounts_or_none(),
                "roles": ROLE_CHOICES,
                "principal": principal,
                "invited": invited,
                "problem": problem,
            },
            status_code=status_code,
        )

    @app.get("/team", response_class=HTMLResponse)
    def team(request: Request,
             principal: Principal = Depends(require("manage_users"))):
        return _team_page(request, principal)

    @app.post("/team/add", response_class=HTMLResponse)
    def team_add(request: Request,
                 email: str = Form(...),
                 display_name: str = Form(default=""),
                 role: str = Form(default="recruiter"),
                 principal: Principal = Depends(require("manage_users"))):
        # The password is generated rather than chosen. An administrator
        # inventing passwords for other people produces weak, reused ones, and
        # this way there is nothing to email — it is shown once, on this page.
        password = secrets.token_urlsafe(12)
        try:
            auth.create_user(
                email, password,
                # Through humanize, not `email.split("@")[0]`: the raw local
                # part put "Priya.Nair" in the people table while the audit log
                # for the same account said "Priya Nair". One tidying rule, in
                # one place, or the two screens disagree about who someone is.
                display_name=display_name.strip() or humanize.actor_name(email),
                role=role, actor=principal,
            )
        except AuthError as denied:
            return _team_page(request, principal, problem=str(denied),
                              status_code=400)
        return _team_page(request, principal,
                          invited=(email.strip().lower(), password))

    @app.post("/team/update", response_class=HTMLResponse)
    def team_update(request: Request,
                    email: str = Form(...),
                    action: str = Form(...),
                    role: str = Form(default=""),
                    principal: Principal = Depends(require("manage_users"))):
        try:
            if action == "set_role":
                auth.set_role(email, role, actor=principal)
            elif action == "deactivate":
                auth.deactivate(email, actor=principal)
            elif action == "reactivate":
                auth.reactivate(email, actor=principal)
            elif action == "reset_password":
                password = secrets.token_urlsafe(12)
                auth.set_password(email, password, actor=principal)
                return _team_page(request, principal,
                                  invited=(email.strip().lower(), password))
            else:
                raise HTTPException(status_code=400,
                                    detail=f"Unknown action: {action}")
        except AuthError as denied:
            return _team_page(request, principal, problem=str(denied),
                              status_code=400)
        return _team_page(request, principal)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    # -- error handling ----------------------------------------------------
    @app.exception_handler(NotAuthenticated)
    def _not_authenticated(request: Request, _exc: NotAuthenticated):
        if _wants_html(request):
            # A brand-new install has no credentials to type. Sending someone to
            # a sign-in screen they cannot possibly pass is the wall this phase
            # exists to remove, so an unconfigured console opens on setup
            # instead. Only where setup is actually available — on a public
            # deployment with no token configured it is not, and /login with the
            # bootstrap path behind it remains the honest answer.
            if firstrun.setup_is_available(auth):
                return RedirectResponse(url="/setup", status_code=303)
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
            "label": humanize.field_label(label),
            "value": humanize.field_value(value),
            "confidence": confidences.get(pointer),
            "evidence_index": evidence_by_pointer.get(pointer),
        }

    walk(profile, "", "")
    return rows
