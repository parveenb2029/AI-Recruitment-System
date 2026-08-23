"""Validation layer for WF-03 output.

Four layers, per `03_Extracted_Data/Validation.md` §3–5:

1. **Schema** — structure, via the JSON Schema contract.
2. **Data** — field-level format rules (email, phone, dates, placeholder names).
3. **Business** — rules from `config/organization.yaml`, never hardcoded.
4. **Evidence grounding (VR-03)** — every cited snippet must actually appear in
   the source document. This is the layer that catches fabrication, and it is the
   reason the whole evidence-citation design exists.

Returns a `ValidationReport` rather than a bool. "Invalid" is not useful to a
reviewer; "the employer on line 3 does not appear in the source document" is.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_DIR = ROOT / "schemas"

# VR-03 threshold. Below this similarity against the source, a snippet is
# treated as potentially fabricated.
EVIDENCE_MATCH_MIN = 0.8

# RFC 5322 in full is famously unusable; this is the pragmatic subset that
# matches what mail servers actually accept.
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
E164_RE = re.compile(r"^\+?[1-9]\d{1,14}$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

PLACEHOLDER_NAMES = {
    "test", "n/a", "na", "none", "unknown", "tbd", "xxx", "asdf",
    "first last", "john doe", "jane doe", "your name", "candidate name",
    "full name", "-", "--",
}

SEVERITY_ORDER = {"CRITICAL": 0, "ERROR": 1, "WARNING": 2, "INFO": 3}


@dataclass
class Finding:
    rule: str
    severity: str          # CRITICAL | ERROR | WARNING | INFO
    message: str
    pointer: str | None = None
    detail: str | None = None

    def __str__(self) -> str:
        where = f" at {self.pointer}" if self.pointer else ""
        return f"[{self.severity}] {self.rule}{where}: {self.message}"


@dataclass
class ValidationReport:
    findings: list[Finding] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity in ("CRITICAL", "ERROR")]

    @property
    def is_valid(self) -> bool:
        return not self.blocking

    @property
    def requires_review(self) -> bool:
        """Warnings do not block, but a human must look."""
        return bool(self.findings)

    def sorted_findings(self) -> list[Finding]:
        return sorted(self.findings, key=lambda f: SEVERITY_ORDER.get(f.severity, 9))

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.severity] = counts.get(finding.severity, 0) + 1
        return {
            "valid": self.is_valid,
            "requires_review": self.requires_review,
            "counts": counts,
            "flags": sorted(set(self.flags)),
            "findings": [
                {
                    "rule": f.rule, "severity": f.severity, "message": f.message,
                    "pointer": f.pointer, "detail": f.detail,
                }
                for f in self.sorted_findings()
            ],
        }


# -- layer 1: schema ----------------------------------------------------------
def validate_schema(envelope: dict[str, Any], report: ValidationReport,
                    schema_dir: Path | None = None) -> None:
    directory = schema_dir or SCHEMA_DIR
    workflow_id = envelope.get("workflow_id", "")
    path = directory / f"{workflow_id}_output.schema.json"
    if not path.is_file():
        report.add(Finding("VR-02", "ERROR", f"No output schema for {workflow_id!r}."))
        return

    try:
        from jsonschema import Draft202012Validator
        from referencing import Registry, Resource
        from referencing.jsonschema import DRAFT202012
    except ImportError:  # pragma: no cover
        report.add(Finding("VR-02", "ERROR", "jsonschema is not installed."))
        return

    registry = Registry()
    for schema_file in sorted(directory.glob("*.schema.json")):
        contents = json.loads(schema_file.read_text(encoding="utf-8"))
        resource = Resource.from_contents(contents, default_specification=DRAFT202012)
        registry = registry.with_resource(uri=schema_file.name, resource=resource)
        if "$id" in contents:
            registry = resource @ registry

    schema = json.loads(path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, registry=registry)
    for error in validator.iter_errors(envelope):
        pointer = "/" + "/".join(str(p) for p in error.absolute_path)
        report.add(Finding("VR-02", "ERROR", error.message, pointer=pointer))


# -- layer 2: data ------------------------------------------------------------
def _parse_iso(value: str) -> date | None:
    if not isinstance(value, str) or not ISO_DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def validate_data(envelope: dict[str, Any], report: ValidationReport) -> None:
    profile = (envelope.get("results") or {}).get("profile") or {}
    personal = profile.get("personal_info") or {}

    email = personal.get("email")
    if email and not EMAIL_RE.match(str(email)):
        report.add(Finding("DV-EMAIL", "ERROR", f"Malformed email: {email!r}",
                           pointer="/results/profile/personal_info/email"))

    phone = personal.get("phone")
    if phone:
        normalized = re.sub(r"[\s\-()./]", "", str(phone))
        if not E164_RE.match(normalized):
            report.add(Finding("DV-PHONE", "WARNING",
                               f"Phone is not E.164-normalizable: {phone!r}",
                               pointer="/results/profile/personal_info/phone"))

    name = str(personal.get("full_name", "")).strip()
    if not name:
        report.add(Finding("DV-NAME", "ERROR", "Candidate name is empty.",
                           pointer="/results/profile/personal_info/full_name"))
    elif name.lower() in PLACEHOLDER_NAMES:
        report.add(Finding("DV-NAME", "ERROR", f"Placeholder name: {name!r}",
                           pointer="/results/profile/personal_info/full_name"))

    today = date.today()
    for index, role in enumerate(profile.get("experience") or []):
        base = f"/results/profile/experience/{index}"
        start = _parse_iso(role.get("start_date", ""))
        end_raw = role.get("end_date")
        end = _parse_iso(end_raw) if end_raw else None

        if role.get("start_date") and start is None:
            report.add(Finding("VR-04", "ERROR",
                               f"start_date is not ISO 8601: {role.get('start_date')!r}",
                               pointer=f"{base}/start_date"))
        if end_raw and end is None:
            report.add(Finding("VR-04", "ERROR",
                               f"end_date is not ISO 8601: {end_raw!r}",
                               pointer=f"{base}/end_date"))
        if start and end and start > end:
            report.add(Finding("VR-04", "ERROR",
                               f"start_date {start} is after end_date {end}.",
                               pointer=f"{base}/start_date"))
        if start and start > today:
            report.add(Finding("VR-04", "WARNING",
                               f"start_date {start} is in the future.",
                               pointer=f"{base}/start_date"))
        if role.get("is_current") and end_raw:
            report.add(Finding("VR-04", "WARNING",
                               "Role marked current but has an end_date.",
                               pointer=f"{base}/end_date"))

    # Every confidence pointer must resolve to a real path in the profile.
    # A pointer to nothing means the review console cannot show the reviewer
    # what the score refers to.
    for pointer in (envelope.get("results") or {}).get("field_confidence", {}):
        if not _resolve_pointer(profile, pointer):
            report.add(Finding("DV-POINTER", "WARNING",
                               "field_confidence points at a path not in the "
                               f"profile: {pointer}",
                               pointer=pointer))


def _resolve_pointer(document: Any, pointer: str) -> bool:
    node = document
    for part in pointer.strip("/").split("/"):
        if isinstance(node, dict):
            if part not in node:
                return False
            node = node[part]
        elif isinstance(node, list):
            if not part.isdigit() or int(part) >= len(node):
                return False
            node = node[int(part)]
        else:
            return False
    return True


# -- layer 3: business rules --------------------------------------------------
def validate_business(envelope: dict[str, Any], report: ValidationReport,
                      config: Any | None = None) -> None:
    auto_publish = 0.85
    highlight_below = 0.60
    if config is not None:
        auto_publish = float(config.get("confidence.auto_publish_min", 0.85))
        highlight_below = float(config.get("confidence.field_highlight_below", 0.60))

    results = envelope.get("results") or {}
    aggregate = envelope.get("confidence_aggregate", 0.0)

    if aggregate < auto_publish and not envelope.get("human_review_required"):
        report.add(Finding(
            "VR-01", "CRITICAL",
            f"confidence_aggregate {aggregate} is below {auto_publish} but "
            f"human_review_required is false. This would auto-publish an "
            f"unreviewed low-confidence extraction.",
        ))

    field_confidence = results.get("field_confidence") or {}
    expected_low = {p for p, c in field_confidence.items() if c < highlight_below}
    declared_low = set(results.get("low_confidence_fields") or [])
    if expected_low - declared_low:
        report.add(Finding(
            "BV-LOWCONF", "ERROR",
            "Fields below the review threshold are missing from "
            "low_confidence_fields; the console would not flag them.",
            detail=", ".join(sorted(expected_low - declared_low)),
        ))

    if results.get("conflicts") and not envelope.get("human_review_required"):
        report.add(Finding("BV-CONFLICT", "ERROR",
                           "Source conflicts recorded but no human review required."))

    if envelope.get("status") == "SUCCESS" and envelope.get("review_reasons"):
        report.add(Finding("BV-STATUS", "WARNING",
                           "Status is SUCCESS but review reasons are present; "
                           "expected PARTIAL."))

    for required in ("prompt_version", "model_id"):
        if not envelope.get(required):
            report.add(Finding("BR-05", "CRITICAL",
                               f"{required} is missing — the artifact is not auditable.",
                               pointer=f"/{required}"))


# -- layer 4: evidence grounding (VR-03) --------------------------------------
def _normalize(text: str) -> str:
    """Collapse whitespace and case. PDF extraction inserts arbitrary line
    breaks, so a raw comparison would fail on text that is genuinely present."""
    return re.sub(r"\s+", " ", text).strip().lower()


def validate_evidence(
    envelope: dict[str, Any],
    source_text: str,
    report: ValidationReport,
    threshold: float = EVIDENCE_MATCH_MIN,
) -> None:
    """VR-03. Every cited snippet must appear in the source document.

    The model is asked to quote verbatim. If a quote cannot be found in the
    source, either the model paraphrased (sloppy) or invented it (dangerous).
    Both need a human. This is the single most important check in the system.
    """
    try:
        from rapidfuzz import fuzz
    except ImportError:  # pragma: no cover
        report.add(Finding("VR-03", "ERROR",
                           "rapidfuzz is not installed; evidence grounding was NOT checked.",
                           detail="pip install rapidfuzz"))
        return

    evidence = envelope.get("evidence") or []
    if not evidence:
        report.add(Finding("VR-03", "WARNING",
                           "No evidence citations. Nothing can be traced to source."))
        return

    haystack = _normalize(source_text)

    for index, item in enumerate(evidence):
        pointer = f"/evidence/{index}"
        snippet = str(item.get("snippet", "")).strip()

        if not snippet:
            report.add(Finding("VR-03", "ERROR", "Empty evidence snippet.", pointer=pointer))
            continue

        needle = _normalize(snippet)

        # Exact substring is the common case and is cheap. Otherwise
        # partial_ratio finds the best-matching window of the source, which is
        # what we want here: the snippet is short and the source is long.
        # Kept as if/else rather than a ternary so each branch stays explained.
        if needle in haystack:  # noqa: SIM108
            score = 1.0
        else:
            score = fuzz.partial_ratio(needle, haystack) / 100.0

        item["match_score"] = round(score, 4)

        if score < threshold:
            report.flags.append("POTENTIAL_HALLUCINATION")
            report.add(Finding(
                "VR-03", "CRITICAL",
                f"Evidence snippet does not appear in the source document "
                f"(similarity {score:.2f} < {threshold}).",
                pointer=pointer,
                detail=f"field={item.get('field')!r} snippet={snippet[:80]!r}",
            ))
        elif score < 0.95:
            report.add(Finding(
                "VR-03", "WARNING",
                f"Evidence snippet is a near-match, not verbatim (similarity {score:.2f}).",
                pointer=pointer,
                detail=f"field={item.get('field')!r}",
            ))


# -- orchestration ------------------------------------------------------------
def validate(
    envelope: dict[str, Any],
    *,
    source_text: str | None = None,
    config: Any | None = None,
    schema_dir: Path | None = None,
    evidence_threshold: float = EVIDENCE_MATCH_MIN,
) -> ValidationReport:
    """Run all four layers. Layers are independent — one failure does not
    short-circuit the rest, because a reviewer wants every problem at once."""
    report = ValidationReport()
    validate_schema(envelope, report, schema_dir)
    validate_data(envelope, report)
    validate_business(envelope, report, config)
    if source_text is not None:
        validate_evidence(envelope, source_text, report, evidence_threshold)
    else:
        report.add(Finding("VR-03", "WARNING",
                           "Source text not supplied; evidence grounding was skipped."))
    return report
