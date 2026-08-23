"""Bias harness tests.

The most important test in this file is `test_detects_injected_bias`. A harness
that reports "no bias found" is worthless unless it has been shown capable of
finding bias — so we plant a known one and require it to be caught.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from recruit.adapters.llm import FakeLLM
from recruit.bias.audit import MATERIAL_DELTA, run_audit
from recruit.bias.fakes import BiasedFakeLLM
from recruit.bias.perturb import (
    PERTURBATIONS,
    assert_substance_unchanged,
    generate_variants,
)
from recruit.bias.report import render_markdown
from recruit.config import OrganizationConfig

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "wf04_fake_results.json"
PROFILE = ROOT / "samples" / "Rahul_Sharma.json"
JOB = ROOT / "samples" / "Software_Engineer.json"

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


# -- THE test -----------------------------------------------------------------
def test_detects_injected_bias(profile, job, config):
    """Plant a bias. If the harness misses it, every clean report is worthless."""
    result = run_audit(
        profile, job,
        llm_factory=lambda: BiasedFakeLLM(FIXTURE, penalise={"Okonkwo": 0.30}),
        config=config, dimensions=["given_name"], root=ROOT,
    )
    finding = result.findings[0]
    assert result.passed is False
    assert finding.is_material
    assert finding.worst_group == "west_african"
    assert finding.component_spreads()["domain_match"] == pytest.approx(0.30)


def test_attributes_bias_to_the_right_component(profile, job, config):
    """Knowing the total moved is not actionable. Knowing which sub-score is."""
    result = run_audit(
        profile, job,
        llm_factory=lambda: BiasedFakeLLM(
            FIXTURE, penalise={"Whitfield": 0.20}, component="must_have_coverage"),
        config=config, dimensions=["given_name"], root=ROOT,
    )
    spreads = result.findings[0].component_spreads()
    assert spreads["must_have_coverage"] == pytest.approx(0.20)
    assert spreads["domain_match"] == pytest.approx(0.0)


def test_unbiased_model_produces_a_clean_result(profile, job, config):
    """The control. Without it, a positive finding proves nothing."""
    result = run_audit(profile, job, llm_factory=lambda: FakeLLM(FIXTURE),
                       config=config, root=ROOT)
    assert result.passed
    assert all(f.spread == 0.0 for f in result.findings)


# -- the controlled-comparison guarantee --------------------------------------
def test_perturbations_hold_substance_constant(profile):
    """If a perturbation changed a skill, a score delta would look like bias."""
    variants = generate_variants(profile)
    assert_substance_unchanged(variants)          # raises on failure


def test_substance_check_catches_a_broken_perturbation(profile):
    variants = generate_variants(profile, ["given_name"])
    variants[0].profile["skills"].append("Rust")   # sabotage
    with pytest.raises(AssertionError, match="substantive"):
        assert_substance_unchanged(variants)


def test_age_perturbation_leaves_employment_untouched(profile):
    """Shifting a current role's start date backwards turns 5 years of tenure
    into 23. That measures experience, not age — so employment must not move."""
    variants = generate_variants(profile, ["age_signal"])
    histories = {
        v.group: json.dumps(v.profile["experience"], sort_keys=True)
        for v in variants
    }
    assert len(set(histories.values())) == 1, "employment differs across age variants"
    # and the graduation year must actually vary, or the dimension does nothing
    years = {v.profile["education"][0]["graduation_date"][:4] for v in variants}
    assert len(years) == len(variants)


def test_age_substance_check_catches_a_shifted_employment_history(profile):
    variants = generate_variants(profile, ["age_signal"])
    variants[-1].profile["experience"][0]["start_date"] = "2005-01-15"
    with pytest.raises(AssertionError, match="tenure, not age"):
        assert_substance_unchanged(variants)


def test_name_perturbation_changes_name_and_derived_fields(profile):
    variants = {v.group: v for v in generate_variants(profile, ["given_name"])}
    anglo = variants["anglo"].profile["personal_info"]
    assert anglo["full_name"] == "James Whitfield"
    assert "james" in anglo["email"]        # email must not leak the old name
    assert "rahul" not in json.dumps(anglo).lower()


def test_every_dimension_produces_one_variant_per_group(profile):
    variants = generate_variants(profile)
    counts: dict[str, int] = {}
    for variant in variants:
        counts[variant.dimension] = counts.get(variant.dimension, 0) + 1
    for dimension, spec in PERTURBATIONS.items():
        assert counts[dimension] == len(spec["groups"])


def test_unknown_dimension_is_rejected(profile):
    with pytest.raises(ValueError, match="Unknown dimensions"):
        generate_variants(profile, ["astrological_sign"])


# -- measurement --------------------------------------------------------------
def test_material_threshold_is_tight():
    """This is a defect threshold, not a tolerance."""
    assert MATERIAL_DELTA <= 0.01


def test_four_fifths_ratio_is_computed(profile, job, config):
    result = run_audit(profile, job, llm_factory=lambda: FakeLLM(FIXTURE),
                       config=config, dimensions=["given_name"], root=ROOT)
    ratio = result.findings[0].four_fifths_ratio(result.threshold)
    assert ratio is None or 0.0 <= ratio <= 1.0


def test_a_failing_variant_does_not_abort_the_audit(profile, job, config):
    """A partial report beats no report."""
    class Exploding:
        model_id = "boom"
        calls = {"n": 0}

        def complete_structured(self, **kwargs):
            self.calls["n"] += 1
            if self.calls["n"] > 2:
                raise RuntimeError("provider exploded")
            return FakeLLM(FIXTURE).complete_structured(**kwargs)

    shared = Exploding()
    result = run_audit(profile, job, llm_factory=lambda: shared, config=config,
                       dimensions=["given_name"], root=ROOT)
    assert any(r.error for r in result.findings[0].results)


# -- report -------------------------------------------------------------------
def test_report_states_its_own_limits(profile, job, config):
    """A report that overclaims is worse than none — someone will cite it."""
    result = run_audit(profile, job, llm_factory=lambda: FakeLLM(FIXTURE),
                       config=config, root=ROOT)
    markdown = render_markdown(result)
    assert "not a compliance certificate" in markdown
    assert "independent" in markdown
    assert "One profile per group" in markdown
    assert "A clean result is not proof" in markdown


def test_clean_report_tells_the_reader_to_verify_the_harness(profile, job, config):
    result = run_audit(profile, job, llm_factory=lambda: FakeLLM(FIXTURE),
                       config=config, root=ROOT)
    assert "detects_injected_bias" in render_markdown(result)


def test_report_names_the_leaking_component(profile, job, config):
    result = run_audit(
        profile, job,
        llm_factory=lambda: BiasedFakeLLM(FIXTURE, penalise={"Okonkwo": 0.30}),
        config=config, dimensions=["given_name"], root=ROOT,
    )
    markdown = render_markdown(result)
    assert "Which component leaked" in markdown
    assert "domain_match" in markdown
    assert "Fix the component, not the total" in markdown
