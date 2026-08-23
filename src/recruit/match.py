"""WF-04 JD-candidate matching.

**The model never produces a fit score.** It judges each component on its own
merits and cites evidence; the arithmetic that combines those judgements into
`overall_score` happens here, in code, using weights from
`config/organization.yaml`.

That split is the whole design. It makes the result:

- **tunable** — change a weight in config and the outcome moves predictably;
- **auditable** — a recruiter can see which dimension drove the decision;
- **defensible** — "0.61 overall" is not an answer to a rejected candidate,
  whereas "Terraform not evidenced, worth 15% of the must-have component" is.

Enforcement is structural, not conventional: the schema handed to the model has
the computed fields stripped out, so it is not capable of returning them.

    python -m recruit.match samples/Rahul_Sharma.json samples/Software_Engineer.json --fake
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import RecruitError
from .prompts import WorkflowPrompt, load_results_schema

WORKFLOW_ID = "WF-04"
ROOT = Path(__file__).resolve().parent.parent.parent
TOLERANCE = 0.001

# Fields the APPLICATION computes. Removed from the model's tool schema so the
# model cannot return them even if a future prompt edit asked it to.
COMPUTED_FIELDS = ("overall_score", "recommendation", "auto_archive_eligible")
COMPUTED_COMPONENT_FIELDS = ("weight", "weighted_score")

DEFAULT_WEIGHTS = {
    "must_have_coverage": 0.5,
    "experience_band": 0.3,
    "domain_match": 0.2,
}
DEFAULT_BANDS = {
    "strong_match_min": 0.80,
    "match_min": 0.65,
    "partial_match_min": 0.45,
}


class MatchError(RecruitError):
    code = "ERR_MATCH_FAILED"
    recovery = "Check the job description and candidate profile are both valid."


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def model_facing_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Strip computed fields, so the model is structurally unable to score."""
    stripped = copy.deepcopy(schema)
    properties = stripped.get("properties", {})
    for field in COMPUTED_FIELDS:
        properties.pop(field, None)
    stripped["required"] = [
        name for name in stripped.get("required", []) if name not in COMPUTED_FIELDS
    ]

    component = properties.get("components", {}).get("items", {})
    for field in COMPUTED_COMPONENT_FIELDS:
        component.get("properties", {}).pop(field, None)
    component["required"] = [
        name for name in component.get("required", [])
        if name not in COMPUTED_COMPONENT_FIELDS
    ]
    # weighting provenance is stamped by the application too
    properties.pop("weighting", None)
    stripped["required"] = [n for n in stripped["required"] if n != "weighting"]
    return stripped


def band(score: float, bands: dict[str, float]) -> str:
    if score >= bands["strong_match_min"]:
        return "STRONG_MATCH"
    if score >= bands["match_min"]:
        return "MATCH"
    if score >= bands["partial_match_min"]:
        return "PARTIAL_MATCH"
    return "NO_MATCH"


def combine(
    components: list[dict[str, Any]],
    weights: dict[str, float],
    bands: dict[str, float],
    auto_archive_below: float,
) -> dict[str, Any]:
    """Apply the weights. This is the arithmetic the model is not trusted with.

    Raises rather than guessing when a component has no weight: silently scoring
    an unweighted dimension at zero would quietly change who gets rejected.
    """
    total_weight = sum(weights.values())
    if abs(total_weight - 1.0) > TOLERANCE:
        raise MatchError(
            f"Rubric weights sum to {total_weight:.4f}, must be 1.0 (BV-04).",
            detail=json.dumps(weights),
        )

    scored: list[dict[str, Any]] = []
    for component in components:
        key = component.get("component_id")
        if key not in weights:
            raise MatchError(
                f"Component {key!r} has no weight in the active rubric.",
                detail=f"Rubric defines: {', '.join(sorted(weights))}",
            )
        raw = float(component.get("raw_score", 0.0))
        if not 0.0 <= raw <= 1.0:
            raise MatchError(f"Component {key!r} returned raw_score {raw}, outside 0..1.")
        weight = float(weights[key])
        enriched = dict(component)
        enriched["weight"] = weight
        enriched["weighted_score"] = round(raw * weight, 6)
        scored.append(enriched)

    seen = [c["component_id"] for c in scored]
    missing = sorted(set(weights) - set(seen))
    if missing:
        raise MatchError(
            f"The rubric weights components the model did not score: {', '.join(missing)}.",
            detail="Scoring a missing dimension as zero would silently change outcomes.",
        )
    if len(seen) != len(set(seen)):
        raise MatchError(f"Duplicate components returned: {seen}")

    overall = round(sum(c["weighted_score"] for c in scored), 6)
    return {
        "components": scored,
        "overall_score": overall,
        "recommendation": band(overall, bands),
        "auto_archive_eligible": overall < auto_archive_below,
    }


