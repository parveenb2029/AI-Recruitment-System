"""Managing people without a terminal.

The console was built for a team that shares one machine and one command line.
Self-hosting breaks that assumption: someone who deploys this with one click has
a browser and nothing else, so every account operation has to be reachable from
the web — and every one of them has to be as guarded there as it was on the
command line.

Two things are defended:

1. **The guard is on the route.** Hiding the Team link from a recruiter is
   decoration; typing the URL must still be refused.
2. **Nobody can lock the last administrator out.** On a hosted deployment there
   is no shell to recover from, so a single careless click would mean redeploying
   from scratch and losing the data.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from recruit.auth import AuthError
from recruit.db.auth_repository import LocalAuth
from recruit.db.migrations import create_all, drop_all
from recruit.db.models import AuditLog, User
from recruit.db.session import create_engine_from_config, make_session_factory, session_scope
from recruit.web.app import create_app

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def factory(tmp_path):
    engine = create_engine_from_config(url=f"sqlite:///{tmp_path / 'team.db'}")
    drop_all(engine)
    create_all(engine)
    return make_session_factory(engine)


@pytest.fixture
def auth(factory):
    return LocalAuth(factory)


@pytest.fixture
def people(auth):
    auth.create_user("boss@x.com", "boss-password", display_name="Boss", role="admin")
    auth.create_user("rec@x.com", "rec-password", display_name="Rec", role="recruiter")
    return auth


@pytest.fixture
def client(factory, people):
    return TestClient(create_app(session_factory=factory, auth_adapter=people))


def sign_in_via_form(client, email, password):
    response = client.post("/login", data={"email": email, "password": password},
                           follow_redirects=False)
    assert response.status_code == 303, response.text
    return response


def audit_events(factory):
    with session_scope(factory) as session:
        return [row.event for row in session.scalars(select_audit())]


def select_audit():
    from sqlalchemy import select
    return select(AuditLog).order_by(AuditLog.id)


# -- the route guard ----------------------------------------------------------
def test_a_recruiter_cannot_reach_the_team_page_by_typing_the_url(client):
    """Hiding the link is a courtesy. The route is the actual control."""
    sign_in_via_form(client, "rec@x.com", "rec-password")

    assert client.get("/team").status_code == 403
    assert client.post("/team/add", data={"email": "new@x.com"}).status_code == 403
    assert client.post("/team/update",
                       data={"email": "boss@x.com", "action": "deactivate"}
                       ).status_code == 403


def test_a_recruiter_never_sees_the_team_link(client):
    sign_in_via_form(client, "rec@x.com", "rec-password")
    assert 'href="/team"' not in client.get("/").text


def test_an_admin_sees_the_link_and_the_page(client):
    sign_in_via_form(client, "boss@x.com", "boss-password")
    assert 'href="/team"' in client.get("/").text

    page = client.get("/team")
    assert page.status_code == 200
    assert "rec@x.com" in page.text


def test_signed_out_visitors_are_sent_to_sign_in(client):
    response = client.get("/team", headers={"accept": "text/html"},
                          follow_redirects=False)
    assert response.status_code == 303
    assert "/login" in response.headers["location"]


# -- adding people ------------------------------------------------------------
def test_adding_someone_shows_their_password_exactly_once(client, factory):
    sign_in_via_form(client, "boss@x.com", "boss-password")

    page = client.post("/team/add", data={
        "email": "New.Person@X.com", "display_name": "New Person", "role": "recruiter",
    })
    assert page.status_code == 200
    assert "new.person@x.com" in page.text

    # The generated password is on this response and nowhere else — revisiting
    # the page must not show it again.
    assert "Password" in page.text
    later = client.get("/team")
    assert "Give these details to" not in later.text


def test_the_generated_password_actually_works(client, people):
    sign_in_via_form(client, "boss@x.com", "boss-password")
    page = client.post("/team/add", data={"email": "sam@x.com", "role": "recruiter"})

    # Pull the password out of the page the way the operator would read it.
    import re
    match = re.search(r"<dt>Password</dt><dd>([^<]+)</dd>", page.text)
    assert match, "the page did not show a password"

    assert people.login("sam@x.com", match.group(1)) is not None


def test_a_duplicate_address_is_refused_in_plain_words(client):
    sign_in_via_form(client, "boss@x.com", "boss-password")
    page = client.post("/team/add", data={"email": "rec@x.com", "role": "recruiter"})

    assert page.status_code == 400
    assert "already exists" in page.text


# -- the lockout guard --------------------------------------------------------
def test_the_only_administrator_cannot_be_switched_off(people):
    """The failure this prevents cannot be undone from a browser.

    A hosted deployment has no shell. Removing the last administrator would mean
    nobody can ever add one back, and the only fix is redeploying and losing the
    data.
    """
    with pytest.raises(AuthError, match="only administrator"):
        people.deactivate("boss@x.com")


def test_the_only_administrator_cannot_be_demoted(people):
    with pytest.raises(AuthError, match="only administrator"):
        people.set_role("boss@x.com", "recruiter")


def test_the_guard_lifts_once_a_second_administrator_exists(people):
    people.create_user("second@x.com", "second-password",
                       display_name="Second", role="admin")

    people.set_role("boss@x.com", "recruiter")     # now allowed
    assert [a.role for a in people.accounts() if a.email == "boss@x.com"] == ["recruiter"]


def test_a_deactivated_administrator_does_not_count_as_cover(people):
    """Switched-off accounts cannot sign in, so they cannot manage anyone."""
    people.create_user("second@x.com", "second-password",
                       display_name="Second", role="admin")
    people.deactivate("second@x.com")

    with pytest.raises(AuthError, match="only administrator"):
        people.deactivate("boss@x.com")


def test_the_refusal_reaches_the_screen_rather_than_a_traceback(client):
    sign_in_via_form(client, "boss@x.com", "boss-password")
    page = client.post("/team/update",
                       data={"email": "boss@x.com", "action": "deactivate"})

    assert page.status_code == 400
    assert "only administrator" in page.text


# -- switching off and back on ------------------------------------------------
def test_switching_someone_off_signs_them_out_immediately(client, people, factory):
    """Not at the end of their session — immediately."""
    principal_token = people.login("rec@x.com", "rec-password")
    assert principal_token is not None
    _, token = principal_token
    assert people.principal_for_token(token) is not None

    sign_in_via_form(client, "boss@x.com", "boss-password")
    client.post("/team/update", data={"email": "rec@x.com", "action": "deactivate"})

    assert people.principal_for_token(token) is None


def test_switching_off_is_reversible(client, people):
    sign_in_via_form(client, "boss@x.com", "boss-password")
    client.post("/team/update", data={"email": "rec@x.com", "action": "deactivate"})
    assert [a.is_active for a in people.accounts() if a.email == "rec@x.com"] == [False]

    client.post("/team/update", data={"email": "rec@x.com", "action": "reactivate"})
    assert [a.is_active for a in people.accounts() if a.email == "rec@x.com"] == [True]


# -- the audit trail ----------------------------------------------------------
def test_every_account_change_is_recorded_against_the_person_who_made_it(client, factory):
    """Who was given access to candidate data, by whom, is an audit question.

    Before this, accounts were created on a terminal and left no trace at all.
    """
    sign_in_via_form(client, "boss@x.com", "boss-password")
    client.post("/team/add", data={"email": "sam@x.com", "role": "recruiter"})
    client.post("/team/update",
                data={"email": "sam@x.com", "action": "set_role", "role": "auditor"})
    client.post("/team/update", data={"email": "sam@x.com", "action": "deactivate"})
    client.post("/team/update", data={"email": "sam@x.com", "action": "reactivate"})
    client.post("/team/update", data={"email": "sam@x.com", "action": "reset_password"})

    with session_scope(factory) as session:
        rows = list(session.scalars(select_audit()))
    events = [r.event for r in rows]

    for expected in ("user.created", "user.role_changed", "user.deactivated",
                     "user.reactivated", "user.password_reset"):
        assert expected in events, f"{expected} was not recorded"

    for row in rows:
        if row.event.startswith("user."):
            assert row.actor == "boss@x.com"
            assert row.actor_role == "admin"


def test_the_account_the_change_was_about_is_recorded_in_full(client, factory):
    """BR-06 masks candidates, not operators.

    `append_audit` masks anything keyed `email`, which is right for a candidate
    — a reviewer needs to know a detail was present, not to have a second copy
    of it. Applied to account management it produced "Boss created an account
    for S***[14]", which answers none of the questions the row exists for. The
    key is `account` precisely so the exemption is visible in the code.
    """
    sign_in_via_form(client, "boss@x.com", "boss-password")
    client.post("/team/add", data={"email": "sam.lee@x.com", "role": "recruiter"})

    with session_scope(factory) as session:
        rows = [r for r in session.scalars(select_audit()) if r.event == "user.created"]
    assert [r.detail["account"] for r in rows] == ["sam.lee@x.com"]


def test_a_new_password_is_never_written_to_the_audit_log(client, factory):
    sign_in_via_form(client, "boss@x.com", "boss-password")
    page = client.post("/team/update",
                       data={"email": "rec@x.com", "action": "reset_password"})

    import re
    password = re.search(r"<dt>Password</dt><dd>([^<]+)</dd>", page.text).group(1)

    with session_scope(factory) as session:
        blob = " ".join(str(r.detail) for r in session.scalars(select_audit()))
    assert password not in blob


def test_account_changes_read_as_sentences_on_the_activity_log(client):
    sign_in_via_form(client, "boss@x.com", "boss-password")
    client.post("/team/add", data={"email": "sam.lee@x.com", "role": "recruiter"})

    page = client.get("/audit").text
    assert "Account created" in page
    assert "created an account for Sam Lee" in page
    # The raw constant belongs in the technical view, not the sentence.
    assert "user.created" in page          # still present for auditors
    assert "Boss created an account" in page


# -- single-user mode ---------------------------------------------------------
def test_single_user_mode_explains_itself_instead_of_showing_an_empty_table(factory):
    """An empty team page would read as "everyone has been deleted"."""
    from recruit.auth import Principal, SingleUserAuth

    solo = SingleUserAuth(email="solo@x.com", display_name="Solo", role="admin")
    app = create_app(session_factory=factory, auth_adapter=solo,
                     current_user=Principal(email="solo@x.com", display_name="Solo",
                                            role="admin", user_id=1))
    page = TestClient(app).get("/team")

    assert page.status_code == 200
    assert "single-person mode" in page.text
    assert "<table>" not in page.text


def test_the_user_table_is_untouched_by_all_of_this(factory, people):
    """A sanity check that the page edits accounts rather than replacing them."""
    with session_scope(factory) as session:
        from sqlalchemy import select
        assert session.scalar(select(User).where(User.email == "boss@x.com")) is not None
