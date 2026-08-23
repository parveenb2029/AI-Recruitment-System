"""Module-level app instance, so uvicorn --reload has an import path to target."""

from __future__ import annotations

from .app import create_app

try:
    from ..config import OrganizationConfig
    _config = OrganizationConfig.load()
except Exception:      # noqa: BLE001 - the console runs without config too
    _config = None

app = create_app(config=_config)
