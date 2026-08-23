"""First-run bootstrap and the packaging around it.

Two things are being defended here.

The first is that `bootstrap` runs on every container start, so it must be
idempotent — a second start must not create a second administrator, and must
not rotate the password of the first.

The second is the quickstart itself. The README makes a promise about what a
stranger sees in ten minutes; the Dockerfile, compose file and entrypoint are
the implementation of that promise, and they are the kind of file that rots
silently because nothing imports them.
"""

from __future__ import annotations

import importlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from recruit import bootstrap
from recruit.db.auth_repository import LocalAuth
from recruit.db.session import create_engine_from_config, make_session_factory

ROOT = Path(__file__).resolve().parent.parent


class FakeConfig:
    """Just enough config to choose an auth provider."""

    def __init__(self, provider: str) -> None:
        self._provider = provider

    def get(self, dotted: str, default=None):
        if dotted == "adapters.auth.provider":
            return self._provider
        return default


@pytest.fixture
def db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'bootstrap.db'}"


@pytest.fixture
def local_auth(monkeypatch):
    monkeypatch.setattr(bootstrap, "_load_config", lambda: FakeConfig("local"))


# -- idempotency --------------------------------------------------------------
def test_creates_an_admin_when_the_database_is_empty(db_url, local_auth, capsys):
    assert bootstrap.main(["--url", db_url, "--email", "boss@example.com"]) == 0

    users = LocalAuth(make_session_factory(create_engine_from_config(url=db_url))).list_users()
    assert [(u.email, u.role) for u in users] == [("boss@example.com", "admin")]
    assert "FIRST-RUN PASSWORD" in capsys.readouterr().out


def test_second_run_changes_nothing(db_url, local_auth, capsys):
    bootstrap.main(["--url", db_url, "--email", "boss@example.com"])
    first = capsys.readouterr().out
    original_password = re.search(r"password\s+(\S+)", first).group(1)

    assert bootstrap.main(["--url", db_url, "--email", "boss@example.com"]) == 0
    second = capsys.readouterr().out

    assert "already exist" in second
    assert "FIRST-RUN PASSWORD" not in second

    # The first password must still work. A restart that silently rotated the
    # credential would lock out the only administrator.
    auth = LocalAuth(make_session_factory(create_engine_from_config(url=db_url)))
    assert auth.login("boss@example.com", original_password) is not None
    assert len(auth.list_users()) == 1


def test_generated_password_is_not_guessable(db_url, local_auth, capsys):
    bootstrap.main(["--url", db_url, "--email", "boss@example.com"])
    password = re.search(r"password\s+(\S+)", capsys.readouterr().out).group(1)
    assert len(password) >= 16
    assert password.lower() not in {"admin", "password", "changeme", "recruit"}


def test_supplied_password_is_never_echoed(db_url, local_auth, monkeypatch, capsys):
    monkeypatch.setenv("RECRUIT_ADMIN_PASSWORD", "correct-horse-battery-staple")
    bootstrap.main(["--url", db_url, "--email", "boss@example.com"])
    out = capsys.readouterr().out

    assert "correct-horse-battery-staple" not in out
    auth = LocalAuth(make_session_factory(create_engine_from_config(url=db_url)))
    assert auth.login("boss@example.com", "correct-horse-battery-staple") is not None


def test_refuses_to_guess_an_administrator(db_url, local_auth, monkeypatch, capsys):
    monkeypatch.delenv("RECRUIT_ADMIN_EMAIL", raising=False)
    assert bootstrap.main(["--url", db_url]) == 1
    assert "RECRUIT_ADMIN_EMAIL" in capsys.readouterr().err


def test_single_user_mode_creates_no_account_and_warns(db_url, monkeypatch, capsys):
    monkeypatch.setattr(bootstrap, "_load_config", lambda: FakeConfig("single_user"))
    assert bootstrap.main(["--url", db_url, "--email", "boss@example.com"]) == 0

    out = capsys.readouterr().out
    assert "NO login" in out
    auth = LocalAuth(make_session_factory(create_engine_from_config(url=db_url)))
    assert auth.list_users() == []


def test_schema_only_stops_before_touching_accounts(db_url, local_auth):
    assert bootstrap.main(["--url", db_url, "--email", "boss@example.com",
                           "--schema-only"]) == 0
    auth = LocalAuth(make_session_factory(create_engine_from_config(url=db_url)))
    assert auth.list_users() == []


# -- RECRUIT_CONFIG -----------------------------------------------------------
def test_config_path_honours_the_environment(tmp_path, monkeypatch):
    """A container must be able to point at a mounted config without an edit."""
    from recruit.config import OrganizationConfig, _default_config_path

    source = yaml.safe_load(
        (ROOT / "config" / "organization.example.yaml").read_text(encoding="utf-8")
    )
    elsewhere = tmp_path / "somewhere-else.yaml"
    elsewhere.write_text(yaml.safe_dump(source), encoding="utf-8")

    monkeypatch.setenv("RECRUIT_CONFIG", str(elsewhere))
    assert _default_config_path() == elsewhere
    assert OrganizationConfig.load().get("organization.legal_name")

    monkeypatch.delenv("RECRUIT_CONFIG")
    assert _default_config_path().name == "organization.yaml"


# -- the quickstart's own files ----------------------------------------------
@pytest.mark.skipif(shutil.which("bash") is None,
                    reason="no bash on this machine — Windows without Git Bash or WSL")
def test_entrypoint_is_valid_shell():
    script = ROOT / "docker" / "entrypoint.sh"
    assert script.is_file()
    # bash -n parses without executing. A typo here does not surface until a
    # container refuses to start, which is the worst place to find it.
    #
    # Skipped rather than failed where bash is absent: the entrypoint only ever
    # runs inside a Linux container, so a Windows machine having no shell to
    # check it with says nothing about whether the file is correct. CI runs on
    # Linux and does check it.
    assert subprocess.run(["bash", "-n", str(script)]).returncode == 0


def test_compose_binds_the_console_to_localhost_only():
    """The console shows candidate data and may have no login at all.

    Publishing it on 0.0.0.0 must be a decision someone makes, not a default
    they inherit.
    """
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    for name, service in compose["services"].items():
        for mapping in service.get("ports", []):
            assert str(mapping).startswith("127.0.0.1:"), (
                f"service '{name}' publishes {mapping} on all interfaces"
            )


def test_dockerignore_keeps_the_workflow_prompts():
    """`prompts.WorkflowPrompt.load` reads Prompt.md at run time.

    Excluding the numbered folders from the build context produces an image
    whose console works and whose extraction raises PromptError — a failure that
    appears only on the first real resume.
    """
    ignored = [
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert not any(re.match(r"0\d", pattern) for pattern in ignored)

    for folder in ("03_Extracted_Data", "04_Match_Results"):
        assert (ROOT / folder / "Prompt.md").is_file()


def test_every_console_script_imports():
    """A broken entry point fails at `recruit-x`, long after `pip install`."""
    import tomllib

    scripts = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["scripts"]

    for name, target in scripts.items():
        module_name, _, attribute = target.partition(":")
        module = importlib.import_module(module_name)
        entry = getattr(module, attribute, None)
        assert callable(entry), f"{name} -> {target} is not callable"
