"""Running this somewhere other people can reach.

The project was written for one operator on one machine, and its defaults say
so: `adapters.auth.provider: single_user` means the console has no sign-in
screen at all. That is the right default for someone trying it on a laptop and
the wrong one the moment the same image is behind a public URL, where it becomes
a list of everyone who applied, readable by anyone with the address.

Deploying used to be impossible, so the gap was unreachable. A one-click deploy
makes it reachable by accident, which is what these tests are about.
"""

from __future__ import annotations

import importlib
import sys

import pytest

from recruit import hosting
from recruit.db.session import normalise_url


class FakeConfig:
    """Just enough of OrganizationConfig to answer dotted lookups."""

    def __init__(self, **values):
        self._values = values

    def get(self, key, default=None):
        return self._values.get(key, default)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """No test may inherit another's idea of where it is deployed."""
    for var in ("RECRUIT_PUBLIC", "RECRUIT_AUTH_PROVIDER", "RECRUIT_SECURE_COOKIE",
                hosting.OPEN_CONSOLE_ESCAPE, *hosting.PLATFORM_ENV_VARS):
        monkeypatch.delenv(var, raising=False)


# -- knowing where it is ------------------------------------------------------
def test_a_laptop_is_not_a_public_deployment():
    assert hosting.is_public() is False


def test_a_platform_that_never_declared_itself_is_still_detected(monkeypatch):
    """Someone who deploys by hand sets no variable of ours.

    Every managed platform marks its own environment. Reading those means the
    protection does not depend on the operator having read the README.
    """
    monkeypatch.setenv("RENDER", "true")
    assert hosting.is_public() is True


def test_the_operator_can_say_it_is_private_even_on_a_platform(monkeypatch):
    """A platform we detect is not always a public address.

    An internal deployment behind a VPN is a real case, and a check that cannot
    be turned off is a check people work around by editing the source.
    """
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("RECRUIT_PUBLIC", "0")
    assert hosting.is_public() is False


# -- the setting that matters -------------------------------------------------
def test_the_environment_overrides_the_config_file():
    """A hosted operator has a dashboard, not a shell.

    `config/organization.yaml` is gitignored — it holds a company's details —
    so on a hosting platform there is no file to edit and no terminal to edit
    it with. The one setting that decides whether there is a login screen has
    to be reachable from where the operator actually is.
    """
    config = FakeConfig(**{"adapters.auth.provider": "single_user"})
    assert hosting.auth_provider(config) == "single_user"

    import os
    os.environ["RECRUIT_AUTH_PROVIDER"] = "local"
    try:
        assert hosting.auth_provider(config) == "local"
    finally:
        del os.environ["RECRUIT_AUTH_PROVIDER"]


def test_a_public_deployment_with_no_login_is_refused(monkeypatch):
    """Fail closed.

    A console that will not boot costs an afternoon. A console that boots with
    no login on it discloses every candidate in the database, and nothing tells
    the operator it happened.
    """
    monkeypatch.setenv("RECRUIT_PUBLIC", "1")
    config = FakeConfig(**{"adapters.auth.provider": "single_user"})

    with pytest.raises(RuntimeError) as raised:
        hosting.refuse_unsafe_public_start(config)

    message = str(raised.value)
    assert "no sign-in screen" in message
    # The refusal has to carry the fix, not just the diagnosis: the person
    # reading it is looking at a failed deploy, not at this file.
    assert "RECRUIT_AUTH_PROVIDER=local" in message


def test_the_same_configuration_is_fine_on_a_laptop():
    """This is the intended local experience, and must not become a warning."""
    config = FakeConfig(**{"adapters.auth.provider": "single_user"})
    assert hosting.problems(config) == []
    hosting.refuse_unsafe_public_start(config)


def test_a_public_deployment_with_accounts_starts_normally(monkeypatch):
    monkeypatch.setenv("RECRUIT_PUBLIC", "1")
    monkeypatch.setenv("RECRUIT_AUTH_PROVIDER", "local")
    hosting.refuse_unsafe_public_start(FakeConfig())


def test_an_open_console_can_be_chosen_deliberately(monkeypatch):
    """Refusing outright would be a rule with no exception for a real case.

    A public demo with nothing but synthetic candidates in it is legitimate.
    The point is that it must be a decision somebody made, not a default they
    inherited.
    """
    monkeypatch.setenv("RECRUIT_PUBLIC", "1")
    monkeypatch.setenv(hosting.OPEN_CONSOLE_ESCAPE, "1")
    hosting.refuse_unsafe_public_start(
        FakeConfig(**{"adapters.auth.provider": "single_user"})
    )


