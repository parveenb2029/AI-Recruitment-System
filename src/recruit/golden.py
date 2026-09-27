"""Measure what the extractor actually gets right.

    python -m recruit.golden                     # the fake model, as a smoke test
    python -m recruit.golden --provider ollama --model qwen2.5:3b
    python -m recruit.golden --json report.json

Until now this project has had no accuracy figure at all, and said so in three
places in its README. That honesty was correct and is not a substitute for a
measurement: every threshold in `config/organization.yaml` is a round number
somebody chose, `confidence.calibrated` is `false`, and nothing downstream of
that can be trusted to mean what it says.

**What this measures, and what it does not.** The set is synthetic. Eight
documents, built by `tools/build_golden.py` from cases a person wrote, covering
failure modes that were observed or reasoned about rather than sampled from
real applications. So a number from here describes *how this system handles
these eight constructed documents*. It does not describe how it handles the
distribution of real resumes, because no real resumes are involved — hard rule
5 forbids them in this repository, and the operator has been clear they do not
want other people's CVs. **That limitation is not a footnote and is printed
with every result**, because an accuracy figure quoted without it will be read
as something it is not.

**Why the comparison rules differ per field**, which looks inconsistent and is
the most important thing here:

- **Email and links are compared character for character.** Fuzzy matching is
  precisely wrong for them. `rahl.sharma@email.com` scores about 0.95 against
  the real address and reaches nobody at all. This project has watched a model
  drop that exact character.
- **Phone numbers are compared as digits**, because `+44 7700 900123` and
  `+447700900123` are the same number and a system that called one of them
  wrong would be measuring formatting.
- **Names, employers, titles and places are compared loosely** — case,
  punctuation and spacing normalised — because "B.Sc" and "BSc" are not an
  extraction error.
- **Dates are compared exactly, in ISO form.** The document shows
  "Apr 2021 - Mar 2023"; converting that is the job, and getting it nearly
  right is getting it wrong.

**The harness is itself under test.** `tests/test_golden.py` runs a deliberately
degraded extractor through it and *requires* the damage to show up in the
numbers. A measurement harness that has never reported a failure cannot support
a claim that there are none — the same rule the bias harness is built on.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
DOCUMENTS = ROOT / "golden" / "documents"
EXPECTED = ROOT / "golden" / "expected"

__all__ = [
    "CaseResult",
    "Report",
    "digits_only",
    "loose",
    "run",
    "score_case",
]


# -- comparison ---------------------------------------------------------------
def loose(value: Any) -> str:
    """A comparison key: letters and digits only, lower case, accents folded.

    Not a display form — the result is unreadable on purpose, because its only
    job is to answer "would a person call these the same thing?"

    **Spacing is removed as well as punctuation**, and that detail was found by
    this harness's own tests. Replacing punctuation with a space instead turns
    "B.Sc" into "b sc" while "BSc" stays "bsc", so two spellings of one degree
    compared as different and a correct extraction scored as an error. Removing
    both makes "B.Sc"/"BSc", "Cluj-Napoca"/"Cluj Napoca" and "Power BI"/
    "PowerBI" agree, which is what a human reading them would say.
    """
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", text.lower())


def digits_only(value: Any) -> str:
    """A phone number without its formatting. Leading zeros and country codes
    are kept; only separators go."""
    return re.sub(r"\D", "", str(value or ""))


def _exact(expected: Any, got: Any) -> bool:
    """No normalisation at all. For addresses and links."""
    return str(expected or "").strip() == str(got or "").strip()


@dataclass
class CaseResult:
    """One document's worth of answers, and what went wrong."""

    id: str
    name: str
    layout: str
    tests: str = ""
    checks: dict[str, bool] = field(default_factory=dict)
    skills_found: int = 0
    skills_expected: int = 0
    skills_invented: int = 0
    roles_matched: int = 0
    roles_expected: int = 0
    leaked: list[str] = field(default_factory=list)
    conflict_expected: bool = False
    conflict_reported: bool = False
    error: str | None = None

    @property
    def passed(self) -> int:
        return sum(1 for ok in self.checks.values() if ok)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def failures(self) -> list[str]:
        return sorted(name for name, ok in self.checks.items() if not ok)


def _match_roles(expected: list[dict], got: list[dict]) -> list[tuple[dict, dict]]:
    """Pair expected roles with extracted ones by employer, not by position.

    Position would punish a model that read every job correctly and listed them
    oldest-first, which is a presentation difference and not an error.
    """
    remaining = list(got)
    pairs: list[tuple[dict, dict]] = []
    for want in expected:
        target = loose(want.get("company"))
        found = next((g for g in remaining if loose(g.get("company")) == target), None)
        if found is not None:
            remaining.remove(found)
            pairs.append((want, found))
    return pairs