def match(
    profile: dict[str, Any],
    job_description: dict[str, Any],
    *,
    llm: Any,
    config: Any | None = None,
    scheme: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    base = root or ROOT

    weights = dict(DEFAULT_WEIGHTS)
    bands = dict(DEFAULT_BANDS)
    auto_archive_below = 0.40
    scheme_name = scheme or "default"
    scheme_version = "1.0.0"

    if config is not None:
        scheme_name = scheme or config.get("matching.default_scheme", "default")
        weights = config.weights(scheme_name)
        scheme_version = config.get(f"matching.schemes.{scheme_name}.version", "1.0.0")
        auto_archive_below = float(config.get("matching.auto_archive_below", 0.40))
        for key in bands:
            value = config.get(f"matching.recommendation_bands.{key}")
            if value is not None:
                bands[key] = float(value)

    prompt = WorkflowPrompt.load(WORKFLOW_ID, base)
    full_schema = load_results_schema(WORKFLOW_ID, base / "schemas")
    schema = model_facing_schema(full_schema)

    requisition_id = job_description.get("requisition_id", "REQ-UNKNOWN")
    candidate_id = profile.get("candidate_id", "CAN-UNKNOWN")
    run_id = "RUN-" + hashlib.sha256(
        f"{WORKFLOW_ID}|{requisition_id}|{candidate_id}|{scheme_name}".encode()
    ).hexdigest()[:12]

    excluded = config.get("matching.excluded_signals", []) if config else [
        "name", "gender", "age", "nationality", "university_prestige", "address",
    ]

    payload = {
        "job_description": job_description,
        "candidate_profile": profile,
        "components_to_score": sorted(weights),
        "do_not_use_these_signals": excluded,
    }

    user = prompt.render_user(
        requisition_id=requisition_id,
        candidate_id=candidate_id,
        workflow_run_id=run_id,
        source_channel="cli",
        priority="standard",
        document_text_or_structured_input=json.dumps(payload, indent=2),
        schema_version="1.0.0",
        additional_context=(
            "Score each component in components_to_score independently, 0..1, with "
            "evidence quoted verbatim from the candidate profile. Do NOT produce an "
            "overall score — the application computes it from configured weights."
        ),
    )

    response = llm.complete_structured(system=prompt.system, user=user, schema=schema)
    results = dict(response.content)

    combined = combine(results.get("components") or [], weights, bands, auto_archive_below)
    results.update(combined)
    results["weighting"] = {
        "scheme_id": scheme_name,
        "scheme_version": scheme_version,
        "weights": weights,
    }
    results.setdefault("excluded_signals", list(excluded))

    confidences = [
        float(c["confidence"])
        for c in combined["components"]
        if c.get("confidence") is not None
    ]
    aggregate = round(min(confidences), 4) if confidences else 0.0

    threshold = float(config.get("confidence.auto_publish_min", 0.85)) if config else 0.85
    review_reasons: list[str] = []
    if aggregate < threshold:
        review_reasons.append("LOW_CONFIDENCE_AGGREGATE")
    if any(r.get("status") == "UNKNOWN" for r in results.get("must_have_requirements") or []):
        review_reasons.append("UNRESOLVED_REQUIREMENTS")
    if combined["auto_archive_eligible"]:
        # BR-04: eligibility is not permission. Archiving a candidate is a human
        # act, and an override needs a written justification in the audit log.
        review_reasons.append("BELOW_AUTO_ARCHIVE_THRESHOLD")

    return {
        "status": "PARTIAL" if review_reasons else "SUCCESS",
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
        "evidence": results.pop("evidence", []),
        "results": results,
    }


# -- CLI ----------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m recruit.match", description=__doc__)
    parser.add_argument("profile", type=Path, help="Candidate profile JSON")
    parser.add_argument("job", type=Path, help="Job description JSON")
    parser.add_argument("--fake", action="store_true", help="No API key, no cost.")
    parser.add_argument("--scheme", help="Rubric scheme id. Defaults to config.")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    try:
        profile = json.loads(args.profile.read_text(encoding="utf-8"))
        job = json.loads(args.job.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"Could not read inputs: {error}", file=sys.stderr)
        return 1

    config = None
    try:
        from .config import OrganizationConfig
        config = OrganizationConfig.load()
    except Exception:  # noqa: BLE001 - defaults are fine without config
        pass

    try:
        if args.fake:
            from .adapters.llm import FakeLLM
            fixture = ROOT / "tests" / "fixtures" / "wf04_fake_results.json"
            if not fixture.is_file():
                print(f"Missing fixture: {fixture}", file=sys.stderr)
                return 2
            llm = FakeLLM(fixture)
        else:
            from .adapters.llm import build_llm
            llm = build_llm(config)
        envelope = match(profile, job, llm=llm, config=config,
                         scheme=args.scheme, root=ROOT)
    except RecruitError as error:
        print(str(error), file=sys.stderr)
        print(f"  recovery: {error.recovery}", file=sys.stderr)
        return 1

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")

    results = envelope["results"]
    print(f"  candidate     {envelope['candidate_id']}")
    print(f"  requisition   {envelope['requisition_id']}")
    print(f"  rubric        {results['weighting']['scheme_id']} "
          f"v{results['weighting']['scheme_version']}")
    print()
    print("  component               raw   x weight  =  contribution  confidence")
    print("  " + "-" * 70)
    for component in results["components"]:
        print(f"  {component['component_id']:<22} {component['raw_score']:.2f}"
              f"  x  {component['weight']:.2f}   =    {component['weighted_score']:.3f}"
              f"        {component.get('confidence', 0):.2f}")
    print("  " + "-" * 70)
    print(f"  {'OVERALL':<22} {results['overall_score']:.3f}   "
          f"-> {results['recommendation']}")
    print()
    for requirement in results.get("must_have_requirements") or []:
        marker = {"MET": "met     ", "PARTIAL": "partial ",
                  "NOT_MET": "NOT MET ", "UNKNOWN": "UNKNOWN "}.get(
                      requirement["status"], "?       ")
        print(f"  {marker} {requirement['requirement']}")
    if results.get("gaps"):
        print()
        for gap in results["gaps"]:
            print(f"  gap [{gap['severity']}] {gap['requirement']}: {gap.get('note','')}")
    if envelope["human_review_required"]:
        print(f"\n  review needed: {', '.join(envelope['review_reasons'])}")
    if args.out:
        print(f"\n  written to    {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
