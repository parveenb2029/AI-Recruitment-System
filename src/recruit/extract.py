"""WF-03 resume extraction — ingest, call the model, build the envelope.

    python -m recruit.extract samples/Rahul_Sharma_Resume.pdf --fake
    python -m recruit.extract samples/Rahul_Sharma_Resume.pdf

`--fake` runs the whole pipeline against a canned payload: no API key, no cost,
and every downstream step (schema validation, envelope assembly, confidence
gating) genuinely exercised.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import ingest
from .adapters.llm import FakeLLM, build_llm
from .errors import RecruitError
from .prompts import WorkflowPrompt, load_results_schema
from .validate import validate as run_validation

WORKFLOW_ID = "WF-03"
ROOT = Path(__file__).resolve().parent.parent.parent


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _run_id(content_sha256: str) -> str:
    """Deterministic from the content hash, so a re-run of the same document
    lands on the same id (Execution_Flow.md §8)."""
    return "RUN-" + hashlib.sha256(content_sha256.encode()).hexdigest()[:12]


def _aggregate_confidence(field_confidence: dict[str, float]) -> float:
    """Lowest field confidence, not the mean.

    A profile is only as trustworthy as its weakest extracted field. Averaging
    lets nine confident fields hide one fabricated employer, which is precisely
    the failure the review gate exists to catch.

    NOTE: still built on model self-reported numbers. Uncalibrated until
    Phase 4.3. See `confidence.calibrated` in organization config.
    """
    return round(min(field_confidence.values()), 4) if field_confidence else 0.0


def extract(
    path: str | Path,
    *,
    llm: Any,
    config: Any | None = None,
    requisition_id: str = "REQ-UNKNOWN",
    candidate_id: str = "CAN-UNKNOWN",
    root: Path | None = None,
) -> dict[str, Any]:
    """Run WF-03 over one document and return a full output envelope."""
    base = root or ROOT
    document = ingest.load(path)

    prompt = WorkflowPrompt.load(WORKFLOW_ID, base)
    schema = load_results_schema(WORKFLOW_ID, base / "schemas")
    run_id = _run_id(document.content_sha256)

    user = prompt.render_user(
        requisition_id=requisition_id,
        candidate_id=candidate_id,
        workflow_run_id=run_id,
        source_channel="cli",
        priority="standard",
        document_text_or_structured_input=document.text,
        schema_version="1.0.0",
        additional_context="(none)",
    )

    response = llm.complete_structured(system=prompt.system, user=user, schema=schema)
    results = response.content

    field_confidence = results.get("field_confidence") or {}
    aggregate = _aggregate_confidence(field_confidence)

    threshold = 0.85
    highlight_below = 0.60
    if config is not None:
        threshold = float(config.get("confidence.auto_publish_min", 0.85))
        highlight_below = float(config.get("confidence.field_highlight_below", 0.60))

    low = sorted(p for p, c in field_confidence.items() if c < highlight_below)
    results.setdefault("low_confidence_fields", low)

    # Carry ingest facts into the payload rather than letting the model assert them.
    metadata = results.setdefault("extraction_metadata", {})
    metadata["ocr_used"] = document.ocr_used
    metadata["pages_processed"] = document.pages
    metadata["source_char_count"] = document.char_count
    metadata["content_sha256"] = document.content_sha256

    review_reasons: list[str] = []
    if aggregate < threshold:
        review_reasons.append("LOW_CONFIDENCE_AGGREGATE")
    if low:
        review_reasons.append("LOW_CONFIDENCE_FIELDS")
    if results.get("conflicts"):
        review_reasons.append("SOURCE_CONFLICTS")
    if document.ocr_used:
        review_reasons.append("OCR_USED")

    status = "PARTIAL" if review_reasons else "SUCCESS"

    return {
        "status": status,
        "workflow_id": WORKFLOW_ID,
        "prompt_version": prompt.version,
        "model_id": response.model_id,
        "requisition_id": requisition_id,
        "candidate_id": candidate_id,
        "workflow_run_id": run_id,
        "processed_at": _now(),
        "confidence_aggregate": aggregate,
        "human_review_required": bool(review_reasons),
        "review_reasons": review_reasons,
        "flags": [],
        "evidence": results.pop("evidence", []) if isinstance(results, dict) else [],
        "results": results,
    }


# -- CLI ----------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m recruit.extract", description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--fake", action="store_true",
                        help="Use the canned payload. No API key, no cost.")
    parser.add_argument("--requisition-id", default="REQ-2026-0142")
    parser.add_argument("--candidate-id", default="CAN-88421")
    parser.add_argument("--out", type=Path, help="Write the envelope to this file.")
    parser.add_argument("--quiet", action="store_true", help="Suppress the summary.")
    parser.add_argument("--no-validate", action="store_true",
                        help="Skip validation. Rarely what you want.")
    args = parser.parse_args(argv)

    try:
        if args.fake:
            fixture = ROOT / "tests" / "fixtures" / "wf03_fake_results.json"
            if not fixture.is_file():
                print(f"Missing fixture: {fixture}", file=sys.stderr)
                return 2
            llm = FakeLLM(fixture)
            config = None
        else:
            from .config import OrganizationConfig
            config = OrganizationConfig.load()
            llm = build_llm(config)

        envelope = extract(
            args.file,
            llm=llm,
            config=config,
            requisition_id=args.requisition_id,
            candidate_id=args.candidate_id,
        )
    except RecruitError as error:
        print(str(error), file=sys.stderr)
        print(f"  recovery: {error.recovery}", file=sys.stderr)
        return 1
    except Exception as error:  # noqa: BLE001
        print(f"Unexpected failure: {error}", file=sys.stderr)
        return 1

    report = None
    if not args.no_validate:
        source_text = ingest.load(args.file).text
        report = run_validation(envelope, source_text=source_text, config=config)
        if not report.is_valid:
            envelope["human_review_required"] = True
            envelope["status"] = "PARTIAL"
            for finding in report.blocking:
                reason = f"VALIDATION_{finding.rule.replace('-', '_')}"
                if reason not in envelope["review_reasons"]:
                    envelope["review_reasons"].append(reason)
        envelope["flags"] = sorted(set(envelope.get("flags", []) + report.flags))
        envelope["validation"] = report.summary()

    text = json.dumps(envelope, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")

    if not args.quiet:
        profile = envelope["results"].get("profile", {})
        personal = profile.get("personal_info", {})
        print(f"  status        {envelope['status']}")
        print(f"  model         {envelope['model_id']}")
        print(f"  prompt        v{envelope['prompt_version']}")
        print(f"  run id        {envelope['workflow_run_id']}")
        print(f"  confidence    {envelope['confidence_aggregate']}  (lowest field)")
        print(f"  review needed {envelope['human_review_required']}"
              f"  {envelope['review_reasons'] or ''}")
        print(f"\n  name          {personal.get('full_name', '-')}")
        print(f"  email         {personal.get('email', '-')}")
        print(f"  roles         {len(profile.get('experience', []))}")
        print(f"  skills        {len(profile.get('skills', []))}")
        print(f"  evidence      {len(envelope['evidence'])} citation(s)")
        low = envelope["results"].get("low_confidence_fields") or []
        if low:
            print(f"  flagged       {', '.join(low)}")
        if report is not None:
            print(f"\n  validation    {'PASS' if report.is_valid else 'FAIL'}"
                  f"   {len(report.findings)} finding(s)")
            if "POTENTIAL_HALLUCINATION" in report.flags:
                print("  ** POTENTIAL_HALLUCINATION — evidence not found in source **")
            for finding in report.sorted_findings()[:6]:
                print(f"    {finding}")
        if args.out:
            print(f"\n  written to    {args.out}")
    elif not args.out:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