def score_case(expected: dict, envelope: dict) -> CaseResult:
    """Compare one extraction against one answer key."""
    truth = expected["truth"]
    result = CaseResult(
        id=expected["id"], name=expected["name"],
        layout=expected.get("layout", ""), tests=expected.get("tests", ""),
        conflict_expected=bool(expected.get("expect_conflict")),
        roles_expected=len(truth.get("experience") or []),
        skills_expected=len(truth.get("skills") or []),
    )

    profile = (envelope.get("results") or {}).get("profile") or {}
    personal = profile.get("personal_info") or {}
    want_personal = truth.get("personal_info") or {}

    # Contact details. The email rule is the strict one on purpose.
    result.checks["name"] = loose(want_personal.get("full_name")) == loose(
        personal.get("full_name"))
    result.checks["email"] = _exact(want_personal.get("email"),
                                    personal.get("email"))
    result.checks["phone"] = digits_only(want_personal.get("phone")) == digits_only(
        personal.get("phone"))
    result.checks["location"] = loose(want_personal.get("location")) == loose(
        personal.get("location"))

    # Employment. Matched by employer, then judged on title and dates.
    pairs = _match_roles(truth.get("experience") or [], profile.get("experience") or [])
    result.roles_matched = len(pairs)
    result.checks["all_roles_found"] = result.roles_matched == result.roles_expected
    titles_ok = dates_ok = 0
    for want, got in pairs:
        if loose(want.get("title")) == loose(got.get("title")):
            titles_ok += 1
        if (_exact(want.get("start_date"), got.get("start_date"))
                and _exact(want.get("end_date"), got.get("end_date"))):
            dates_ok += 1
    if pairs:
        result.checks["role_titles"] = titles_ok == len(pairs)
        result.checks["role_dates"] = dates_ok == len(pairs)

    # Education, first entry only — the cases each have one.
    want_school = (truth.get("education") or [{}])[0]
    got_school = (profile.get("education") or [{}])[0]
    if want_school:
        result.checks["institution"] = loose(want_school.get("institution")) == loose(
            got_school.get("institution"))
        result.checks["degree"] = loose(want_school.get("degree")) == loose(
            got_school.get("degree"))

    # Skills. Counted rather than pass/fail, because partial credit is the
    # honest answer for a list and a single boolean would hide most of it.
    want_skills = {loose(s) for s in (truth.get("skills") or [])}
    got_skills = {loose(s) for s in (profile.get("skills") or [])}
    result.skills_found = len(want_skills & got_skills)
    result.skills_invented = len(got_skills - want_skills)
    result.checks["all_skills_found"] = result.skills_found == len(want_skills)

    # Protected characteristics. The document volunteers them; nothing may
    # come back out. Searched across the WHOLE extracted profile rather than
    # the fields we happen to expect them in — a date of birth smuggled into a
    # summary is still a date of birth.
    blob = json.dumps(profile, ensure_ascii=False).lower()
    result.leaked = [v for v in (expected.get("must_not_extract") or [])
                     if str(v).lower() in blob]
    result.checks["no_protected_data"] = not result.leaked

    # A contradiction must be reported rather than quietly resolved.
    if result.conflict_expected:
        conflicts = (envelope.get("results") or {}).get("conflicts") or []
        result.conflict_reported = bool(conflicts)
        result.checks["conflict_reported"] = result.conflict_reported

    return result


@dataclass
class Report:
    model_id: str
    results: list[CaseResult] = field(default_factory=list)

    @property
    def checks_passed(self) -> int:
        return sum(r.passed for r in self.results)

    @property
    def checks_total(self) -> int:
        return sum(r.total for r in self.results)

    @property
    def accuracy(self) -> float:
        return self.checks_passed / self.checks_total if self.checks_total else 0.0

    def rate(self, name: str) -> float | None:
        applicable = [r.checks[name] for r in self.results if name in r.checks]
        return (sum(applicable) / len(applicable)) if applicable else None

    @property
    def leaks(self) -> list[tuple[str, list[str]]]:
        return [(r.id, r.leaked) for r in self.results if r.leaked]

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "accuracy": round(self.accuracy, 4),
            "checks_passed": self.checks_passed,
            "checks_total": self.checks_total,
            "per_check": {name: round(value, 4)
                          for name in sorted({k for r in self.results for k in r.checks})
                          if (value := self.rate(name)) is not None},
            "protected_data_leaks": [{"case": cid, "values": vals}
                                     for cid, vals in self.leaks],
            "limitation": (
                "Synthetic set of 8 constructed documents. Describes how this "
                "system handles these documents, NOT the distribution of real "
                "resumes. No real candidate data is used (hard rule 5)."
            ),
            "cases": [
                {
                    "id": r.id, "name": r.name, "layout": r.layout,
                    "tests": r.tests,
                    "passed": r.passed, "total": r.total,
                    "failures": r.failures,
                    "skills_found": r.skills_found,
                    "skills_expected": r.skills_expected,
                    "skills_invented": r.skills_invented,
                    "roles_matched": r.roles_matched,
                    "roles_expected": r.roles_expected,
                    "leaked": r.leaked,
                    "error": r.error,
                }
                for r in self.results
            ],
        }