# -- the session cookie -------------------------------------------------------
def test_the_session_cookie_is_secure_on_a_public_deployment(monkeypatch):
    """The shipped config says `secure_cookie: false`, for plain-HTTP localhost.

    Inheriting that on a hosted deployment would send the session cookie in
    clear text. Being wrong in this direction means nobody can sign in over
    plain HTTP — loud, immediate, and one variable to undo.
    """
    config = FakeConfig(**{"adapters.auth.local.secure_cookie": False})
    assert hosting.secure_cookie(config) is False

    monkeypatch.setenv("RECRUIT_PUBLIC", "1")
    assert hosting.secure_cookie(config) is True

    monkeypatch.setenv("RECRUIT_SECURE_COOKIE", "0")
    assert hosting.secure_cookie(config) is False


# -- the database URL a platform hands out ------------------------------------
@pytest.mark.parametrize(("given", "expected"), [
    # Heroku's legacy spelling, still emitted by several platforms. SQLAlchemy
    # dropped it in 1.4 and errors out.
    ("postgres://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"),
    # Valid, but a bare scheme means psycopg2 — which this project does not
    # ship, because it needs a compiler (hard rule 9).
    ("postgresql://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"),
    # Already explicit. Left alone.
    ("postgresql+psycopg://u:p@h/d", "postgresql+psycopg://u:p@h/d"),
    # Someone who names a different driver meant it.
    ("postgresql+asyncpg://u:p@h/d", "postgresql+asyncpg://u:p@h/d"),
    ("sqlite:///./data/recruit.db", "sqlite:///./data/recruit.db"),
    ("nonsense", "nonsense"),
])
def test_a_managed_database_url_is_made_usable(given, expected):
    """Neither shape a hosting platform generates works here unchanged.

    The alternative is telling every operator to hand-edit a URL the platform
    wrote for them, and letting the ones who miss it hit
    `ModuleNotFoundError: psycopg2` with no idea what it means.
    """
    assert normalise_url(given) == expected


# -- the blueprint ------------------------------------------------------------
def test_the_render_blueprint_turns_authentication_on():
    """The blueprint is the deploy button. If it is wrong, everyone gets it wrong."""
    from pathlib import Path

    import yaml
    blueprint = yaml.safe_load(
        (Path(__file__).resolve().parent.parent / "render.yaml").read_text()
    )
    service = blueprint["services"][0]
    env = {entry["key"]: entry for entry in service["envVars"]}

    assert env["RECRUIT_AUTH_PROVIDER"]["value"] == "local"
    assert env["RECRUIT_SECURE_COOKIE"]["value"] == "1"
    assert service["healthCheckPath"] == "/health"

    # Secrets are prompted for, never written down. `sync: false` means Render
    # asks at creation; a `value:` here would put it in a public repository.
    assert env["ANTHROPIC_API_KEY"]["sync"] is False
    assert "value" not in env["ANTHROPIC_API_KEY"]
    assert env["RECRUIT_ADMIN_EMAIL"]["sync"] is False

    # No password, at all. The operator chooses it in the browser at /setup.
    assert "RECRUIT_ADMIN_PASSWORD" not in env

    # The setup token must be GENERATED by the platform, never written here.
    # It is the only thing standing between a freshly deployed console and the
    # first stranger who finds the URL, so a literal value in a public
    # repository would hand that window to everyone.
    token = env["RECRUIT_SETUP_TOKEN"]
    assert token.get("generateValue") is True
    assert "value" not in token

    # The database is ASKED FOR, not provisioned. Two reasons, both learned by
    # submitting this blueprint to Render and watching it fail:
    #
    #   1. Render's free Postgres deletes itself 30 days after creation, which
    #      for a demo linked from a CV is a failure with a timer on it.
    #   2. Render allows one free database per account, so a blueprint that
    #      creates one fails outright for anybody who already has one — and
    #      takes the web service down with it.
    #
    # A connection string also carries a password, and this repository is
    # public, so a literal value here would publish the credentials.
    assert "databases" not in blueprint, (
        "provisioning a database here reintroduces the 30-day timer and the "
        "one-free-database limit"
    )
    assert env["DATABASE_URL"]["sync"] is False
    assert "value" not in env["DATABASE_URL"]


def test_the_app_module_refuses_to_import_when_it_would_serve_openly(monkeypatch):
    """The guard has to be on the path uvicorn actually takes.

    Putting it in `create_app` would mean every test that builds an app with an
    adapter already chosen has to opt out of it, and a check everything opts out
    of stops being a check.
    """
    monkeypatch.setenv("RECRUIT_PUBLIC", "1")
    monkeypatch.setenv("RECRUIT_AUTH_PROVIDER", "single_user")

    # Dropped from the module cache first: a module already imported by an
    # earlier test would skip the check entirely, and the test would pass by
    # never running the code it is about.
    sys.modules.pop("recruit.web.factory", None)
    with pytest.raises(RuntimeError, match="Refusing to start"):
        importlib.import_module("recruit.web.factory")

    # Leave it importable for whatever runs next.
    monkeypatch.delenv("RECRUIT_PUBLIC")
    sys.modules.pop("recruit.web.factory", None)
    importlib.import_module("recruit.web.factory")
