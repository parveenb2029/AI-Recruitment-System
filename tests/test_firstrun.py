"""The first account, claimed from a browser instead of a server log.

`bootstrap` generates a password on first start and prints it once. That is
right on a hosting dashboard and impossible everywhere else: somebody who has
just double-clicked an installer has no log, no terminal, and no reason to know
one exists. It was the single step a non-technical person could not complete.

Replacing it opens a hole — a console with no accounts is a console anyone can
claim — so most of this file is about the ways `/setup` must refuse, and only a
little of it is about the way it works.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from recruit import firstrun
from recruit.auth import AuthError, check_password_quality
from recruit.db.auth_repository import LocalAuth
from recruit.db.migrations import create_all
from recruit.db.session import make_session_factory
from recruit.web.app import create_app


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'setup.db'}")
    create_all(engine)
    return make_session_factory(engine)


@pytest.fixture
def auth(factory):
    return LocalAuth(factory)


@pytest.fixture
def client(factory, auth):
    app = create_app(session_factory=factory, auth_adapter=auth)
    # A browser announces that it wants HTML, and the console's redirect-versus-
    # 401 behaviour turns on exactly that. A client that omits it is testing the
    # API path while claiming to test the screen.
    return TestClient(app, follow_redirects=False,
                      headers={"accept": "text/html"})


@pytest.fixture(autouse=True)
def not_public(monkeypatch):
    """Default every test to a laptop. The public cases opt in explicitly."""
    monkeypatch.setenv("RECRUIT_PUBLIC", "0")
    monkeypatch.delenv(firstrun.SETUP_TOKEN_ENV, raising=False)


# -- the wall this removes ----------------------------------------------------
def test_a_fresh_console_opens_on_setup_rather_than_an_unpassable_login(client):
    """The whole point, in one assertion.

    Before this, a new install redirected to a sign-in form with no credentials
    in existence — a dead end unless you knew to read a log.
    """
    response = client.get("/")

    assert response.status_code == 303
    assert response.headers["location"] == "/setup"


def test_creating_the_first_account_signs_you_straight_in(client, auth):
    """No retyping the password chosen four seconds ago."""
    response = client.post("/setup", data={
        "email": "K@Example.com", "password": "correct horse battery",
        "confirm": "correct horse battery", "display_name": "K",
    })

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert response.cookies.get("recruit_session")

    (user,) = auth.list_users()
    assert user.email == "k@example.com"      # normalised, not stored as typed
    assert user.role == "admin"               # the first account owns the copy
    assert user.display_name == "K"


def test_the_name_is_optional_and_tidied_the_same_way_everywhere(client, auth):
    """`Priya.Nair` versus `Priya Nair` was a real defect. One rule, one place."""
    client.post("/setup", data={"email": "priya.nair@example.com",
                                "password": "a longer passphrase"})

    (user,) = auth.list_users()
    assert user.display_name == "Priya Nair"


# -- the ways it must refuse --------------------------------------------------
def test_setup_is_gone_for_good_once_an_account_exists(client, auth):
    auth.create_user("first@example.com", "a longer passphrase",
                     display_name="First", role="admin")

    assert client.get("/setup").status_code == 404
    assert client.post("/setup", data={"email": "second@example.com",
                                       "password": "another passphrase"}).status_code == 404
    assert len(auth.list_users()) == 1


def test_a_closed_setup_answers_404_and_not_403(client, auth):
    """403 confirms there is a configured console here.

    That is a true fact about somebody else's system, harvestable by probing.
    404 says nothing at all, which is the cheaper answer and the same one the
    Phase 7 plan reaches for cross-workspace reads.
    """
    auth.create_user("first@example.com", "a longer passphrase",
                     display_name="First", role="admin")

    response = client.get("/setup")
    assert response.status_code == 404
    assert "403" not in response.text


def test_an_account_already_existing_sends_you_to_login_not_setup(client, auth):
    auth.create_user("first@example.com", "a longer passphrase",
                     display_name="First", role="admin")

    response = client.get("/")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_mismatched_passwords_do_not_create_anything(client, auth):
    response = client.post("/setup", data={
        "email": "k@example.com", "password": "a longer passphrase",
        "confirm": "a different passphrase",
    })

    assert response.status_code == 400
    assert "not the same" in response.text
    assert auth.list_users() == []


def test_a_password_from_a_wordlist_is_refused_in_the_browser_too(client, auth):
    """The rule existed only on the command line, which is not a rule.

    The CLI has refused the obvious passwords since Phase 5.1. A browser path
    that accepted them would mean the enforced policy depended on which door
    somebody walked through.
    """
    response = client.post("/setup", data={
        "email": "k@example.com", "password": "password1", "confirm": "password1",
    })

    assert response.status_code == 400
    assert "most-guessed" in response.text
    assert auth.list_users() == []


def test_a_short_password_is_refused_with_a_sentence_not_a_traceback(client):
    response = client.post("/setup", data={"email": "k@example.com",
                                           "password": "short", "confirm": "short"})

    assert response.status_code == 400
    assert "at least 8 characters" in response.text


# -- public deployments -------------------------------------------------------
def test_a_public_deployment_with_no_token_has_no_setup_page_at_all(client, monkeypatch):
    """Fail closed.

    Between an instance starting and its owner first visiting it, whoever
    reaches /setup first becomes its administrator — and on a public URL that is
    everyone. An unset variable is somebody who has not made a decision, so the
    door stays shut and `bootstrap` remains the way in.
    """
    monkeypatch.setenv("RECRUIT_PUBLIC", "1")

    assert client.get("/setup").status_code == 404
    # And the unauthenticated redirect must not advertise it either.
    assert client.get("/").headers["location"] == "/login"


def test_a_public_deployment_with_a_token_accepts_only_that_token(client, auth, monkeypatch):
    monkeypatch.setenv("RECRUIT_PUBLIC", "1")
    monkeypatch.setenv(firstrun.SETUP_TOKEN_ENV, "s3cret-from-the-dashboard")

    assert client.get("/setup").status_code == 404
    assert client.get("/setup?token=wrong").status_code == 404
    assert client.get("/setup?token=s3cret-from-the-dashboard").status_code == 200

    created = client.post("/setup", data={
        "email": "k@example.com", "password": "a longer passphrase",
        "confirm": "a longer passphrase", "token": "s3cret-from-the-dashboard",
    })
    assert created.status_code == 303
    assert len(auth.list_users()) == 1


def test_the_token_is_re_checked_on_post_not_trusted_from_the_form(client, auth,
                                                                   monkeypatch):
    """The form is a convenience; the route is the boundary.

    Same rule as every permission in this console — checked where the request
    arrives, never in a template.
    """
    monkeypatch.setenv("RECRUIT_PUBLIC", "1")
    monkeypatch.setenv(firstrun.SETUP_TOKEN_ENV, "s3cret-from-the-dashboard")

    response = client.post("/setup", data={
        "email": "attacker@example.com", "password": "a longer passphrase",
        "confirm": "a longer passphrase", "token": "",
    })

    assert response.status_code == 404
    assert auth.list_users() == []


def test_a_wrong_token_is_indistinguishable_from_setup_being_finished(client, monkeypatch):
    """Both answer 404, deliberately.

    Saying "wrong token" confirms that setup is open and that guessing is worth
    continuing. Saying nothing tells a prober to go away.
    """
    monkeypatch.setenv("RECRUIT_PUBLIC", "1")
    monkeypatch.setenv(firstrun.SETUP_TOKEN_ENV, "s3cret-from-the-dashboard")

    wrong = client.get("/setup?token=nearly-right")
    assert wrong.status_code == 404
    assert "token" not in wrong.text.lower()


# -- the policy, without a web server -----------------------------------------
def test_the_policy_can_be_read_without_starting_a_console(auth, monkeypatch):
    """`firstrun` holds the rule so it is testable and reviewable on its own."""
    monkeypatch.setenv("RECRUIT_PUBLIC", "0")
    assert firstrun.needs_setup(auth) is True
    assert firstrun.setup_is_available(auth) is True
    assert firstrun.token_is_required() is False

    monkeypatch.setenv("RECRUIT_PUBLIC", "1")
    assert firstrun.token_is_required() is True
    assert firstrun.setup_is_available(auth) is False       # no token configured

    monkeypatch.setenv(firstrun.SETUP_TOKEN_ENV, "abc")
    assert firstrun.setup_is_available(auth) is True


def test_an_empty_token_never_satisfies_a_required_one(monkeypatch):
    """The empty-versus-empty case is the one that quietly opens the door."""
    monkeypatch.setenv("RECRUIT_PUBLIC", "1")
    monkeypatch.delenv(firstrun.SETUP_TOKEN_ENV, raising=False)

    assert firstrun.token_matches("") is False
    assert firstrun.token_matches(None) is False
    assert firstrun.token_matches("anything") is False


def test_an_adapter_with_no_accounts_has_nothing_to_set_up():
    """`single_user` mode has one hardcoded operator and no user table.

    Offering a setup screen there would invite somebody to create an account
    that nothing would ever read.
    """
    from recruit.auth import SingleUserAuth

    assert firstrun.needs_setup(SingleUserAuth()) is False
    assert firstrun.setup_is_available(SingleUserAuth()) is False


def test_a_database_that_is_not_ready_is_not_mistaken_for_an_open_console():
    """An error counting users must not read as "nobody has claimed this"."""
    class Broken:
        def list_users(self):
            raise RuntimeError("no such table: users")

    assert firstrun.needs_setup(Broken()) is False


def test_the_operator_gets_a_reason_rather_than_a_silent_404(auth, monkeypatch):
    """A 404 with no explanation anywhere looks like a broken deployment."""
    monkeypatch.setenv("RECRUIT_PUBLIC", "1")
    monkeypatch.delenv(firstrun.SETUP_TOKEN_ENV, raising=False)

    reason = firstrun.why_unavailable(auth)
    assert firstrun.SETUP_TOKEN_ENV in reason
    assert "bootstrap" in reason


# -- the shared rule ----------------------------------------------------------
def test_password_quality_is_one_function_used_by_both_doors():
    with pytest.raises(AuthError, match="at least 8"):
        check_password_quality("short")
    with pytest.raises(AuthError, match="most-guessed"):
        check_password_quality("Password1")     # case must not evade the list
    check_password_quality("a longer passphrase")


def test_the_command_line_and_the_browser_refuse_the_same_passwords():
    """They diverged once; a test is cheaper than noticing again."""
    from recruit import users

    for weak in sorted(users.OBVIOUS_PASSWORDS):
        with pytest.raises(AuthError):
            check_password_quality(weak)
