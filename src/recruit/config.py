"""Load and validate config/organization.yaml.

Validation happens at import time rather than at runtime, so a misconfigured
rubric fails on startup instead of silently mis-scoring a candidate.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLE_PATH = ROOT / "config" / "organization.example.yaml"


def _default_config_path() -> Path:
    """Where to look for the organization config.

    `RECRUIT_CONFIG` wins, so a container can point at a mounted file without
    editing anything inside the image. Resolved per call rather than at import,
    because tests and the Docker entrypoint set it after this module loads.
    """
    override = os.environ.get("RECRUIT_CONFIG")
    if override:
        return Path(override)
    return ROOT / "config" / "organization.yaml"


CONFIG_PATH = ROOT / "config" / "organization.yaml"

WEIGHT_TOLERANCE = 0.001


class ConfigError(RuntimeError):
    """Raised when the organization config is missing or invalid."""


class OrganizationConfig:
    """Typed-ish accessor over the organization config."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data
        self._validate()

    # -- loading ----------------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> OrganizationConfig:
        target = path or _default_config_path()
        if not target.is_file():
            if EXAMPLE_PATH.is_file():
                raise ConfigError(
                    f"No organization config at {target}.\n"
                    "Create one with:\n"
                    "    cp config/organization.example.yaml config/organization.yaml"
                )
            raise ConfigError(f"No organization config at {target}")
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        return cls(data)

    # -- validation -------------------------------------------------------
    def _validate(self) -> None:
        errors: list[str] = []

        if not self.get("organization.legal_name"):
            errors.append("organization.legal_name is required")

        # BV-04: every rubric's weights must sum to 1.0.
        schemes = self.get("matching.schemes", {}) or {}
        if not schemes:
            errors.append("matching.schemes must define at least one scheme")
        for name, scheme in schemes.items():
            weights = (scheme or {}).get("weights", {}) or {}
            if not weights:
                errors.append(f"matching.schemes.{name}.weights is empty")
                continue
            total = sum(float(v) for v in weights.values())
            if abs(total - 1.0) > WEIGHT_TOLERANCE:
                errors.append(
                    f"matching.schemes.{name}.weights sum to {total:.4f}, "
                    f"must sum to 1.0 (business rule BV-04)"
                )

        default_scheme = self.get("matching.default_scheme")
        if default_scheme and default_scheme not in schemes:
            errors.append(
                f"matching.default_scheme '{default_scheme}' is not defined in "
                f"matching.schemes"
            )

        # Confidence thresholds must descend.
        gates = [
            ("confidence.auto_publish_min", self.get("confidence.auto_publish_min")),
            ("confidence.mandatory_review_min", self.get("confidence.mandatory_review_min")),
            ("confidence.spot_check_min", self.get("confidence.spot_check_min")),
        ]
        values = [v for _, v in gates if v is not None]
        if values != sorted(values, reverse=True):
            errors.append(
                "confidence thresholds must descend: "
                "auto_publish_min > mandatory_review_min > spot_check_min"
            )

        # Every jurisdiction needs retention rules; default must exist.
        codes = {j.get("code") for j in self.get("jurisdictions", []) or []}
        default_jurisdiction = self.get("default_jurisdiction")
        if default_jurisdiction and default_jurisdiction not in codes:
            errors.append(
                f"default_jurisdiction '{default_jurisdiction}' is not in jurisdictions"
            )

        if errors:
            raise ConfigError(
                "Invalid organization config:\n  - " + "\n  - ".join(errors)
            )

    # -- access -----------------------------------------------------------
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def weights(self, scheme: str | None = None) -> dict[str, float]:
        name = scheme or self.get("matching.default_scheme", "default")
        weights = self.get(f"matching.schemes.{name}.weights")
        if weights is None:
            raise ConfigError(f"Unknown matching scheme: {name}")
        return {k: float(v) for k, v in weights.items()}

    def retention_days(self, jurisdiction: str, outcome: str) -> int:
        """Retention for an outcome in a jurisdiction.

        outcome: unsuccessful_candidate | unsuccessful_with_consent |
                 hired_employee | audit_log
        """
        for entry in self.get("jurisdictions", []) or []:
            if entry.get("code") == jurisdiction:
                days = (entry.get("retention") or {}).get(f"{outcome}_days")
                if days is None:
                    break
                return int(days)
        fallback = self.get("default_jurisdiction")
        if jurisdiction != fallback and fallback:
            return self.retention_days(fallback, outcome)
        raise ConfigError(
            f"No retention rule for outcome '{outcome}' in jurisdiction '{jurisdiction}'"
        )

    def secret(self, env_var: str) -> str:
        value = os.environ.get(env_var)
        if not value:
            raise ConfigError(
                f"Environment variable {env_var} is not set. See .env.example."
            )
        return value

    @property
    def confidence_is_calibrated(self) -> bool:
        return bool(self.get("confidence.calibrated", False))
