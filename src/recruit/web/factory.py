"""Module-level app instance, so uvicorn --reload has an import path to target."""

from __future__ import annotations

from .. import hosting
from .app import create_app

try:
    from ..config import OrganizationConfig
    _config = OrganizationConfig.load()
except Exception:      # noqa: BLE001 - the console runs without config too
    _config = None

# Before the app exists, not after. The check that matters here — "is this
# console about to serve candidate data on a public address with no sign-in
# screen?" — is only answerable on a real start, which is why it lives in the
# module uvicorn imports rather than in create_app, where every test would have
# to opt out of it.
hosting.refuse_unsafe_public_start(_config)

app = create_app(config=_config)
