"""Adapter protocols.

Structural typing (typing.Protocol) rather than inheritance, so an
implementation only has to match the shape — no base class to import.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


# -- storage ------------------------------------------------------------------
@runtime_checkable
class StorageAdapter(Protocol):
    """Blob storage for source documents and published artifacts."""

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        """Store bytes under key. Returns a URI locating them."""
        ...

    def get(self, key: str) -> bytes:
        """Retrieve bytes. Raises KeyError when absent."""
        ...

    def exists(self, key: str) -> bool:
        ...

    def uri(self, key: str) -> str:
        ...


# -- LLM ----------------------------------------------------------------------
@dataclass
class LLMResponse:
    """One model call.

    `content` is already-parsed structured output. Providers are called in
    native structured-output mode, so there is no JSON string to parse and no
    repair-prompt loop.
    """

    content: dict[str, Any]
    model_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str | None = None


@runtime_checkable
class LLMAdapter(Protocol):
    def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Call the model, constraining output to `schema`.

        Implementations MUST use the provider's native structured-output or
        tool-calling mode. Asking for JSON in prose is a project-level rule
        violation (see CLAUDE.md, Hard rules).
        """
        ...

    @property
    def model_id(self) -> str:
        """Exact model identifier including snapshot, for the audit log."""
        ...


# -- ATS ----------------------------------------------------------------------
@runtime_checkable
class ATSAdapter(Protocol):
    """Applicant tracking system. 'csv' is a valid answer for teams with none."""

    def update_stage(self, candidate_id: str, stage: str) -> None:
        ...

    def attach_artifact(self, candidate_id: str, uri: str, label: str) -> None:
        ...

    def add_note(self, candidate_id: str, note: str) -> None:
        ...


# -- auth ---------------------------------------------------------------------
@dataclass
class User:
    email: str
    display_name: str
    role: str = "recruiter"       # admin | recruiter | hiring_manager
    attributes: dict[str, Any] = field(default_factory=dict)

    def can(self, action: str) -> bool:
        permissions = {
            "admin": {"review", "approve", "override", "configure"},
            "hiring_manager": {"review", "approve"},
            "recruiter": {"review"},
        }
        return action in permissions.get(self.role, set())


@runtime_checkable
class AuthAdapter(Protocol):
    def authenticate(self, credentials: dict[str, Any]) -> User | None:
        ...

    def current_user(self) -> User | None:
        ...
