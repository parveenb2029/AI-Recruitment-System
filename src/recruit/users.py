"""Manage operator accounts.

    python -m recruit.users add alice@example.com --role admin
    python -m recruit.users list
    python -m recruit.users set-role bob@example.com recruiter
    python -m recruit.users deactivate bob@example.com

Passwords are prompted for, never passed as arguments — a password on the
command line lands in shell history and in the process table.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from .auth import ROLES, AuthError
from .db.auth_repository import LocalAuth
from .db.migrations import create_all
from .db.session import create_engine_from_config, make_session_factory

# Not a substitute for a real password policy — just the handful that turn up
# first in any wordlist. A length check alone lets "12345678" through.
OBVIOUS_PASSWORDS = {
    "12345678", "123456789", "1234567890", "password", "password1",
    "qwertyui", "abc12345", "11111111", "00000000", "iloveyou",
    "letmein1", "admin123", "welcome1", "passw0rd",
}


def _adapter(url: str | None):
    config = None
    try:
        from .config import OrganizationConfig
        config = OrganizationConfig.load()
    except Exception:  # noqa: BLE001
        pass
    engine = create_engine_from_config(config, url=url)
    create_all(engine)
    return LocalAuth(make_session_factory(engine))


def _prompt_password() -> str:
    """Prompt twice, hiding input.

    getpass shows nothing at all while you type — no dots, no asterisks. That
    surprises people, so say it once up front rather than leaving them staring
    at a cursor wondering whether the keyboard works.
    """
    print("  Type the password and press Enter. Nothing will appear on screen.")
    try:
        first = getpass.getpass("  Password (min 8 chars): ")
        second = getpass.getpass("  Confirm: ")
    except (KeyboardInterrupt, EOFError):
        raise AuthError("Cancelled. No account was created.") from None
    if first != second:
        raise AuthError("Passwords do not match. No account was created.")
    _warn_if_obvious(first)
    return first


def _warn_if_obvious(password: str) -> None:
    if password.lower() in OBVIOUS_PASSWORDS:
        raise AuthError(
            "That password is one of the most-guessed in existence.\n"
            "  Hashing cannot save a password a wordlist already contains.\n"
            "  Pick something else — a short phrase works well."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m recruit.users",
                                     description=__doc__)
    parser.add_argument("--url", help="Override DATABASE_URL.")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="Create an operator account.")
    add.add_argument("email")
    add.add_argument("--name", help="Display name. Defaults to the email local part.")
    add.add_argument("--role", choices=ROLES, default="recruiter")
    add.add_argument("--password", help="For scripted setup only. Prefer the prompt.")

    sub.add_parser("list", help="List accounts.")

    pwd = sub.add_parser("set-password",
                         help="Change a password and revoke live sessions.")
    pwd.add_argument("email")
    pwd.add_argument("--password", help="For scripted setup only. Prefer the prompt.")
    pwd.add_argument("--keep-sessions", action="store_true",
                     help="Do not revoke existing sessions.")

    role = sub.add_parser("set-role", help="Change an account's role.")
    role.add_argument("email")
    role.add_argument("role", choices=ROLES)

    off = sub.add_parser("deactivate", help="Disable an account and kill its sessions.")
    off.add_argument("email")

    sub.add_parser("purge-sessions", help="Delete expired sessions.")

    args = parser.parse_args(argv)
    auth = _adapter(args.url)

    try:
        if args.command == "add":
            password = args.password or _prompt_password()
            if args.password:
                _warn_if_obvious(args.password)
            name = args.name or args.email.split("@")[0].replace(".", " ").title()
            principal = auth.create_user(args.email, password,
                                         display_name=name, role=args.role)
            print(f"  created  {principal.email}  role={principal.role}")
            print(f"  can:     {', '.join(sorted(principal.permissions))}")

        elif args.command == "list":
            people = auth.list_users()
            if not people:
                print("  No accounts yet. Create one:")
                print("      python -m recruit.users add you@example.com --role admin")
                return 0
            print(f"  {'EMAIL':<34} {'ROLE':<16} NAME")
            for person in people:
                print(f"  {person.email:<34} {person.role:<16} {person.display_name}")

        elif args.command == "set-password":
            password = args.password or _prompt_password()
            if args.password:
                _warn_if_obvious(args.password)
            auth.set_password(args.email, password,
                              revoke_sessions=not args.keep_sessions)
            print(f"  password changed for {args.email}")
            if not args.keep_sessions:
                print("  live sessions revoked; sign in again")

        elif args.command == "set-role":
            auth.set_role(args.email, args.role)
            print(f"  {args.email} is now {args.role}")

        elif args.command == "deactivate":
            auth.deactivate(args.email)
            print(f"  {args.email} deactivated; live sessions revoked")

        elif args.command == "purge-sessions":
            print(f"  removed {auth.purge_expired_sessions()} expired session(s)")

    except AuthError as error:
        print(f"  {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n  Cancelled.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
