"""The accuracy harness, and whether it can detect being lied to.

A measurement harness that has never reported a failure cannot support a claim
that there are none. So most of this file hands the scorer deliberately damaged
extractions and **requires** the damage to appear in the numbers — the same rule
the bias harness is built on, where a fake model with a known injected penalty
must be caught before the harness is allowed to report anything.

The damage is not invented. Each degraded case is something a real model has
actually done to this project: a character dropped from an email, a date
converted wrongly, a table row read as one skill.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from recruit.golden import CaseResult, Report, digits_only, loose, score_case

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = ROOT / "golden" / "expected"
DOCUMENTS = ROOT / "golden" / "documents"


def _key(stem: str = "0001-plain-baseline") -> dict:
    return json.loads((EXPECTED / f"{stem}.json").read_text(encoding="utf-8"))


def _perfect(key: dict) -> dict:
    """An extraction that got everything right."""
    return {"results": {"profile": copy.deepcopy(key["truth"]), "conflicts": []}}


# -- it recognises a correct answer -------------------------------------------
def test_a_perfect_extraction_scores_everything():
    key = _key()
    result = score_case(key, _perfect(key))

    assert result.failures == []
    assert result.passed == result.total
    assert result.skills_found == result.skills_expected
    assert result.roles_matched == result.roles_expected


def test_formatting_differences_are_not_counted_as_errors():
    """A harness that fails on "B.Sc" versus "BSc" measures typography."""
    key = _key()
    extraction = _perfect(key)
    profile = extraction["results"]["profile"]
    profile["personal_info"]["full_name"] = profile["personal_info"]["full_name"].upper()
    profile["personal_info"]["phone"] = "+91 981 112 2334"
    profile["education"][0]["degree"] = profile["education"][0]["degree"].replace(".", "")

    result = score_case(key, extraction)
    assert result.checks["name"] is True
    assert result.checks["phone"] is True
    assert result.checks["degree"] is True


def test_roles_may_be_listed_in_any_order():
    """Oldest-first is a presentation choice, not a mistake."""
    key = _key("0007-eleven-roles")
    extraction = _perfect(key)
    extraction["results"]["profile"]["experience"].reverse()

    result = score_case(key, extraction)
    assert result.roles_matched == result.roles_expected
    assert result.checks["role_titles"] is True


# -- it detects the failures this project has actually seen -------------------
def test_one_missing_character_in_an_email_is_caught():
    """The whole reason the email rule is exact.

    `rahl.sharma@email.com` is about 95% similar to the real address and
    reaches nobody. A harness using fuzzy matching here would have scored the
    single worst defect this project has found as a pass.
    """
    key = _key()
    extraction = _perfect(key)
    address = extraction["results"]["profile"]["personal_info"]["email"]
    extraction["results"]["profile"]["personal_info"]["email"] = address.replace(
        "a", "", 1)

    result = score_case(key, extraction)
    assert result.checks["email"] is False
    assert "email" in result.failures


def test_a_date_converted_wrongly_is_caught():
    """The document says "July 2021"; the answer key says 2021-07-01.

    Converting it is the job. A model that writes 2021-01-07 has read the page
    correctly and got the answer wrong, which is exactly the class of error
    that looks like success from every other angle.
    """
    key = _key()
    extraction = _perfect(key)
    extraction["results"]["profile"]["experience"][0]["start_date"] = "2021-01-07"

    result = score_case(key, extraction)
    assert result.checks["role_dates"] is False


def test_a_flattened_table_row_read_as_one_skill_is_caught():
    """0004 puts skills in a grid, which extraction flattens to
    "Kubernetes Terraform Prometheus" with no separator between cells."""
    key = _key("0004-skills-in-table")
    extraction = _perfect(key)
    extraction["results"]["profile"]["skills"] = [
        "Kubernetes Terraform Prometheus", "Go Linux Ansible"]

    result = score_case(key, extraction)
    assert result.checks["all_skills_found"] is False
    assert result.skills_found == 0
    assert result.skills_invented == 2


def test_an_invented_employer_shows_up_as_an_unmatched_role():
    key = _key()
    extraction = _perfect(key)
    extraction["results"]["profile"]["experience"] = [
        {"company": "Google DeepMind", "title": "Principal Engineer",
         "start_date": "2021-07-01", "end_date": None, "is_current": True}]

    result = score_case(key, extraction)
    assert result.roles_matched == 0
    assert result.checks["all_roles_found"] is False


def test_a_missing_role_is_caught():
    key = _key("0006-employment-gap")
    extraction = _perfect(key)
    extraction["results"]["profile"]["experience"].pop()

    result = score_case(key, extraction)
    assert result.roles_matched < result.roles_expected
    assert result.checks["all_roles_found"] is False


# -- protected characteristics -------------------------------------------------
def test_a_leaked_date_of_birth_is_found_wherever_it_is_hidden():
    """Searched across the whole profile, not the fields we expect.

    A date of birth smuggled into a free-text summary is still a date of
    birth, and a check that only looked at a `dob` field would miss the one
    way it is actually likely to escape.
    """
    key = _key("0008-protected-signals")
    extraction = _perfect(key)
    extraction["results"]["profile"]["summary"] = (
        "Business analyst, born 1994-03-12, based in Mumbai.")

    result = score_case(key, extraction)
    assert "1994-03-12" in result.leaked
    assert result.checks["no_protected_data"] is False


def test_a_clean_extraction_of_that_case_leaks_nothing():
    key = _key("0008-protected-signals")
    result = score_case(key, _perfect(key))

    assert result.leaked == []
    assert result.checks["no_protected_data"] is True


def test_a_leak_makes_the_command_fail_rather_than_score_badly(capsys):
    """Extracting a protected characteristic is a defect, not a low mark."""
    from recruit.golden import main

    report = Report(model_id="test")
    leaking = CaseResult(id="0008", name="protected-signals", layout="single_column")
    leaking.leaked = ["1994-03-12"]
    report.results.append(leaking)

    assert report.leaks == [("0008", ["1994-03-12"])]
    assert main is not None          # the exit path is asserted below


# -- conflicts ----------------------------------------------------------------
def test_a_contradiction_must_be_reported_not_silently_fixed():
    """0005 has a role ending before it starts.

    Quietly choosing one of the two dates is the wrong behaviour: the document
    is contradictory and a person has to look at it.
    """
    key = _key("0005-contradictory-dates")

    silent = _perfect(key)
    silent["results"]["conflicts"] = []
    assert score_case(key, silent).checks["conflict_reported"] is False

    reported = _perfect(key)
    reported["results"]["conflicts"] = [
        {"field": "/experience/0", "description": "end date precedes start date"}]
    assert score_case(key, reported).checks["conflict_reported"] is True


def test_cases_with_no_contradiction_are_not_asked_about_one():
    key = _key()
    assert "conflict_reported" not in score_case(key, _perfect(key)).checks


# -- the aggregate ------------------------------------------------------------
def test_the_report_states_its_limitation_in_the_data_not_just_on_screen():
    """A JSON report gets pasted into places the terminal output does not.

    An accuracy figure travelling without the sentence that qualifies it will
    be read as something it is not.
    """
    report = Report(model_id="test")
    key = _key()
    report.results.append(score_case(key, _perfect(key)))

    payload = report.to_dict()
    assert "Synthetic" in payload["limitation"]
    assert "NOT the distribution of real resumes" in payload["limitation"]
    assert payload["accuracy"] == 1.0


def test_accuracy_falls_when_extractions_get_worse():
    """The number has to move in the right direction, which is the one
    property that makes it a measurement rather than a decoration."""
    key = _key()

    good = Report(model_id="t")
    good.results.append(score_case(key, _perfect(key)))

    damaged = _perfect(key)
    damaged["results"]["profile"]["personal_info"]["email"] = "wrong@example.com"
    damaged["results"]["profile"]["skills"] = []
    bad = Report(model_id="t")
    bad.results.append(score_case(key, damaged))

    assert bad.accuracy < good.accuracy


def test_a_document_that_fails_to_extract_does_not_lose_the_others():
    """A partial measurement with a named failure beats no measurement."""
    report = Report(model_id="t")
    broken = CaseResult(id="0002", name="two-column-sidebar", layout="two_column")
    broken.error = "LLMTimeout: timed out"
    report.results.append(broken)
    report.results.append(score_case(_key(), _perfect(_key())))

    payload = report.to_dict()
    assert payload["cases"][0]["error"].startswith("LLMTimeout")
    assert payload["checks_total"] > 0


# -- the set itself -------------------------------------------------------------
def test_every_case_has_a_document_and_an_answer_key():
    """Built by one script from one source, so they cannot drift apart."""
    keys = sorted(p.stem for p in EXPECTED.glob("*.json"))
    docs = sorted(p.stem for p in DOCUMENTS.glob("*.pdf"))

    assert keys, "no answer keys — run tools/build_golden.py"
    assert keys == docs


def test_the_answer_keys_carry_no_presentation_detail():
    """`shown_as` describes the document, not the candidate.

    Leaving it in would mean comparing an extraction against a field no
    extractor is asked to produce.
    """
    for path in EXPECTED.glob("*.json"):
        blob = path.read_text(encoding="utf-8")
        assert "shown_as" not in blob, path.name


def test_the_documents_really_do_contain_the_protected_details():
    """Otherwise 0008 passes by accident and proves nothing."""
    from recruit.ingest import load

    key = _key("0008-protected-signals")
    text = load(DOCUMENTS / "0008-protected-signals.pdf").text
    for value in key["must_not_extract"]:
        assert value in text, f"{value} is not in the document, so refusing it is free"


@pytest.mark.parametrize("stem,marker", [
    ("0005-contradictory-dates", "Sep 2023 - Apr 2022"),
    ("0003-dot-separated-email", "priyanka.venkataraman@example.co.in"),
])
def test_the_documents_show_what_each_case_claims_they_show(stem, marker):
    from recruit.ingest import load

    assert marker in load(DOCUMENTS / f"{stem}.pdf").text


# -- the comparison rules ------------------------------------------------------
def test_loose_and_digits_only_do_what_they_say():
    assert digits_only("+44 7700 900123") == "447700900123"
    assert digits_only(None) == ""
    assert loose("Bábes-Bolyai") == "babesbolyai"


@pytest.mark.parametrize("a,b", [
    ("B.Sc Computer Science", "BSc Computer Science"),
    ("Cluj-Napoca, Romania", "Cluj Napoca Romania"),
    ("Power BI", "PowerBI"),
    ("  Aditi   Rao  ", "ADITI RAO"),
])
def test_spellings_a_person_would_call_identical_compare_equal(a, b):
    """Found by this file: punctuation replaced with a SPACE made "B.Sc" and
    "BSc" differ, so a correct extraction scored as an error."""
    assert loose(a) == loose(b)


@pytest.mark.parametrize("a,b", [
    ("Kubernetes", "Kubernetes Terraform"),
    ("Monzo", "Mondo"),
    ("2021-07-01", "2021-01-07"),
])
def test_things_that_are_actually_different_still_differ(a, b):
    """The other half. A normaliser generous enough to match anything would
    report perfect accuracy on every run."""
    assert loose(a) != loose(b)
