"""Authentication and RBAC tests.

The acceptance criterion for this phase: a signed-in hiring manager cannot reach
an admin route, and every decision names a real authenticated person.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from recruit import extract as extract_mod
from recruit.adapters.llm import FakeLLM
from recruit.auth import (
    PERMISSIONS,
    AuthError,
    PermissionDenied,
    Principal,
    hash_password,
    hash_token,
    verify_password,
)
from recruit.db.auth_repository import LocalAuth
from recruit.db.migrations import create_all, drop_all
from recruit.db.models import AuditLog, ReviewTask
from recruit.db.repository import Repository
from recruit.db.session import create_engine_from_config, make_session_factory, session_scope
from recruit.web.app import SESSION_COOKIE, create_app

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "wf03_fake_results.json"
RESUME = ROOT / "samples" / "Rahul_Sharma_Resume.pdf"


@pytest.fixture
def factory(tmp_path):
    engine = create_engine_from_config(url=f"sqlite:///{tmp_path / 'auth.db'}")
    drop_all(engine)
    create_all(engine)
    yield make_session_factory(engine)
    drop_all(engine)


@pytest.fixture
def auth(factory):
    adapter = LocalAuth(factory)
    adapter.create_user("admin@x.com", "correct-horse-battery",
                        display_name="Ada Admin", role="admin")
    adapter.create_user("hm@x.com", "correct-horse-battery",
                        display_name="Hana Manager", role="hiring_manager")
    adapter.create_user("rec@x.com", "correct-horse-battery",
                        display_name="Ravi Recruiter", role="recruiter")
    return adapter


@pytest.fixture
def client(factory, auth):
    return TestClient(create_app(session_factory=factory, auth_adapter=auth),
                      follow_redirects=False)


@pytest.fixture
def task_id(factory):
    if not (RESUME.is_file() and FIXTURE.is_file()):
        pytest.skip("fixtures not present")
    envelope = extract_mod.extract(RESUME, llm=FakeLLM(FIXTURE), root=ROOT)
    with session_scope(factory) as session:
        repo = Repository(session)
        repo.ensure_requisition("REQ-1", title="Engineer")
        repo.ensure_candidate("CAN-1", requisition_id="REQ-1")
        run, _ = repo.save_run(envelope, document_id=None)
        return repo.create_review_task(run).id


def sign_in(client, email: str) -> None:
    response = client.post("/login", data={"email": email,
                                           "password": "correct-horse-battery"})
    assert response.status_code == 303, response.text
    client.cookies.set(SESSION_COOKIE, response.cookies[SESSION_COOKIE])


# -- passwords ----------------------------------------------------------------
def test_password_roundtrip():
    encoded = hash_password("correct-horse-battery")
    assert encoded.startswith("scrypt$")
    assert "correct-horse-battery" not in encoded
    assert verify_password("correct-horse-battery", encoded)
    assert not verify_password("wrong", encoded)


def test_same_password_hashes_differently():
    """Per-password salt: identical passwords must not produce identical rows."""
    assert hash_password("same-password-x") != hash_password("same-password-x")


def test_short_password_is_refused():
    with pytest.raises(AuthError):
        hash_password("short")


def test_malformed_hash_fails_closed():
    """A corrupt row must not become an authentication bypass."""
    for broken in ("", "garbage", "scrypt$bad", "bcrypt$1$2$3$4$5", "scrypt$a$b$c$d$e"):
        assert verify_password("anything", broken) is False


# -- sessions -----------------------------------------------------------------
def test_session_token_is_stored_hashed(factory, auth):
    """A database dump must not yield usable cookies."""
    _, token = auth.login("admin@x.com", "correct-horse-battery")
    from sqlalchemy import select

    from recruit.db.models import Session as DbSession
    with factory() as db:
        stored = db.scalars(select(DbSession)).all()
    assert len(stored) == 1
    assert stored[0].token_hash != token
    assert stored[0].token_hash == hash_token(token)


def test_login_failures_are_indistinguishable(auth):
    assert auth.login("nobody@x.com", "correct-horse-battery") is None
    assert auth.login("admin@x.com", "wrong-password") is None


def test_logout_revokes_the_session(auth):
    _, token = auth.login("admin@x.com", "correct-horse-battery")
    assert auth.principal_for_token(token) is not None
    auth.logout(token)
    assert auth.principal_for_token(token) is None


def test_deactivating_a_user_kills_live_sessions(auth):
    """Otherwise a removed operator keeps working until their cookie expires."""
    _, token = auth.login("rec@x.com", "correct-horse-battery")
    assert auth.principal_for_token(token) is not None
    auth.deactivate("rec@x.com")
    assert auth.principal_for_token(token) is None
    assert auth.login("rec@x.com", "correct-horse-battery") is None


def test_expired_session_is_rejected(factory):
    adapter = LocalAuth(factory, session_hours=-1)      # already expired
    adapter.create_user("e@x.com", "correct-horse-battery", display_name="E")
    _, token = adapter.login("e@x.com", "correct-horse-battery")
    assert adapter.principal_for_token(token) is None


def test_unknown_token_is_rejected(auth):
    assert auth.principal_for_token("not-a-real-token") is None
    assert auth.principal_for_token("") is None


# -- roles --------------------------------------------------------------------
def test_recruiter_cannot_approve():
    """The human-in-the-loop boundary from Workflow_Spec.md section 15."""
    recruiter = Principal(email="r@x.com", display_name="R", role="recruiter")
    assert recruiter.can("review")
    assert recruiter.can("escalate")
    assert not recruiter.can("approve")
    with pytest.raises(PermissionDenied):
        recruiter.require("approve")


def test_unknown_role_is_rejected():
    with pytest.raises(AuthError, match="Unknown role"):
        Principal(email="x@x.com", display_name="X", role="ceo")


def test_only_admin_can_read_the_audit_log():
    holders = {role for role, perms in PERMISSIONS.items() if "read_audit" in perms}
    assert holders == {"admin", "auditor"}


# -- the acceptance criterion -------------------------------------------------
def test_hiring_manager_cannot_reach_an_admin_route(client):
    sign_in(client, "hm@x.com")
    assert client.get("/audit").status_code == 403


def test_forbidden_browser_gets_a_page_not_raw_json(client):
    sign_in(client, "hm@x.com")
    response = client.get("/audit", headers={"accept": "text/html"})
    assert response.status_code == 403
    assert "Your role does not permit this" in response.text


def test_admin_can_reach_the_admin_route(client):
    sign_in(client, "admin@x.com")
    assert client.get("/audit").status_code == 200


def test_signed_out_browser_is_redirected_to_sign_in(client):
    """A 401 with a Location header does nothing — browsers only follow
    Location on a 3xx, so an unauthenticated visitor saw raw JSON."""
    response = client.get("/", headers={"accept": "text/html"})
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_signed_out_browser_keeps_its_destination(client):
    response = client.get("/audit", headers={"accept": "text/html"})
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/audit"


def test_signed_out_api_client_gets_401(client):
    """A programmatic caller wants a status code, not a redirect to a form."""
    response = client.get("/", headers={"accept": "application/json"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Not signed in"


def test_sign_in_returns_you_to_where_you_were_going(client):
    response = client.post("/login", data={
        "email": "admin@x.com", "password": "correct-horse-battery",
        "next": "/audit"})
    assert response.status_code == 303
    assert response.headers["location"] == "/audit"


def test_next_cannot_be_used_as_an_open_redirect(client):
    """Otherwise a crafted sign-in link bounces the user to another site."""
    for hostile in ("https://evil.example.com/steal", "//evil.example.com"):
        response = client.post("/login", data={
            "email": "admin@x.com", "password": "correct-horse-battery",
            "next": hostile})
        assert response.headers["location"] == "/"


def test_recruiter_can_view_the_queue_but_not_approve(client, task_id):
    sign_in(client, "rec@x.com")
    assert client.get("/").status_code == 200
    denied = client.post(f"/review/{task_id}/resolve", data={"decision": "approve"})
    assert denied.status_code == 403
    allowed = client.post(f"/review/{task_id}/resolve", data={"decision": "escalate"})
    assert allowed.status_code == 303


def test_route_guard_not_template_guard(client, task_id):
    """Hiding a button is a courtesy. Typing the URL must still be refused."""
    sign_in(client, "rec@x.com")
    body = client.get(f"/review/{task_id}").text
    assert "Approve" in body          # button is rendered
    assert client.post(f"/review/{task_id}/resolve",
                       data={"decision": "approve"}).status_code == 403


# -- audit ties decisions to real people --------------------------------------
def test_decisions_record_the_authenticated_user(client, factory, task_id):
    sign_in(client, "hm@x.com")
    client.post(f"/review/{task_id}/resolve", data={"decision": "approve"})
    with session_scope(factory) as session:
        task = session.get(ReviewTask, task_id)
        assert task.reviewer == "hm@x.com"
        entry = session.query(AuditLog).filter(
            AuditLog.event == "review.approved").one()
        assert entry.actor == "hm@x.com"
        assert entry.actor_role == "hiring_manager"


def test_logins_and_failures_are_audited(client, factory):
    client.post("/login", data={"email": "admin@x.com", "password": "nope"})
    sign_in(client, "admin@x.com")
    with session_scope(factory) as session:
        events = [e.event for e in session.query(AuditLog).all()]
    assert "auth.login_failed" in events
    assert "auth.login" in events


def test_session_cookie_is_httponly_and_samesite(client):
    response = client.post("/login", data={"email": "admin@x.com",
                                           "password": "correct-horse-battery"})
    header = response.headers["set-cookie"].lower()
    assert "httponly" in header
    assert "samesite=lax" in header


# -- provider selection -------------------------------------------------------
def test_oidc_refuses_rather_than_falling_back(factory):
    """Configuring SSO and silently getting single-user auth is an incident."""
    from recruit.db.auth_repository import build_auth

    class Config:
        def get(self, key, default=None):
            return "oidc" if key == "adapters.auth.provider" else default

    with pytest.raises(NotImplementedError, match="not implemented"):
        build_auth(Config(), factory)
