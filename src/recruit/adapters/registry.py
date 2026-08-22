"""Build adapters from config. The only place that maps a provider name to a class."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .local import CSVAts, LocalStorage, NullAts, SingleUserAuth


@dataclass
class Adapters:
    storage: Any
    ats: Any
    auth: Any
    llm: Any = None          # built lazily; needs an API key


NOT_IMPLEMENTED = (
    "Adapter provider '{provider}' for {slot} is declared in config but not "
    "implemented yet. Available now: {available}. "
    "Cloud providers arrive in Phase 5."
)


def build_adapters(config) -> Adapters:
    """Instantiate every adapter named in config/organization.yaml."""

    storage_provider = config.get("adapters.storage.provider", "local")
    if storage_provider == "local":
        storage = LocalStorage(config.get("adapters.storage.local.root", "./data/artifacts"))
    else:
        raise NotImplementedError(
            NOT_IMPLEMENTED.format(provider=storage_provider, slot="storage", available="local")
        )

    ats_provider = config.get("adapters.ats.provider", "csv")
    if ats_provider == "csv":
        ats = CSVAts(config.get("adapters.ats.csv.export_dir", "./data/ats-export"))
    elif ats_provider == "none":
        ats = NullAts()
    else:
        raise NotImplementedError(
            NOT_IMPLEMENTED.format(provider=ats_provider, slot="ats", available="csv, none")
        )

    auth_provider = config.get("adapters.auth.provider", "single_user")
    if auth_provider == "single_user":
        auth = SingleUserAuth(
            email=config.get("adapters.auth.single_user.email", "operator@localhost"),
            display_name=config.get("adapters.auth.single_user.display_name", "Local Operator"),
            role=config.get("adapters.auth.single_user.role", "admin"),
        )
    else:
        raise NotImplementedError(
            NOT_IMPLEMENTED.format(provider=auth_provider, slot="auth", available="single_user")
        )

    return Adapters(storage=storage, ats=ats, auth=auth, llm=None)
