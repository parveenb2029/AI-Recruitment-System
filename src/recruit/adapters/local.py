"""Default adapter implementations. No cloud account required."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .base import User


class LocalStorage:
    """Filesystem-backed StorageAdapter.

    Keys may contain '/' and become nested directories. Keys are confined to
    the configured root, so a traversal key cannot escape it.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        if not candidate.is_relative_to(self.root):
            raise ValueError(f"Key escapes storage root: {key!r}")
        return candidate

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return self.uri(key)

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise KeyError(key)
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def uri(self, key: str) -> str:
        return self._path(key).as_uri()


class CSVAts:
    """ATSAdapter for teams without an ATS.

    Appends events to a CSV a recruiter can open in Excel. Not a system of
    record — Postgres is. This exists so the pipeline has somewhere to emit
    stage changes without requiring a vendor integration on day one.
    """

    FIELDS = ["timestamp", "candidate_id", "event", "detail"]

    def __init__(self, export_dir: str | Path) -> None:
        self.export_dir = Path(export_dir)
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.export_dir / "ats_events.csv"
        if not self.path.exists():
            with self.path.open("w", newline="", encoding="utf-8") as handle:
                csv.writer(handle).writerow(self.FIELDS)

    def _append(self, candidate_id: str, event: str, detail: str) -> None:
        row = [
            datetime.now(UTC).isoformat(timespec="seconds"),
            candidate_id,
            event,
            detail,
        ]
        with self.path.open("a", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerow(row)

    def update_stage(self, candidate_id: str, stage: str) -> None:
        self._append(candidate_id, "stage_change", stage)

    def attach_artifact(self, candidate_id: str, uri: str, label: str) -> None:
        self._append(candidate_id, "artifact", json.dumps({"label": label, "uri": uri}))

    def add_note(self, candidate_id: str, note: str) -> None:
        self._append(candidate_id, "note", note)


class NullAts:
    """ATSAdapter that discards everything. For evaluation runs."""

    def update_stage(self, candidate_id: str, stage: str) -> None:
        return None

    def attach_artifact(self, candidate_id: str, uri: str, label: str) -> None:
        return None

    def add_note(self, candidate_id: str, note: str) -> None:
        return None


class SingleUserAuth:
    """AuthAdapter with one hardcoded operator.

    For local development only. Phase 5.1 replaces this with real sessions and
    an OIDC option. Every audit-log entry still records this identity, so the
    log shape does not change when real auth arrives.
    """

    def __init__(self, email: str, display_name: str, role: str = "admin") -> None:
        self._user = User(email=email, display_name=display_name, role=role)

    def authenticate(self, credentials: dict[str, Any]) -> User | None:
        return self._user

    def current_user(self) -> User | None:
        return self._user
