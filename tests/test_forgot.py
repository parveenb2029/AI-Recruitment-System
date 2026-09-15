"""Getting back in, with nothing able to send an email.

Every product answers a forgotten password the same way: a link in your inbox.
**This one cannot send email at all** — Phase 6 receives applications, it does
not send anything, and there is no SMTP configuration to borrow. A screen
saying "check your inbox" when nothing was sent would be the worst page in the
product.

So the answer depends on something a person can verify about themselves rather
than on a secret they no longer have: are you at the machine this is running
on? If yes, you already have the database file and the command-line tools, and
a browser form grants you nothing new. If no, somebody with an account has to
help, and the page says exactly what to ask them for.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from recruit import hosting
from recruit.db.auth_repository import LocalAuth
from recruit.db.migrations import create_all
from recruit.db.session import make_session_factory
from recruit.web.app import create_app


@pytest.fixture
def auth(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'forgot.db'}")
    create_all(engine)
    factory = make_session_factory(engine)
    adapter = LocalAuth(factory)
    adapter.create_user("k@example.com", "the original passphrase",
                        display_name="K", role="admin")
    return adapter, factory


@pytest.fixture
def client(auth):
    """A browser on the machine itself."""
    adapter, factory = auth
    app = create_app(session_factory=factory, auth_adapter=adapter)
    # `client=` matters: TestClient presents itself as the host "testclient"
    # by default, which is not loopback and which this route correctly
    # refuses. Saying 127.0.0.1 out loud is also documentation — the fixture
    # names the condition the test is about.
    return TestClient(app, follow_redirects=False,
                      headers={"accept": "text/html"},
                      client=("127.0.0.1", 45001))


@pytest.fixture
def from_the_network(auth):
    """A browser on another machine on the same network.

    This is the case `is_public()` cannot see: a console started with
    `--host 0.0.0.0` on somebody's laptop sets no platform environment
    variable, so nothing marks it public, and every machine in the building
    can reach it.
    """
    adapter, factory = auth
    app = create_app(session_factory=factory, auth_adapter=adapter)
    return TestClient(app, follow_redirects=False,
                      headers={"accept": "text/html"},
                      client=("192.168.1.44", 45002))


@pytest.fixture(autouse=True)
def not_public(monkeypatch):
    monkeypatch.setenv("RECRUIT_PUBLIC", "0")


# -- who is asking ------------------------------------------------------------
def test_at_the_machine_you_can_set_a_new_password(client, auth):
    adapter, _ = auth

    response = client.post("/forgot", data={
        "email": "k@example.com",
        "password": "a brand new passphrase",
        "confirm": "a brand new passphrase",
    })

    assert response.status_code == 200
    assert "Password changed" in response.text
    assert adapter.login("k@example.com", "a brand new passphrase") is not None
    assert adapter.login("k@example.com", "the original passphrase") is None


def test_the_reset_form_is_offered_at_the_machine(client):
    text = client.get("/forgot").text
    assert "Set a new password" in text
    assert 'action="/forgot"' in text


def test_from_another_machine_there_is_no_form_at_all(from_the_network):
    """A console started with --host 0.0.0.0 is reachable by the whole office.

    `is_public()` would call that deployment private, because no hosting
    platform set an environment variable. The question that matters here is not
    what kind of deployment this is — it is who is knocking.
    """
    text = from_the_network.get("/forgot").text

    assert "Set a new password" not in text
    assert "cannot send email" in text


def test_from_another_machine_the_post_is_refused(from_the_network, auth):
    adapter, _ = auth

    response = from_the_network.post("/forgot", data={
        "email": "k@example.com", "password": "somebody elses passphrase",
        "confirm": "somebody elses passphrase",
    })

    assert response.status_code == 404
    assert adapter.login("k@example.com", "the original passphrase") is not None


def test_the_loopback_rule_itself():
    assert hosting.is_from_this_machine("127.0.0.1") is True
    assert hosting.is_from_this_machine("::1") is True
    assert hosting.is_from_this_machine("192.168.1.44") is False
    assert hosting.is_from_this_machine("10.0.0.7") is False
    assert hosting.is_from_this_machine(None) is False


def test_a_public_deployment_never_offers_a_self_service_reset(client, monkeypatch):
    """Even from loopback. On a server, "I am on the box" is not identity —
    every request arrives through a proxy that may well be on the box."""
    monkeypatch.setenv("RECRUIT_PUBLIC", "1")

    text = client.get("/forgot").text
    assert "Set a new password" not in text
    assert "cannot send email" in text


def test_a_public_deployment_refuses_the_post_too(client, auth, monkeypatch):
    """The form is a convenience; the route is the boundary."""
    adapter, _ = auth
    monkeypatch.setenv("RECRUIT_PUBLIC", "1")

    response = client.post("/forgot", data={
        "email": "k@example.com", "password": "attacker chosen passphrase",
        "confirm": "attacker chosen passphrase",
    })

    assert response.status_code == 404
    assert adapter.login("k@example.com", "the original passphrase") is not None


# -- what it tells somebody who cannot reset here ------------------------------
def test_it_never_claims_an_email_was_sent(client, monkeypatch):
    """The failure mode this page exists to avoid."""
    monkeypatch.setenv("RECRUIT_PUBLIC", "1")
    text = client.get("/forgot").text.lower()

    assert "check your inbox" not in text
    assert "sent you" not in text
    assert "cannot send email" in text


def test_it_names_the_two_real_ways_back_in(client, monkeypatch):
    monkeypatch.setenv("RECRUIT_PUBLIC", "1")
    text = client.get("/forgot").text

    assert "Reset password" in text                 # what to ask an admin for
    assert "recruit.users set-password" in text     # and the command


# -- the rules that apply wherever a password is chosen ------------------------
def test_a_wordlist_password_is_refused_here_too(client, auth):
    adapter, _ = auth
    response = client.post("/forgot", data={
        "email": "k@example.com", "password": "password1", "confirm": "password1",
    })

    assert response.status_code == 400
    assert "most-guessed" in response.text
    assert adapter.login("k@example.com", "the original passphrase") is not None


def test_mismatched_passwords_change_nothing(client, auth):
    adapter, _ = auth
    response = client.post("/forgot", data={
        "email": "k@example.com", "password": "a brand new passphrase",
        "confirm": "a different passphrase",
    })

    assert response.status_code == 400
    assert adapter.login("k@example.com", "the original passphrase") is not None


def test_an_unknown_account_says_so_plainly(client):
    """Deliberately NOT the silence a sign-in form gives.

    A login form hides whether an account exists, because an attacker can
    harvest that. This form is only reachable from the machine itself, where
    the person can already list the accounts — so being unhelpful buys nothing
    and costs somebody a confusing afternoon.
    """
    response = client.post("/forgot", data={
        "email": "nobody@example.com", "password": "a brand new passphrase",
        "confirm": "a brand new passphrase",
    })

    assert response.status_code == 400
    assert "No user" in response.text


def test_resetting_signs_everyone_out_of_that_account(client, auth):
    """A password you had to reset is one somebody else might know."""
    adapter, _ = auth
    _, token = adapter.login("k@example.com", "the original passphrase")
    assert adapter.principal_for_token(token) is not None

    client.post("/forgot", data={
        "email": "k@example.com", "password": "a brand new passphrase",
        "confirm": "a brand new passphrase",
    })

    assert adapter.principal_for_token(token) is None


def test_the_reset_is_written_to_the_audit_log(client, auth):
    from sqlalchemy import select

    from recruit.db.models import AuditLog

    adapter, factory = auth
    client.post("/forgot", data={
        "email": "k@example.com", "password": "a brand new passphrase",
        "confirm": "a brand new passphrase",
    })

    with factory() as db:
        events = [row.event for row in db.scalars(select(AuditLog))]
    assert "auth.password_reset_locally" in events


# -- the way in, from the sign-in screen ---------------------------------------
def test_the_sign_in_page_offers_the_link(client):
    """A way out that nobody can find is not a way out."""
    assert 'href="/forgot"' in client.get("/login").text
