"""Who is allowed to create the very first account, and from where.

Until now the answer was "whoever can read the server log". `bootstrap` generates
a password on first start and prints it once, which is correct on a hosting
dashboard and useless everywhere else: a person who has just double-clicked an
installer has no log, no terminal and no idea one exists. That single step is
the wall between a working product and a non-technical visitor.

So the first account can be created in the browser. That opens a real hole, and
this module is the door it gets closed with.

**The hole.** A console with no accounts is a console anyone can claim. Between
the moment an instance starts and the moment its owner first visits it, whoever
reaches `/setup` first becomes the administrator of it — and on a public URL
that is everyone. This is not theoretical; it is how self-hosted software gets
taken over.

**The rule, and why it is split by where the thing is running.**

- *On a machine somebody is sitting at*, setup is open. Whoever can reach
  localhost is already the person at the keyboard, holding a computer they
  own. A token there protects nothing and costs the whole benefit.
- *On a public deployment*, setup requires a token supplied out of band. The
  operator has a dashboard — that is the one channel a stranger with the URL
  does not have — so the secret travels through it. `render.yaml` asks the
  platform to generate the value, so nothing secret is written into a public
  repository and nobody has to invent one.

`hosting.is_public()` already knows the difference and is reused rather than
re-derived, so there is one definition of "public" in the codebase.

**Fail closed.** A public deployment with no token configured does not get an
open setup screen — it gets no setup screen at all, and falls back to the
`bootstrap` path that has always worked. An unset variable is somebody who has
not made a decision, and guessing "open" on their behalf is how the hole gets
left open by accident rather than on purpose.

**Setup disappears the moment it succeeds.** Once any account exists the route
is gone for good, and it answers 404 rather than 403: a 403 confirms there is a
configured instance here, which is a true thing about somebody else's system
that a stranger has no business learning.
"""

from __future__ import annotations

import hmac
import os

from . import hosting

__all__ = [
    "SETUP_TOKEN_ENV",
    "needs_setup",
    "setup_is_available",
    "token_is_required",
    "token_matches",
    "why_unavailable",
]

SETUP_TOKEN_ENV = "RECRUIT_SETUP_TOKEN"


def needs_setup(auth) -> bool:
    """True when no account exists yet and accounts are a thing here.

    An adapter with no notion of users — `single_user` on a laptop — has
    nothing to set up, and offering a setup screen for it would invite somebody
    to create an account that nothing would ever read.
    """
    lister = getattr(auth, "list_users", None)
    if not callable(lister):
        return False
    try:
        return not lister()
    except Exception:  # noqa: BLE001 - a database that is not ready is not "set up"
        return False


def token_is_required() -> bool:
    """A token is demanded exactly where the audience is the whole internet."""
    return hosting.is_public()


def _configured_token() -> str:
    return (os.environ.get(SETUP_TOKEN_ENV) or "").strip()


def setup_is_available(auth) -> bool:
    """Should `/setup` answer at all?

    Three things must hold: nothing is set up yet, this adapter has accounts,
    and — on a public deployment — somebody has deliberately configured a token.
    """
    if not needs_setup(auth):
        return False
    return not (token_is_required() and not _configured_token())


def token_matches(supplied: str | None) -> bool:
    """Compare in constant time, and never accept an unset token as a match.

    `hmac.compare_digest` rather than `==` because the comparison is against a
    secret and an early-exit comparison leaks its length and prefix. The empty
    case is checked first so that a missing variable can never be satisfied by
    a missing parameter.
    """
    if not token_is_required():
        return True
    expected = _configured_token()
    if not expected:
        return False
    return hmac.compare_digest(expected, (supplied or "").strip())


def why_unavailable(auth) -> str:
    """A sentence for the operator when setup is off. Never shown to a stranger.

    This exists so the log line and the CLI say the same thing, and so that
    "the setup page 404s" has a discoverable reason rather than looking like a
    broken deployment.
    """
    if not needs_setup(auth):
        return ("An account already exists, so first-run setup is closed. "
                "Sign in, or reset a password from the command line with "
                "`recruit-users set-password <email>`.")
    if token_is_required() and not _configured_token():
        return (
            "This looks like a public deployment, so browser setup needs a "
            f"one-time token and {SETUP_TOKEN_ENV} is not set. Set it in your "
            "hosting dashboard and open /setup?token=<value>, or create the "
            "first account with `python -m recruit.bootstrap` instead."
        )
    return "First-run setup is available at /setup."
