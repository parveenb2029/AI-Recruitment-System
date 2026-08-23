#!/usr/bin/env bash
#
# Container entrypoint. Gets the stack from "image just started" to "a person
# can sign in and see work", then hands over to the console.
#
#     entrypoint.sh console     start the review console (default)
#     entrypoint.sh shell       a shell, with everything installed
#     entrypoint.sh <anything>  run it as a command
#
# Every step is idempotent: this runs on every start, including restarts, and
# must not duplicate an account, re-charge for an extraction, or wipe a queue.

set -euo pipefail

APP_HOST="${RECRUIT_HOST:-0.0.0.0}"
APP_PORT="${RECRUIT_PORT:-8000}"
CONFIG_DIR="/app/config"
CONFIG_FILE="${CONFIG_DIR}/organization.yaml"
EXAMPLE_FILE="${CONFIG_DIR}/organization.example.yaml"

log() { printf '  %s\n' "$*"; }

# -- 1. config ----------------------------------------------------------------
# A first-time user has no organization.yaml, because it is gitignored — it
# holds their company's details. Start them on the example so the stack comes
# up, and say clearly that the values are placeholders.
if [ ! -f "${CONFIG_FILE}" ]; then
    if cp "${EXAMPLE_FILE}" "${CONFIG_FILE}" 2>/dev/null; then
        log "config   created config/organization.yaml from the example."
        log "         It carries PLACEHOLDER company details. Edit it before"
        log "         anything you do here counts as a real hiring decision."
    else
        # The mount is read-only, or owned by another uid. Fall back to reading
        # the example in place rather than refusing to start.
        export RECRUIT_CONFIG="${EXAMPLE_FILE}"
        log "config   config/ is not writable — using the example config as-is."
        log "         Settings changes will not persist. Mount config/ read-write"
        log "         to fix that."
    fi
fi

# -- 2. database --------------------------------------------------------------
# depends_on: service_healthy already orders this, but the image is also run
# standalone, and "connection refused" three seconds after boot is a support
# ticket rather than a fact about the system.
case "${DATABASE_URL:-}" in
    # A file-backed database is either there or it is not; waiting for SQLite to
    # "start" would burn a minute and then blame Postgres for a permissions error.
    ""|sqlite*) NEEDS_WAIT=0 ;;
    *)          NEEDS_WAIT=1 ;;
esac

if [ "${NEEDS_WAIT}" = "1" ]; then
    log "wait     for the database..."
    for attempt in $(seq 1 30); do
        if python -c "
import os, sys
from sqlalchemy import create_engine, text
try:
    create_engine(os.environ['DATABASE_URL']).connect().execute(text('SELECT 1'))
except Exception:
    sys.exit(1)
" 2>/dev/null; then
            log "wait     database is accepting connections."
            break
        fi
        if [ "${attempt}" -eq 30 ]; then
            echo "  FAILED   database never became reachable at DATABASE_URL." >&2
            echo "           Is the postgres service running? docker compose ps" >&2
            exit 1
        fi
        sleep 2
    done
fi

# -- 3. schema + first account ------------------------------------------------
python -m recruit.bootstrap

# -- 4. sample queue ----------------------------------------------------------
# An empty first screen is indistinguishable from a broken one. Seeding runs the
# real pipeline against the sample resumes with the fake model, so it costs
# nothing and needs no API key. Off by default for anything but a demo: set
# RECRUIT_SEED=0 once real candidates are in the database.
if [ "${RECRUIT_SEED:-1}" = "1" ]; then
    python -m recruit.seed || log "seed     skipped (see the message above)."
fi

# -- 5. hand over -------------------------------------------------------------
case "${1:-console}" in
    console)
        log "console  http://localhost:${APP_PORT}"
        exec python -m recruit.web --host "${APP_HOST}" --port "${APP_PORT}"
        ;;
    shell)
        exec /bin/bash
        ;;
    *)
        exec "$@"
        ;;
esac
