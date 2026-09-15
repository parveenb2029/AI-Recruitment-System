"""Bake the two extractions the public demo replays.

    python tools/bake_demo.py

**Why bake rather than call a model when somebody visits.** The demo page is
the first thing a stranger sees, and a live model call there is three separate
ways to look broken: it is slow, it needs Ollama running or a paid key, and it
is non-deterministic — so the one screen an employer looks at could produce a
different, worse answer than the one that was checked. A replayed extraction is
instant, free, offline, and identical every time. The page says plainly that it
is a recorded run, because a demo that implies live inference when there is
none is the sort of dishonesty this project exists not to commit.

**Why two of them.** One clean extraction shows that the system reads a resume
and can point at where every detail came from. That is the comprehension
moment. But it is only half the product, and the weaker half — anything can
claim to read a CV.

The second is the real one. In September 2026 a 3B model running on the
operator's own laptop read `rahul.sharma@email.com` off the page and wrote
`rahl.sharma@email.com` into the record: one character, in the only field
anybody would use to contact that candidate. It passed every check the system
had, because the model had quoted the correct line as its evidence — the
citation was honest and the extraction was wrong, and nothing was looking at
the gap between them. VR-05 was written for exactly that, and the second
extraction here reproduces it: the same mangled address, the same correct
citation, run through the same validator. Nothing is simulated. The finding on
the demo page is `validate.py` genuinely catching it.

So the page shows a system that reads a document, and a system that catches
itself misreading one. The second is what a person is actually buying.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from recruit.adapters.llm import FakeLLM  # noqa: E402
from recruit.config import OrganizationConfig  # noqa: E402
from recruit.extract import extract  # noqa: E402
from recruit.ingest import load as load_document  # noqa: E402
from recruit.validate import validate as run_validation  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "wf03_fake_results.json"
RESUME = ROOT / "samples" / "Rahul_Sharma_Resume.pdf"
OUT = ROOT / "samples" / "demo"

# The exact character the model dropped. Kept as a pair rather than a string
# edit so that the two halves cannot drift apart in a later edit.
MISREAD = ("rahul.sharma@email.com", "rahl.sharma@email.com")


def _load_config():
    try:
        return OrganizationConfig.load()
    except Exception:  # noqa: BLE001 - the example config is enough to bake with
        return OrganizationConfig.load(ROOT / "config" / "organization.example.yaml")


def _bake(results: dict, *, candidate_id: str, config) -> dict:
    """Run the real pipeline and return the envelope a reviewer would see."""
    envelope = extract(
        RESUME, llm=FakeLLM(results), config=config,
        requisition_id="REQ-2026-0142", candidate_id=candidate_id, root=ROOT,
    )
    document = load_document(RESUME)

    report = run_validation(envelope, source_text=document.text, config=config)
    if not report.is_valid:
        envelope["status"] = "PARTIAL"
        envelope["human_review_required"] = True
    envelope["flags"] = sorted(set(envelope.get("flags", []) + report.flags))
    # `summary()` is exactly what the console stores on a real run, so the demo
    # renders the same structure the review screen does rather than a shape
    # invented for it.
    envelope["validation"] = report.summary()
    return envelope


def main() -> int:
    if not RESUME.is_file():
        print(f"Missing sample resume: {RESUME}", file=sys.stderr)
        return 1

    config = _load_config()
    clean_results = json.loads(FIXTURE.read_text(encoding="utf-8"))

    # -- 1. the extraction that checked out --------------------------------
    clean = _bake(clean_results, candidate_id="CAN-88421", config=config)

    # -- 2. the extraction that did not ------------------------------------
    # One character removed from the email VALUE. The evidence is left exactly
    # as it was, still quoting the correct line, because that is what actually
    # happened: the model read the address correctly and then wrote something
    # else into the field.
    misread_results = copy.deepcopy(clean_results)
    correct, wrong = MISREAD
    personal = misread_results["profile"]["personal_info"]
    if personal.get("email") != correct:
        print(f"Fixture email is {personal.get('email')!r}, expected {correct!r}. "
              "The demo depends on that exact value; fix one or the other.",
              file=sys.stderr)
        return 1
    personal["email"] = wrong

    misread = _bake(misread_results, candidate_id="CAN-88422", config=config)

    # The whole point of baking this one. If the validator stops catching it,
    # the demo would quietly become a page showing a wrong answer with a green
    # tick — which is the exact failure the page exists to dramatise.
    findings = misread.get("validation", {}).get("findings", [])
    caught = [f for f in findings if f.get("rule") == "VR-05"]
    if not caught:
        print("VR-05 did not fire on the misread email. Refusing to bake a demo "
              "that claims the system catches something it no longer catches.",
              file=sys.stderr)
        print(f"  findings: {[f.get('rule') for f in findings]}", file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    for name, envelope in (("clean.json", clean), ("misread.json", misread)):
        path = OUT / name
        path.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
        print(f"  baked    {path.relative_to(ROOT)}  "
              f"status={envelope['status']}  "
              f"findings={len(envelope.get('validation', {}).get('findings', []))}")

    print(f"  VR-05    fired {len(caught)} time(s) on the misread address — "
          "the demo's central claim is true today.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
