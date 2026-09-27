"""Turn the golden cases into documents, and their ground truth into JSON.

    python tools/build_golden.py

**One source, two outputs.** Each case in `golden/cases/` is rendered into a
PDF *and* into the expected answer, from the same YAML, in the same run. That is
the whole design. A measurement set where the document and the answer key are
maintained separately drifts within a month, and a drifted answer key does not
fail loudly — it quietly reports the model getting things wrong that it got
right, or right that it got wrong, and every number after that is noise.

**Why PDFs rather than text files.** Half of what this measures is layout.
Columns interleave when a PDF is flattened, table cells run together, dense
pages wrap mid-value. Handing the extractor clean text would measure a problem
nobody has, and would report an accuracy figure far higher than the real one.
So each case names a `layout:` and gets a document built that way.

**What `shown_as` is for.** The truth holds ISO dates, because that is what the
extractor must produce. The document has to show what a human would write —
"Apr 2021 - Mar 2023" — so each dated entry carries a `shown_as` giving the
printed form. Deriving one from the other automatically would hide exactly the
failure this set exists to catch: a model that reads the page correctly and
converts the date wrongly.

The documents are **committed**, so that a number quoted in the README was
measured against bytes anybody can inspect, rather than against whatever this
script happened to produce that day.
"""

from __future__ import annotations

import html
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "golden" / "cases"
DOCS = ROOT / "golden" / "documents"
EXPECTED = ROOT / "golden" / "expected"

# The protected characteristics case volunteers these in the document. They are
# rendered so that refusing to extract them can be measured; the labels live
# here rather than in the case file so the case stays a statement of truth.
PROTECTED_LABELS = {
    "1994-03-12": "Date of Birth",
    "Married": "Marital Status",
    "Female": "Gender",
    "Hindu": "Religion",
}

