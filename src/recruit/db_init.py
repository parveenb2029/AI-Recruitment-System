"""Create the database schema and install the append-only guarantee.

    python -m recruit.db_init
    python -m recruit.db_init --drop      # tests and local resets only

Reads DATABASE_URL, falling back to adapters.database.url in the organization
config. Safe to re-run: tables and triggers are created if absent.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import text

from .db.migrations import create_all, drop_all
from .db.session import create_engine_from_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m recruit.db_init", description=__doc__)
    parser.add_argument("--url", help="Override DATABASE_URL for this run.")
    parser.add_argument("--drop", action="store_true",
                        help="Drop everything first. Destroys all data.")
    parser.add_argument("--yes", action="store_true", help="Skip the --drop confirmation.")
    args = parser.parse_args(argv)

    config = None
    if not args.url:
        try:
            from .config import OrganizationConfig
            config = OrganizationConfig.load()
        except Exception:
            config = None      # DATABASE_URL or the built-in default will do

    try:
        engine = create_engine_from_config(config, url=args.url)
    except Exception as error:  # noqa: BLE001
        print(f"Could not build a database engine: {error}", file=sys.stderr)
        return 1

    print(f"  target   {engine.url.render_as_string(hide_password=True)}")

    if args.drop:
        if not args.yes:
            answer = input("  This DESTROYS ALL DATA. Type 'drop' to continue: ")
            if answer.strip().lower() != "drop":
                print("  aborted")
                return 1
        drop_all(engine)
        print("  dropped  all tables and triggers")

    try:
        create_all(engine)
    except Exception as error:  # noqa: BLE001
        print(f"  FAILED   {error}", file=sys.stderr)
        message = str(error).lower()
        if "could not connect" in message or "connection refused" in message:
            print("\n  Is Postgres running? Try:  docker compose up -d", file=sys.stderr)
        return 1

    with engine.connect() as connection:
        tables = sorted(
            row[0] for row in connection.execute(text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public'"
            )) if engine.dialect.name == "postgresql"
        ) if engine.dialect.name == "postgresql" else []

    print("  created  tables and the append-only audit trigger")
    if tables:
        print(f"  tables   {', '.join(tables)}")
    print("\n  The audit log now rejects UPDATE and DELETE at the database level.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
