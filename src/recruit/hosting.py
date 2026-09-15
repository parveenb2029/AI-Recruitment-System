"""The difference between a laptop and a server other people can reach.

Everything in this file exists because of one gap. The shipped config sets
`adapters.auth.provider: single_user`, which is the right default for someone
trying the project on their own machine: no accounts, no password, straight to
the queue. The same setting on a public URL is a console full of candidate data
with **no login on it at all**, reachable by anyone who guesses the address.

Nothing in the codebase knew the difference, because until now there was no
supported way to deploy this anywhere. A one-click deploy makes that gap
reachable by accident, so the knowledge has to live somewhere — here.

Two rules:

1. **Hosting settings come from the environment, not the config file.**
   `config/organization.yaml` is gitignored and holds a company's details; on a
   hosted platform there is no file to edit and no shell to edit it with. The
   dashboard has environment variables, so the handful of settings that differ
   between a laptop and a server are read from there.
2. **A public deployment with no login refuses to start.** Fail closed. A
   console that will not boot is an afternoon; a console that boots open is a
   disclosure of everyone who applied.
"""

from __future__ import annotations

import os

__all__ = [
    "OPEN_CONSOLE_ESCAPE",
    "auth_provider",
    "is_from_this_machine",
    "is_public",
    "problems",
    "refuse_unsafe_public_start",
    "secure_cookie",
]

LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})


def is_from_this_machine(client_host: str | None) -> bool:
    """Did this request come from the computer the app is running on?

    A narrower question than `is_public()`, and the two are not
    interchangeable. `is_public()` asks what kind of deployment this is;
    this asks who is knocking.

    It matters for anything where "you are physically at the machine" is the
    authorisation. Somebody at the keyboard can already read the database file
    and run the command-line tools, so offering them the same power through the
    browser grants nothing new. Somebody on the same office network cannot, and
    `is_public()` would happily call that deployment private — a console
    started with `--host 0.0.0.0` on a laptop is not public by any
    environment marker, and is reachable by every machine on the LAN.
    """
    return (client_host or "") in LOOPBACK

# Platforms set one of these for every service they run. They are read as a
# fallback so that someone who deploys by hand — or copies the blueprint and
# drops a variable — is still protected. `RECRUIT_PUBLIC` always wins, because
# a platform this list has never heard of is exactly the case that needs a way
# in, and a platform that starts setting one of these tomorrow needs a way out.
PLATFORM_ENV_VARS = (
    "RENDER",              # Render
    "FLY_APP_NAME",        # Fly.io
    "RAILWAY_ENVIRONMENT",  # Railway
    "DYNO",                # Heroku
    "K_SERVICE",           # Google Cloud Run
    "WEBSITE_SITE_NAME",   # Azure App Service
)

OPEN_CONSOLE_ESCAPE = "RECRUIT_ALLOW_OPEN_CONSOLE"

_TRUE = {"1", "true", "yes", "on"}


def _flag(name: str) -> bool | None:
    """A tri-state env var: set-and-true, set-and-false, or absent.

    `bool(os.environ.get(...))` cannot express the third, and "unset" is a
    different instruction from "off" for every setting in this file.
    """
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return None
    return raw.strip().lower() in _TRUE


def is_public() -> bool:
    """Is this copy reachable by people who were not handed the machine?"""
    explicit = _flag("RECRUIT_PUBLIC")
    if explicit is not None:
        return explicit
    return any(os.environ.get(var) for var in PLATFORM_ENV_VARS)


def auth_provider(config) -> str:
    """Which auth adapter to build.

    `RECRUIT_AUTH_PROVIDER` overrides the config file so a hosted operator can
    turn on real accounts from a dashboard rather than by editing a file they
    cannot reach.
    """
    override = os.environ.get("RECRUIT_AUTH_PROVIDER")
    if override and override.strip():
        return override.strip().lower()
    if config is None:
        return "local" if is_public() else "single_user"
    return config.get("adapters.auth.provider", "single_user")


def secure_cookie(config) -> bool:
    """Should the session cookie be marked `Secure`?

    Defaults to on for a public deployment regardless of what the config file
    says, because the shipped example says `false` and was written for someone
    serving plain HTTP on their own machine. The failure mode if this is wrong
    is that nobody can sign in over plain HTTP — visible, immediate, and fixed
    by one variable. The failure mode the other way is a session cookie
    travelling in clear text.
    """
    override = _flag("RECRUIT_SECURE_COOKIE")
    if override is not None:
        return override
    if is_public():
        return True
    return bool(config.get("adapters.auth.local.secure_cookie", False)) if config else False


def problems(config) -> list[str]:
    """Misconfigurations that must stop a public deployment from starting.

    Returns sentences an operator can act on, not codes. Empty on a private
    machine: none of this applies to someone running it on their laptop, and a
    warning that fires when it does not apply is a warning people learn to skip.
    """
    if not is_public():
        return []

    found: list[str] = []
    if auth_provider(config) == "single_user":
        found.append(
            "This copy is deployed where other people can reach it, but "
            "authentication is set to 'single_user' — which means the console "
            "has no sign-in screen and anyone with the address can read every "
            "candidate in it.\n"
            "  Fix it by setting the environment variable "
            "RECRUIT_AUTH_PROVIDER=local in your hosting dashboard, then "
            "restarting. The first administrator account and its password are "
            "created on start and printed to the log, once.\n"
            f"  If the console genuinely holds nothing private and you want it "
            f"open on purpose, set {OPEN_CONSOLE_ESCAPE}=1."
        )
    return found


def refuse_unsafe_public_start(config) -> None:
    """Raise rather than serve an open console on a public address.

    Called from the module uvicorn imports, so it runs on a real start and not
    in the tests that build an app directly with an adapter already chosen.
    """
    if _flag(OPEN_CONSOLE_ESCAPE):
        return
    found = problems(config)
    if found:
        raise RuntimeError(
            "Refusing to start.\n\n" + "\n\n".join(found) + "\n"
        )
