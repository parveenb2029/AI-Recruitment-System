"""Run the bias audit and write a publishable report.

    python -m recruit.bias_audit --fake
    python -m recruit.bias_audit --fake --out docs/compliance/bias_audit.md
    python -m recruit.bias_audit --self-test

`--self-test` injects a known bias and asserts the harness detects it. Run that
before trusting a clean report: a harness that cannot find bias will always say
there is none.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .bias.audit import run_audit
from .bias.perturb import PERTURBATIONS
from .bias.report import render_markdown
from .errors import RecruitError

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_PROFILE = ROOT / "samples" / "Rahul_Sharma.json"
DEFAULT_JOB = ROOT / "samples" / "Software_Engineer.json"
FIXTURE = ROOT / "tests" / "fixtures" / "wf04_fake_results.json"


def _load_config():
    try:
        from .config import OrganizationConfig
        return OrganizationConfig.load()
    except Exception:  # noqa: BLE001
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m recruit.bias_audit",
                                     description=__doc__)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--job", type=Path, default=DEFAULT_JOB)
    parser.add_argument("--fake", action="store_true",
                        help="Use the canned model. No API key, no cost.")
    parser.add_argument("--dimensions", nargs="*", choices=sorted(PERTURBATIONS),
                        help="Limit to these dimensions. Defaults to all.")
    parser.add_argument("--scheme", help="Rubric scheme id.")
    parser.add_argument("--out", type=Path, help="Write the Markdown report here.")
    parser.add_argument("--json", type=Path, help="Also write the raw result as JSON.")
    parser.add_argument("--self-test", action="store_true",
                        help="Inject a known bias and assert it is detected.")
    parser.add_argument("--fail-on-bias", action="store_true",
                        help="Exit non-zero when a dimension moves. For CI.")
    args = parser.parse_args(argv)

    try:
        profile = json.loads(args.profile.read_text(encoding="utf-8"))
        job = json.loads(args.job.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"Could not read inputs: {error}", file=sys.stderr)
        return 2

    config = _load_config()

    if args.self_test:
        return _self_test(profile, job, config)

    if args.fake:
        if not FIXTURE.is_file():
            print(f"Missing fixture: {FIXTURE}", file=sys.stderr)
            return 2
        from .adapters.llm import FakeLLM
        def factory():
            return FakeLLM(FIXTURE)
    else:
        from .adapters.llm import build_llm
        def factory():
            return build_llm(config)

    try:
        result = run_audit(profile, job, llm_factory=factory, config=config,
                           dimensions=args.dimensions, scheme=args.scheme, root=ROOT)
    except (RecruitError, AssertionError) as error:
        print(f"Audit could not run: {error}", file=sys.stderr)
        return 1

    markdown = render_markdown(result)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(markdown + "\n", encoding="utf-8")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result.summary(), indent=2) + "\n",
                             encoding="utf-8")

    print(f"  model            {result.model_id}")
    print(f"  rubric           {result.scheme}")
    print(f"  dimensions       {len(result.findings)}")
    print()
    for finding in sorted(result.findings, key=lambda f: -f.spread):
        marker = "MOVED" if finding.is_material else "     "
        print(f"  {marker}  {finding.dimension:<22} spread {finding.spread:.4f}")
        if finding.is_material:
            leaking = {k: v for k, v in finding.component_spreads().items() if v > 0.01}
            for name, spread in sorted(leaking.items(), key=lambda kv: -kv[1]):
                print(f"           via {name}: {spread:.4f}")
            print(f"           best {finding.best_group} / worst {finding.worst_group}")
    print()
    if result.passed:
        print("  RESULT: no material movement.")
        print("  Before treating that as reassurance, prove the harness works:")
        print("      python -m recruit.bias_audit --self-test")
    else:
        print(f"  RESULT: {len(result.material_findings)} dimension(s) moved. "
              "The matcher is reading a signal it must not.")
    if args.out:
        print(f"\n  report written   {args.out}")

    if args.fail_on_bias and not result.passed:
        return 1
    return 0


def _self_test(profile, job, config) -> int:
    """Inject a known bias and assert the harness catches it."""
    from .bias.fakes import BiasedFakeLLM

    penalty = 0.30
    print("  Injecting a known bias: penalising one name group by "
          f"{penalty} on domain_match.\n")
    result = run_audit(
        profile, job,
        llm_factory=lambda: BiasedFakeLLM(FIXTURE, penalise={"Okonkwo": penalty}),
        config=config, dimensions=["given_name"], root=ROOT,
    )
    finding = result.findings[0]
    detected = finding.is_material and finding.worst_group == "west_african"

    print(f"  spread detected  {finding.spread:.4f}")
    print(f"  worst group      {finding.worst_group}")
    print(f"  leaking via      {finding.component_spreads()}")
    print()
    if detected:
        print("  SELF-TEST PASSED — the harness detects injected bias.")
        print("  A clean report from this harness is therefore meaningful.")
        return 0
    print("  SELF-TEST FAILED — the harness did NOT detect a bias that is "
          "definitely present.", file=sys.stderr)
    print("  Do not trust any clean report until this passes.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
