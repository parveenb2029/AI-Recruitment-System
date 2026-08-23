"""WF-04 matching tests.

The central claim under test: the model does not produce the score. It judges
components; the application does the arithmetic. If that ever stops being true,
a rejected candidate cannot be given a real answer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from recruit.adapters.llm import FakeLLM
from recruit.config import OrganizationConfig
from recruit.match import MatchError, band, combine, match, model_facing_schema
from recruit.prompts import load_results_schema

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "wf04_fake_results.json"
PROFILE = ROOT / "samples" / "Rahul_Sharma.json"
JOB = ROOT / "samples" / "Software_Engineer.json"

BANDS = {"strong_match_min": 0.80, "match_min": 0.65, "partial_match_min": 0.45}

pytestmark = pytest.mark.skipif(
    not (FIXTURE.is_file() and PROFILE.is_file() and JOB.is_file()),
    reason="fixtures not present",
)


@pytest.fixture
def profile():
    return json.loads(PROFILE.read_text(encoding="utf-8"))


@pytest.fixture
def job():
    return json.loads(JOB.read_text(encoding="utf-8"))


@pytest.fixture
def config():
    return OrganizationConfig.load(ROOT / "config" / "organization.example.yaml")


# -- the model cannot score ---------------------------------------------------
def test_computed_fields_are_stripped_from_the_model_schema():
    """Structural enforcement, not a convention the next prompt edit can undo."""
    schema = model_facing_schema(load_results_schema("WF-04", ROOT / "schemas"))
    assert "overall_score" not in schema["properties"]
    assert "recommendation" not in schema["properties"]
    assert "auto_archive_eligible" not in schema["properties"]
    assert "weighting" not in schema["properties"]
    component = schema["properties"]["components"]["items"]["properties"]
    assert "weight" not in component
    assert "weighted_score" not in component
    # what the model IS asked for
    assert {"component_id", "raw_score", "rationale", "evidence"} <= set(component)


def test_model_schema_does_not_mutate_the_original():
    original = load_results_schema("WF-04", ROOT / "schemas")
    before = json.dumps(original, sort_keys=True)
    model_facing_schema(original)
    assert json.dumps(original, sort_keys=True) == before


# -- the arithmetic -----------------------------------------------------------
def test_overall_score_is_the_weighted_sum():
    components = [
        {"component_id": "must_have_coverage", "raw_score": 0.80},
        {"component_id": "experience_band", "raw_score": 0.85},
        {"component_id": "domain_match", "raw_score": 0.75},
    ]
    weights = {"must_have_coverage": 0.5, "experience_band": 0.3, "domain_match": 0.2}
    result = combine(components, weights, BANDS, 0.40)
    assert result["overall_score"] == pytest.approx(0.805)
    assert result["recommendation"] == "STRONG_MATCH"


def test_changing_a_weight_changes_the_outcome_predictably(profile, job, config):
    default = match(profile, job, llm=FakeLLM(FIXTURE), config=config, root=ROOT)
    swe = match(profile, job, llm=FakeLLM(FIXTURE), config=config,
                scheme="swe-ic", root=ROOT)
    must_default = next(c for c in default["results"]["components"]
                        if c["component_id"] == "must_have_coverage")
    must_swe = next(c for c in swe["results"]["components"]
                    if c["component_id"] == "must_have_coverage")
    assert must_swe["weight"] > must_default["weight"]
    assert must_swe["weighted_score"] > must_default["weighted_score"]
    assert must_swe["raw_score"] == must_default["raw_score"]   # judgement unchanged


def test_weighting_provenance_is_recorded(profile, job, config):
    """A historical match must stay reproducible after the rubric changes."""
    envelope = match(profile, job, llm=FakeLLM(FIXTURE), config=config, root=ROOT)
    weighting = envelope["results"]["weighting"]
    assert weighting["scheme_id"] and weighting["scheme_version"]
    assert sum(weighting["weights"].values()) == pytest.approx(1.0)


# -- guard rails --------------------------------------------------------------
def test_weights_must_sum_to_one():
    with pytest.raises(MatchError, match="BV-04"):
        combine([{"component_id": "a", "raw_score": 0.5}], {"a": 0.4, "b": 0.4},
                BANDS, 0.40)


def test_unweighted_component_is_rejected():
    with pytest.raises(MatchError, match="no weight"):
        combine([{"component_id": "vibes", "raw_score": 0.9}],
                {"must_have_coverage": 1.0}, BANDS, 0.40)


def test_missing_component_is_rejected_not_scored_as_zero():
    """Silently treating an unscored dimension as zero would change who is
    rejected, invisibly."""
    with pytest.raises(MatchError, match="did not score"):
        combine([{"component_id": "must_have_coverage", "raw_score": 0.9}],
                {"must_have_coverage": 0.5, "experience_band": 0.5}, BANDS, 0.40)


def test_raw_score_out_of_range_is_rejected():
    with pytest.raises(MatchError, match="outside"):
        combine([{"component_id": "a", "raw_score": 1.7}], {"a": 1.0}, BANDS, 0.40)


def test_duplicate_components_are_rejected():
    with pytest.raises(MatchError, match="Duplicate"):
        combine([{"component_id": "a", "raw_score": 0.5},
                 {"component_id": "a", "raw_score": 0.9}], {"a": 1.0}, BANDS, 0.40)


# -- bands and BR-04 ----------------------------------------------------------
@pytest.mark.parametrize("score,expected", [
    (0.95, "STRONG_MATCH"), (0.80, "STRONG_MATCH"),
    (0.79, "MATCH"), (0.65, "MATCH"),
    (0.64, "PARTIAL_MATCH"), (0.45, "PARTIAL_MATCH"),
    (0.44, "NO_MATCH"), (0.0, "NO_MATCH"),
])
def test_recommendation_bands(score, expected):
    assert band(score, BANDS) == expected


def test_weak_candidate_is_flagged_for_a_human_not_auto_rejected(
    profile, job, config, tmp_path
):
    """BR-04: below-threshold means ELIGIBLE for archive. A person still decides."""
    weak = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for component in weak["components"]:
        component["raw_score"] = 0.2
    path = tmp_path / "weak.json"
    path.write_text(json.dumps(weak), encoding="utf-8")

    envelope = match(profile, job, llm=FakeLLM(path), config=config, root=ROOT)
    assert envelope["results"]["auto_archive_eligible"] is True
    assert envelope["human_review_required"] is True
    assert "BELOW_AUTO_ARCHIVE_THRESHOLD" in envelope["review_reasons"]


# -- requirement resolution ---------------------------------------------------
def test_unknown_requirement_forces_review(profile, job, config):
    """UNKNOWN is not NOT_MET. Absence of evidence is not evidence of absence."""
    envelope = match(profile, job, llm=FakeLLM(FIXTURE), config=config, root=ROOT)
    statuses = {r["requirement"]: r["status"]
                for r in envelope["results"]["must_have_requirements"]}
    assert statuses["Mentoring junior engineers"] == "UNKNOWN"
    assert "UNRESOLVED_REQUIREMENTS" in envelope["review_reasons"]


def test_confidence_is_the_weakest_component(profile, job, config):
    envelope = match(profile, job, llm=FakeLLM(FIXTURE), config=config, root=ROOT)
    lowest = min(c["confidence"] for c in envelope["results"]["components"])
    assert envelope["confidence_aggregate"] == pytest.approx(lowest)


def test_excluded_signals_are_recorded_for_the_bias_audit(profile, job, config):
    envelope = match(profile, job, llm=FakeLLM(FIXTURE), config=config, root=ROOT)
    excluded = envelope["results"]["excluded_signals"]
    for signal in ("name", "gender", "age"):
        assert signal in excluded


def test_envelope_validates_against_the_wf04_schema(profile, job, config, tmp_path):
    from recruit.validate import validate as run_validation
    envelope = match(profile, job, llm=FakeLLM(FIXTURE), config=config, root=ROOT)
    report = run_validation(envelope, source_text=json.dumps(profile),
                            config=config, schema_dir=ROOT / "schemas")
    schema_errors = [f for f in report.blocking if f.rule == "VR-02"]
    assert not schema_errors, [str(f) for f in schema_errors]