def run(llm, *, config=None, documents: Path = DOCUMENTS,
        expected: Path = EXPECTED, limit: int | None = None) -> Report:
    """Extract every document with `llm` and score the answers."""
    from .errors import RecruitError
    from .extract import extract

    report = Report(model_id=getattr(llm, "model_id", "unknown"))
    keys = sorted(expected.glob("*.json"))[:limit]

    for index, key_path in enumerate(keys):
        key = json.loads(key_path.read_text(encoding="utf-8"))
        document = documents / f"{key_path.stem}.pdf"
        # Announced BEFORE the call, not after. A local model takes minutes per
        # document, and the first version of this printed on completion — so
        # the first few minutes of a correct run were indistinguishable from a
        # hang, which is how somebody kills a job that was working. Flushed
        # because stderr is line-buffered when piped and the whole point is
        # that it appears now.
        print(f"  [{index + 1}/{len(keys)}] {key_path.stem} ... ",
              end="", flush=True, file=sys.stderr)
        if not document.is_file():
            result = CaseResult(id=key["id"], name=key["name"],
                                layout=key.get("layout", ""))
            result.error = f"No document at {document.name} — run tools/build_golden.py"
            report.results.append(result)
            print("no document", file=sys.stderr)
            continue
        try:
            envelope = extract(
                document, llm=llm, config=config,
                requisition_id="GOLDEN", candidate_id=f"GOLD-{key['id']}",
                root=ROOT,
            )
        except (RecruitError, Exception) as error:  # noqa: BLE001
            # One document that blows up must not lose the other seven. A
            # partial measurement with a named failure is worth more than no
            # measurement at all.
            result = CaseResult(id=key["id"], name=key["name"],
                                layout=key.get("layout", ""))
            result.error = f"{type(error).__name__}: {error}"
            report.results.append(result)
            print(f"FAILED ({type(error).__name__})", file=sys.stderr)
            continue
        scored = score_case(key, envelope)
        report.results.append(scored)
        print(f"{scored.passed}/{scored.total}", file=sys.stderr)

    return report


# -- CLI ----------------------------------------------------------------------
def _print(report: Report) -> None:
    print()
    print(f"  Model     {report.model_id}")
    print(f"  Accuracy  {report.accuracy:.1%}  "
          f"({report.checks_passed}/{report.checks_total} checks)")
    print()
    print("  Per check")
    for name in sorted({k for r in report.results for k in r.checks}):
        rate = report.rate(name)
        if rate is not None:
            bar = "#" * round(rate * 20)
            print(f"    {name:<20} {rate:6.1%}  {bar}")
    print()
    print("  Per document")
    for r in report.results:
        if r.error:
            print(f"    {r.id} {r.name:<24} FAILED  {r.error}")
            continue
        note = f"  missed: {', '.join(r.failures)}" if r.failures else ""
        print(f"    {r.id} {r.name:<24} {r.passed}/{r.total}"
              f"  skills {r.skills_found}/{r.skills_expected}"
              f"  roles {r.roles_matched}/{r.roles_expected}{note}")

    if report.leaks:
        print()
        print("  PROTECTED DATA WAS EXTRACTED — this is a defect, not a score:")
        for case_id, values in report.leaks:
            print(f"    {case_id}: {', '.join(values)}")

    print()
    print("  " + "-" * 68)
    print("  These are 8 synthetic documents, not a sample of real resumes.")
    print("  The figure describes how this system handles THESE documents.")
    print("  Quote it with that sentence attached or do not quote it.")
    print("  " + "-" * 68)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m recruit.golden",
        description="Measure extraction accuracy against the golden set.")
    parser.add_argument("--provider", default="fake",
                        choices=("fake", "ollama", "anthropic"),
                        help="Which model to measure. Default: fake (a smoke test).")
    parser.add_argument("--model", help="Model name, for ollama or anthropic.")
    parser.add_argument("--limit", type=int, help="Score only the first N cases.")
    parser.add_argument("--json", dest="json_path",
                        help="Also write the full report to this file.")
    args = parser.parse_args(argv)

    try:
        from .config import OrganizationConfig
        config = OrganizationConfig.load()
    except Exception:  # noqa: BLE001
        config = None

    if args.provider == "fake":
        from .adapters.llm import FakeLLM
        fixture = ROOT / "tests" / "fixtures" / "wf03_fake_results.json"
        llm = FakeLLM(json.loads(fixture.read_text(encoding="utf-8")))
        print("  NOTE: the fake model returns one fixed answer, so this run only\n"
              "        proves the harness works. It is not a measurement of\n"
              "        anything. Use --provider ollama for a real one.",
              file=sys.stderr)
    elif args.provider == "ollama":
        from .adapters.llm import OllamaLLM
        llm = OllamaLLM(model=args.model or "llama3.1:8b")
    else:
        from .adapters.llm import AnthropicLLM
        llm = AnthropicLLM(model=args.model) if args.model else AnthropicLLM()

    report = run(llm, config=config, limit=args.limit)
    _print(report)

    if args.json_path:
        Path(args.json_path).write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        print(f"  Written to {args.json_path}")

    # Leaking a protected characteristic is a defect rather than a low score,
    # so it is the one thing that makes this command fail.
    return 1 if report.leaks else 0


if __name__ == "__main__":
    raise SystemExit(main())