BASE_CSS = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: 'Liberation Sans', Arial, sans-serif; color: #111; }
h1 { font-size: 19pt; margin: 0 0 2pt; letter-spacing: .4pt; }
.contact { font-size: 9.5pt; color: #333; margin: 0 0 12pt; }
h2 { font-size: 11pt; margin: 14pt 0 5pt; border-bottom: 1px solid #999;
     padding-bottom: 2pt; text-transform: uppercase; letter-spacing: .6pt; }
.role { margin: 0 0 9pt; }
.role .line1 { font-size: 10.5pt; font-weight: bold; }
.role .line2 { font-size: 9.5pt; color: #444; }
.role ul { margin: 3pt 0 0 14pt; padding: 0; font-size: 9.5pt; }
p, li { line-height: 1.35; }
"""

DENSE_CSS = """
@page { size: A4; margin: 12mm 12mm; }
body { font-size: 8.5pt; }
h1 { font-size: 15pt; }
h2 { font-size: 9.5pt; margin: 8pt 0 3pt; }
.role { margin: 0 0 4pt; }
.role .line1 { font-size: 9pt; }
.role .line2 { font-size: 8pt; }
"""

TWO_COLUMN_CSS = """
.wrap { display: table; width: 100%; }
.side { display: table-cell; width: 32%; padding-right: 10mm;
        border-right: 1px solid #bbb; vertical-align: top; font-size: 9pt; }
.main { display: table-cell; vertical-align: top; padding-left: 8mm; }
.side h2 { font-size: 9.5pt; }
"""

TABLE_CSS = """
table.skills { border-collapse: collapse; width: 100%; font-size: 9.5pt; }
table.skills td { border: 1px solid #999; padding: 4pt 7pt; }
"""


def _contact(t: dict) -> str:
    p = t["personal_info"]
    bits = [p.get("email"), p.get("phone"), p.get("location")]
    return " | ".join(html.escape(str(b)) for b in bits if b)


# Responsibility lines, so the documents are the length of real CVs rather than
# skeletons. A 250-character document is far easier to read correctly than a
# 3,000-character one, and measuring against skeletons would report an accuracy
# the system does not have.
#
# **Every line is built only from facts the case already states** — the job
# title, the employer, and skills listed in the truth. Nothing invents a
# figure, a client or a technology, because a document containing claims the
# answer key does not know about would score correct extractions as
# hallucinations.
BULLET_SHAPES = (
    "Built and maintained {skill} services supporting day-to-day operations at {company}.",
    "Worked across the team on {skill} and {skill2}, from design through to release.",
    "Reviewed changes, wrote documentation and supported colleagues using {skill}.",
    "Improved reliability of existing {skill} systems and reduced manual work.",
)


def _bullets(job: dict, skills: list[str], offset: int) -> str:
    if not skills:
        return ""
    lines = []
    for n in range(2):
        shape = BULLET_SHAPES[(offset + n) % len(BULLET_SHAPES)]
        lines.append("<li>" + html.escape(shape.format(
            skill=skills[(offset + n) % len(skills)],
            skill2=skills[(offset + n + 1) % len(skills)],
            company=job["company"],
        )) + "</li>")
    return "<ul>" + "".join(lines) + "</ul>"


def _summary_html(t: dict) -> str:
    """The paragraph almost every CV opens with, and a model must not mine
    for employment history — the dates in it are deliberately absent."""
    jobs = t.get("experience") or []
    if not jobs:
        return ""
    skills = t.get("skills") or []
    return (
        "<h2>Profile</h2><p style='font-size:9.5pt'>"
        f"{html.escape(jobs[0]['title'])} with experience across "
        f"{html.escape(', '.join(skills[:3]))}. Comfortable working with "
        "colleagues across teams, and used to picking up unfamiliar systems."
        "</p>"
    )


def _roles_html(t: dict) -> str:
    out = []
    skills = t.get("skills") or []
    for index, job in enumerate(t.get("experience", [])):
        out.append(
            '<div class="role">'
            f'<div class="line1">{html.escape(job["title"])} — '
            f'{html.escape(job["company"])}</div>'
            f'<div class="line2">{html.escape(job.get("shown_as", ""))}</div>'
            f'{_bullets(job, skills, index)}'
            "</div>"
        )
    return "\n".join(out)


def _education_html(t: dict) -> str:
    out = []
    for school in t.get("education", []):
        out.append(
            '<div class="role">'
            f'<div class="line1">{html.escape(school["degree"])}</div>'
            f'<div class="line2">{html.escape(school["institution"])}'
            f' — {html.escape(str(school.get("shown_as", "")))}</div>'
            "</div>"
        )
    return "\n".join(out)


def _protected_html(case: dict) -> str:
    """Render the characteristics that must never come back out.

    Written the way a CV in several countries genuinely is, because a synthetic
    version that nobody would actually produce would not test anything.
    """
    values = case.get("must_not_extract") or []
    if not values:
        return ""
    rows = "".join(
        f"<div>{html.escape(PROTECTED_LABELS.get(v, 'Detail'))}: {html.escape(v)}</div>"
        for v in values
    )
    return f'<h2>Personal Details</h2><div style="font-size:9.5pt">{rows}</div>'


def _skills_html(case: dict, t: dict) -> str:
    skills = t.get("skills", [])
    if case.get("layout") == "table_skills":
        cells = "".join(
            f"<td>{html.escape(s)}</td>" + ("</tr><tr>" if (i + 1) % 3 == 0 else "")
            for i, s in enumerate(skills)
        )
        return f'<h2>Skills</h2><table class="skills"><tr>{cells}</tr></table>'
    return f'<h2>Skills</h2><p>{html.escape(" · ".join(skills))}</p>'


def _document_html(case: dict) -> str:
    t = case["truth"]
    layout = case.get("layout", "single_column")
    css = BASE_CSS + {"dense": DENSE_CSS, "two_column": TWO_COLUMN_CSS,
                      "table_skills": TABLE_CSS}.get(layout, "")

    header = (f'<h1>{html.escape(t["personal_info"]["full_name"])}</h1>'
              f'<p class="contact">{_contact(t)}</p>')
    summary = _summary_html(t)
    experience = f"<h2>Experience</h2>{_roles_html(t)}"
    education = f"<h2>Education</h2>{_education_html(t)}"
    skills = _skills_html(case, t)
    protected = _protected_html(case)

    if layout == "two_column":
        # Contact and skills in a sidebar. When the PDF is flattened the two
        # columns interleave, which is the whole point of this case.
        body = (
            '<div class="wrap">'
            f'<div class="side"><h1>{html.escape(t["personal_info"]["full_name"])}</h1>'
            f'<p class="contact">{_contact(t)}</p>{skills}{education}</div>'
            f'<div class="main">{summary}{experience}{protected}</div>'
            "</div>"
        )
    else:
        body = header + summary + experience + education + skills + protected

    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<style>{css}</style></head><body>{body}</body></html>")


def _expected(case: dict) -> dict:
    """The answer key: truth with the presentation stripped out.

    `shown_as` describes the document, not the candidate, so it does not belong
    in something an extraction is compared against.
    """
    truth = json.loads(json.dumps(case["truth"]))  # deep copy
    for group in ("experience", "education"):
        for entry in truth.get(group, []) or []:
            entry.pop("shown_as", None)
    return {
        "id": case["id"],
        "name": case["name"],
        "layout": case.get("layout", "single_column"),
        "tests": case.get("tests", ""),
        "expect_conflict": bool(case.get("expect_conflict")),
        "must_not_extract": case.get("must_not_extract") or [],
        "truth": truth,
    }


def _render_pdf(html_text: str, destination: Path) -> None:
    with tempfile.TemporaryDirectory() as work:
        source = Path(work) / "resume.html"
        source.write_text(html_text, encoding="utf-8")
        subprocess.run(
            ["soffice", "--headless", "--convert-to", "pdf",
             "--outdir", work, str(source)],
            check=True, capture_output=True, timeout=180,
        )
        produced = Path(work) / "resume.pdf"
        if not produced.is_file():
            raise RuntimeError(f"soffice produced no PDF for {destination.name}")
        shutil.move(str(produced), destination)


def main() -> int:
    if shutil.which("soffice") is None:
        print("LibreOffice (soffice) is not installed. It renders the documents;\n"
              "without it the set cannot be rebuilt. The committed PDFs in\n"
              "golden/documents/ are usable as they are.", file=sys.stderr)
        return 1

    cases = sorted(CASES.glob("*.yaml"))
    if not cases:
        print(f"No cases in {CASES}", file=sys.stderr)
        return 1

    DOCS.mkdir(parents=True, exist_ok=True)
    EXPECTED.mkdir(parents=True, exist_ok=True)

    for path in cases:
        case = yaml.safe_load(path.read_text(encoding="utf-8"))
        stem = f"{case['id']}-{case['name']}"

        _render_pdf(_document_html(case), DOCS / f"{stem}.pdf")
        (EXPECTED / f"{stem}.json").write_text(
            json.dumps(_expected(case), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"  built    {stem}  ({case.get('layout')})")

    print(f"\n  {len(cases)} cases -> golden/documents/ and golden/expected/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
