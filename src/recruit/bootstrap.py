"""First-run setup: schema, and an administrator to sign in as.

    python -m recruit.bootstrap
    python -m recruit.bootstrap --email you@example.com --role admin

Idempotent by design. It is the container entrypoint's first call on every
start, so it must be safe to run against a database that is already set up: if
an account exists it changes nothing and says so.

Why this exists rather than a documented `recruit-users add` step: a stack that
comes up with no way to sign in looks broken, and the usual fix — shipping a
default password — is how products end up on the internet with `admin/admin`.
So the password is **generated**, printed once, and never stored anywhere but
the hash. Nobody can leak a credential they were never given.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys

from .db.auth_repository import LocalAuth
from .db.migrations import create_all
from .db.session import create_engine_from_config, make_session_factory

# Long enough that the printed password is not worth attacking, short enough to
# retype from a terminal if the operator does not copy-paste.
GENERATED_PASSWORD_BYTES = 12


def _load_config():
    try:
        from .config import OrganizationConfig

        return OrganizationConfig.load()
    except Exception:  # noqa: BLE001 - bootstrap must work before config exists
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m recruit.bootstrap",
                                     description=__doc__)
    parser.add_argument("--url", help="Override DATABASE_URL for this run.")
    parser.add_argument("--email", default=os.environ.get("RECRUIT_ADMIN_EMAIL"),
                        help="Administrator email. Or set RECRUIT_ADMIN_EMAIL.")
    parser.add_argument("--name", help="Display name. Defaults to the email local part.")
    parser.add_argument("--role", default="admin",
                        help="Role for the bootstrapped account. Default: admin.")
    parser.add_argument("--schema-only", action="store_true",
                        help="Create tables and the audit trigger, then stop.")
    args = parser.parse_args(argv)

    config = _load_config()

    try:
        engine = create_engine_from_config(config, url=args.url)
    except Exception as error:  # noqa: BLE001
        print(f"  FAILED   could not reach the database: {error}", file=sys.stderr)
        return 1

    try:
        create_all(engine)
    except Exception as error:  # noqa: BLE001
        print(f"  FAILED   {error}", file=sys.stderr)
        return 1
    print(f"  schema   ready at {engine.url.render_as_string(hide_password=True)}")

    if args.schema_only:
        return 0

    provider = config.get("adapters.auth.provider", "single_user") if config else "single_user"
    if provider != "local":
        # Not a failure. `single_user` is a legitimate choice for a laptop demo,
        # and creating accounts for an adapter that never reads them would be
        # theatre. Say what is actually true about who can reach the console.
        print(f"  auth     provider is '{provider}' — no account needed to sign in.")
        if provider == "single_user":
            print("           WARNING: the console has NO login in this mode. Do not "
                  "expose\n                    it beyond localhost. Set "
                  "adapters.auth.provider: local\n                    in "
                  "config/organization.yaml before anyone else can reach it.")
        return 0

    auth = LocalAuth(make_session_factory(engine))
    existing = auth.list_users()
    if existing:
        print(f"  auth     {len(existing)} account(s) already exist — unchanged.")
        return 0

    email = args.email
    if not email:
        print("  FAILED   no accounts exist and no administrator email was given.\n"
              "           Pass --email you@example.com, or set RECRUIT_ADMIN_EMAIL.",
              file=sys.stderr)
        return 1

    supplied = os.environ.get("RECRUIT_ADMIN_PASSWORD")
    password = supplied or secrets.token_urlsafe(GENERATED_PASSWORD_BYTES)

    auth.create_user(
        email,
        password,
        display_name=args.name or email.split("@")[0],
        role=args.role,
    )

    print(f"  auth     created {args.role} account {email.strip().lower()}")
    if supplied:
        # Do not echo an operator-supplied password: it is likely reused, and it
        # is already wherever they got it from.
        print("           password taken from RECRUIT_ADMIN_PASSWORD.")
    else:
        print()
        print("  " + "=" * 64)
        print("   FIRST-RUN PASSWORD — shown once, never stored in readable form")
        print()
        print(f"     email     {email.strip().lower()}")
        print(f"     password  {password}")
        print()
        print("   Change it after signing in:")
        print(f"     recruit-users set-password {email.strip().lower()}")
        print("  " + "=" * 64)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
