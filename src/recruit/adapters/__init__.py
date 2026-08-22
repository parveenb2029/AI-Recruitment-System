"""Adapter interfaces and their default local implementations.

Every external dependency sits behind a Protocol here. The defaults need no
cloud account and no ATS, so the project runs on a laptop with one API key.

Swapping to managed infrastructure is a config change, not a code change.
"""

from .base import ATSAdapter, AuthAdapter, LLMAdapter, StorageAdapter, User
from .registry import build_adapters

__all__ = [
    "ATSAdapter",
    "AuthAdapter",
    "LLMAdapter",
    "StorageAdapter",
    "User",
    "build_adapters",
]
