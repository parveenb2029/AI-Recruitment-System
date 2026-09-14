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
    tampered["results"]["field_confidence"].append(
        {"pointer": "/experience/99/company", "confidence": 0.9})
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


def test_an_extraction_with_no_citations_cannot_pass(envelope, source_text):
    """The most dangerous result this project can produce.

    A real run came back `SUCCESS`, confidence 0.92, human review NOT required,
    with zero evidence citations — not one claim traceable to the document. It
    passed because "no citations" was a WARNING, and warnings do not block.

    That combination is the one the whole design exists to prevent. VR-03 is the
    hallucination defence; with nothing to check, it checked nothing, and the
    run still arrived wearing the same green tick as a verified one. An
    extraction that *cannot* be checked is more dangerous than one that fails,
    because a reviewer has no reason to look harder at it.

    The model's own confidence is not an answer. It is self-reported and
    uncalibrated, and a model inventing an employer is not less sure while it
    does so.
    """
    stripped = copy.deepcopy(envelope)
    stripped["evidence"] = []

    report = run(stripped, source_text)

    vr03 = [f for f in report.findings if f.rule == "VR-03"]
    assert vr03, "no VR-03 finding at all"
    assert vr03[0].severity == "ERROR"
    assert report.is_valid is False, (
        "an extraction with nothing traceable to source must not validate"
    )
    # And the reason has to reach whoever reads it.
    assert "traced" in vr03[0].message


# -- VR-05: the field must agree with its own citation ------------------------
def test_a_mangled_email_is_caught_even_though_the_quote_is_real(envelope, source_text):
    """The failure that passed every check this project had.

    A real run quoted `Email: rahul.sharma@email.com` from the document — a
    genuine snippet, found in the source, VR-03 satisfied — and extracted
    `rahl.sharma@email.com`. One character missing from the only field anyone
    would use to contact that candidate. Status SUCCESS, zero findings, no
    review required.

    VR-03 proves a snippet exists. It proves nothing about the field the snippet
    was cited for, and nothing else was looking.
    """
    tampered = copy.deepcopy(envelope)
    tampered["results"]["profile"]["personal_info"]["email"] = "rahl.sharma@email.com"
    tampered["evidence"] = [{
        "field": "email",
        "pointer": "/personal_info/email",
        "snippet": "Email: rahul.sharma@email.com",
    }]

    report = run(tampered, source_text)

    vr05 = [f for f in report.findings if f.rule == "VR-05"]
    assert vr05, [str(f) for f in report.findings]
    assert vr05[0].severity == "ERROR"
    assert report.is_valid is False
    assert "VALUE_NOT_IN_EVIDENCE" in report.flags


def test_an_email_that_does_match_its_citation_passes(envelope, source_text):
    """The check must not fire on the correct case, or it will be turned off."""
    clean = copy.deepcopy(envelope)
    clean["evidence"] = [{
        "field": "email",
        "pointer": "/personal_info/email",
        "snippet": "Email: rahul.sharma@email.com | Phone: +91-98765-43210",
    }]

    report = run(clean, source_text)
    assert not [f for f in report.findings if f.rule == "VR-05"]


def test_a_summary_is_allowed_to_differ_from_what_it_summarises(envelope, source_text):
    """Paraphrase is the job, not a defect.

    Checking a summary against the sentences it was written from would fail
    every honest extraction, and a rule that fires on correct work is a rule
    people disable.
    """
    paraphrased = copy.deepcopy(envelope)
    paraphrased["results"]["profile"]["summary"] = (
        "Backend engineer with cloud experience across several employers."
    )
    paraphrased["evidence"] = [{
        "field": "summary",
        "pointer": "/summary",
        "snippet": "Software engineer with 4.5 years building backend services",
    }]

    report = run(paraphrased, source_text)
    assert not [f for f in report.findings if f.rule == "VR-05"]


def test_a_fuzzy_match_is_refused_for_an_address(envelope, source_text):
    """Near enough is the wrong standard for something you have to type.

    `rahl.sharma@email.com` scores about 0.95 against the real address. Fuzzy
    matching would wave it through, and the mail would reach nobody.
    """
    from recruit.validate import VERBATIM_FIELDS

    assert "email" in VERBATIM_FIELDS
    assert "phone" in VERBATIM_FIELDS


def test_a_contact_field_nobody_cited_is_flagged(envelope, source_text):
    """Silence read as success.

    A real run produced six citations, validation green, and a mangled email —
    and VR-05 said nothing, because the email was not one of the six. A field
    nobody cited is exactly as unverified as one cited wrongly; the difference
    is only that the first kind leaves no trace to argue with.
    """
    uncited = copy.deepcopy(envelope)
    uncited["evidence"] = [
        item for item in uncited["evidence"]
        if not str(item.get("pointer", "")).endswith("/email")
    ]

    report = run(uncited, source_text)

    vr06 = [f for f in report.findings if f.rule == "VR-06"]
    assert vr06, [str(f) for f in report.findings]
    assert vr06[0].severity == "ERROR"
    assert "email" in vr06[0].message
    assert report.is_valid is False


def test_a_field_that_was_never_extracted_is_not_demanded(envelope, source_text):
    """Absent is a different problem from unverified, and has its own rules."""
    no_phone = copy.deepcopy(envelope)
    no_phone["results"]["profile"]["personal_info"]["phone"] = ""
    no_phone["evidence"] = [
        item for item in no_phone["evidence"]
        if not str(item.get("pointer", "")).endswith("/phone")
    ]

    report = run(no_phone, source_text)
    assert not [f for f in report.findings
                if f.rule == "VR-06" and "phone" in f.message]


def test_a_citation_must_say_what_it_is_a_citation_for():
    """`pointer` was optional, so a quote could be attached to nothing.

    It reads as evidence and counts as evidence, and VR-05 skipped every such
    entry without a word. Requiring the pointer — from the same menu of real
    paths — means every citation lands on something checkable.
    """
    from recruit.prompts import load_results_schema, with_required_evidence

    schema = with_required_evidence(load_results_schema("WF-03", ROOT / "schemas"))
    item = schema["properties"]["evidence"]["items"]

    assert "pointer" in item["required"]

    pointer = item["properties"]["pointer"]
    assert "/personal_info/email" in pointer["enum"]
    # **No `$ref` beside the enum.** `pointer` is defined by reference in the
    # envelope schema, and a constraint added alongside a `$ref` reads correctly
    # and does nothing: grammar conversion follows the reference and drops the
    # sibling. The first attempt did exactly that, so the menu was decoration
    # and a real model answered `pointer: "RAHUL SHARMA"` — the value itself
    # rather than a path to it. Broken and working look identical unless
    # something goes looking for the `$ref`.
    assert "$ref" not in pointer, (
        "an enum next to a $ref is ignored by the grammar - replace, do not amend"
    )
    assert pointer["type"] == "string"


def test_a_field_we_supplied_ourselves_is_not_checked_against_the_resume(
        envelope, source_text):
    """`candidate_id` comes from the command line, not the document.

    A real run warned "similarity 0.20" for it — true, useless, and exactly the
    kind of noise that teaches a reviewer to skim past the warnings that matter.
    """
    ours = copy.deepcopy(envelope)
    ours["evidence"].append({
        "field": "candidate_id",
        "pointer": "/candidate_id",
        "snippet": "RAHUL SHARMA",
    })

    report = run(ours, source_text)
    assert not [f for f in report.findings
                if f.rule == "VR-05" and "candidate_id" in str(f.detail)]
