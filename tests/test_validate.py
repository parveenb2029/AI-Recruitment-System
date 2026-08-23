"""Validation tests.

The centrepiece is VR-03: a fabricated employer must be caught. If only one test
in this project were kept, it should be that one.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from recruit import extract as extract_mod
from recruit import ingest
from recruit import validate as validate_mod
from recruit.adapters.llm import FakeLLM

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "wf03_fake_results.json"
RESUME = ROOT / "samples" / "Rahul_Sharma_Resume.pdf"

pytestmark = pytest.mark.skipif(
    not RESUME.is_file() or not FIXTURE.is_file(), reason="fixtures not present"
)


@pytest.fixture
def source_text() -> str:
    return ingest.load(RESUME).text


@pytest.fixture
def envelope() -> dict:
    return extract_mod.extract(RESUME, llm=FakeLLM(FIXTURE), root=ROOT)


def run(envelope, source_text=None):
    return validate_mod.validate(
        envelope, source_text=source_text, schema_dir=ROOT / "schemas"
    )


# -- happy path ---------------------------------------------------------------
def test_clean_extraction_passes(envelope, source_text):
    report = run(envelope, source_text)
    assert report.is_valid, [str(f) for f in report.blocking]
    assert "POTENTIAL_HALLUCINATION" not in report.flags


def test_real_evidence_scores_high(envelope, source_text):
    run(envelope, source_text)
    for item in envelope["evidence"]:
        assert item["match_score"] >= 0.8, item


# -- VR-03: the important one -------------------------------------------------
def test_fabricated_employer_is_caught(envelope, source_text):
    """The model invents a job the candidate never had."""
    tampered = copy.deepcopy(envelope)
    tampered["evidence"].append({
        "field": "experience[2].company",
        "snippet": "Principal Engineer at Google DeepMind leading the Gemini team",
        "source_location": "page 1",
    })
    report = run(tampered, source_text)

    assert not report.is_valid
    assert "POTENTIAL_HALLUCINATION" in report.flags
    hits = [f for f in report.blocking if f.rule == "VR-03"]
    assert hits and hits[0].severity == "CRITICAL"


def test_plausible_but_absent_detail_is_caught(envelope, source_text):
    """Harder case: sounds like the real resume, but is not in it."""
    tampered = copy.deepcopy(envelope)
    tampered["evidence"].append({
        "field": "certifications",
        "snippet": "AWS Certified Solutions Architect Professional",
        "source_location": "page 1",
    })
    report = run(tampered, source_text)
    assert "POTENTIAL_HALLUCINATION" in report.flags


def test_empty_snippet_is_an_error(envelope, source_text):
    tampered = copy.deepcopy(envelope)
    tampered["evidence"].append({"field": "x", "snippet": "   "})
    report = run(tampered, source_text)
    assert any(f.rule == "VR-03" and "Empty" in f.message for f in report.blocking)


def test_whitespace_differences_do_not_trigger_a_false_alarm(envelope, source_text):
    """PDF extraction inserts arbitrary line breaks. A verbatim quote whose
    whitespace differs must NOT be reported as fabricated."""
    tampered = copy.deepcopy(envelope)
    tampered["evidence"].append({
        "field": "experience[0].company",
        "snippet": "Senior   Software\n\nEngineer  |  Infosys   Limited",
    })
    report = run(tampered, source_text)
    assert "POTENTIAL_HALLUCINATION" not in report.flags


def test_missing_source_text_is_reported_not_silently_skipped(envelope):
    report = run(envelope, None)
    assert any("skipped" in f.message for f in report.findings)


# -- data validation ----------------------------------------------------------
def test_malformed_email(envelope, source_text):
    tampered = copy.deepcopy(envelope)
    tampered["results"]["profile"]["personal_info"]["email"] = "rahul.sharma[at]email"
    report = run(tampered, source_text)
    assert any(f.rule == "DV-EMAIL" for f in report.blocking)


def test_placeholder_name(envelope, source_text):
    tampered = copy.deepcopy(envelope)
    tampered["results"]["profile"]["personal_info"]["full_name"] = "John Doe"
    report = run(tampered, source_text)
    assert any(f.rule == "DV-NAME" for f in report.blocking)


def test_start_after_end_date(envelope, source_text):
    tampered = copy.deepcopy(envelope)
    tampered["results"]["profile"]["experience"][1]["start_date"] = "2023-01-01"
    tampered["results"]["profile"]["experience"][1]["end_date"] = "2021-12-31"
    report = run(tampered, source_text)
    assert any(f.rule == "VR-04" and "after" in f.message for f in report.blocking)


def test_confidence_pointer_to_nowhere(envelope, source_text):
    tampered = copy.deepcopy(envelope)
    tampered["results"]["field_confidence"]["/experience/99/company"] = 0.9
    report = run(tampered, source_text)
    assert any(f.rule == "DV-POINTER" for f in report.findings)


# -- business rules -----------------------------------------------------------
def test_low_confidence_must_not_auto_publish(envelope, source_text):
    """The failure that would put an unreviewed extraction in front of a hiring
    manager. Must be CRITICAL."""
    tampered = copy.deepcopy(envelope)
    tampered["confidence_aggregate"] = 0.42
    tampered["human_review_required"] = False
    report = run(tampered, source_text)
    critical = [f for f in report.findings if f.severity == "CRITICAL"]
    assert any(f.rule == "VR-01" for f in critical)


def test_missing_audit_fields_are_critical(envelope, source_text):
    for missing in ("prompt_version", "model_id"):
        tampered = copy.deepcopy(envelope)
        tampered[missing] = ""
        report = run(tampered, source_text)
        assert any(f.rule == "BR-05" and f.severity == "CRITICAL"
                   for f in report.findings), missing


def test_undeclared_low_confidence_field(envelope, source_text):
    tampered = copy.deepcopy(envelope)
    tampered["results"]["low_confidence_fields"] = []
    report = run(tampered, source_text)
    assert any(f.rule == "BV-LOWCONF" for f in report.blocking)


# -- report shape -------------------------------------------------------------
def test_report_names_the_rule_and_the_place(envelope, source_text):
    """'Invalid' helps nobody. A reviewer needs rule, severity, and location."""
    tampered = copy.deepcopy(envelope)
    tampered["results"]["profile"]["personal_info"]["email"] = "nope"
    report = run(tampered, source_text)
    summary = report.summary()
    assert summary["valid"] is False
    finding = summary["findings"][0]
    assert finding["rule"] and finding["severity"] and finding["pointer"]


def test_findings_are_severity_ordered(envelope, source_text):
    tampered = copy.deepcopy(envelope)
    tampered["results"]["profile"]["personal_info"]["email"] = "nope"
    tampered["results"]["profile"]["personal_info"]["phone"] = "call me"
    order = [f.severity for f in run(tampered, source_text).sorted_findings()]
    ranks = [validate_mod.SEVERITY_ORDER[s] for s in order]
    assert ranks == sorted(ranks)
