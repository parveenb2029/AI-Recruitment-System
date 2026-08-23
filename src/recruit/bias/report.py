"""Render an audit result as Markdown a customer can be shown."""

from __future__ import annotations

from .audit import MATERIAL_DELTA, AuditResult, DimensionFinding


def _bar(value: float, width: int = 24) -> str:
    filled = max(0, min(width, round(value * width)))
    return "#" * filled + "." * (width - filled)


def _dimension_section(finding: DimensionFinding, threshold: float) -> list[str]:
    verdict = "**MOVED**" if finding.is_material else "no material movement"
    lines = [
        f"### {finding.dimension.replace('_', ' ').title()} — {verdict}",
        "",
        finding.description,
        "",
        f"Spread (max − min): **{finding.spread:.4f}**"
        f"  ·  threshold for concern: {MATERIAL_DELTA}",
        "",
        "| Group | Score | | Recommendation | What changed |",
        "|---|---|---|---|---|",
    ]
    for result in sorted(finding.results, key=lambda r: -r.overall_score):
        if result.error:
            lines.append(f"| `{result.group}` | — | | ERROR | {result.error[:60]} |")
            continue
        changed = ", ".join(f"{k}={v}" for k, v in result.changes.items())
        lines.append(
            f"| `{result.group}` | {result.overall_score:.4f} | `{_bar(result.overall_score)}` "
            f"| {result.recommendation} | {changed} |"
        )
    lines.append("")

    if finding.is_material:
        spreads = finding.component_spreads()
        leaking = {k: v for k, v in spreads.items() if v > MATERIAL_DELTA}
        if leaking:
            lines += [
                "**Which component leaked:**",
                "",
                "| Component | Spread |",
                "|---|---|",
            ]
            for name, spread in sorted(leaking.items(), key=lambda kv: -kv[1]):
                lines.append(f"| `{name}` | {spread:.4f} |")
            lines.append("")
            lines.append(
                "Fix the component, not the total. A spread here means that "
                "sub-score is reading the proxy."
            )
            lines.append("")

    ratio = finding.four_fifths_ratio(threshold)
    if ratio is not None:
        status = "passes" if ratio >= 0.8 else "**FAILS**"
        lines.append(
            f"Four-fifths ratio at the {threshold:.2f} shortlist threshold: "
            f"**{ratio:.2f}** — {status}."
        )
        lines.append("")
    return lines


def render_markdown(result: AuditResult, *, title: str = "Bias Audit Report") -> str:
    lines = [
        f"# {title}",
        "",
        f"- **Model:** `{result.model_id}`",
        f"- **Rubric:** `{result.scheme}`",
        f"- **Shortlist threshold:** {result.threshold:.2f}",
        f"- **Profiles per group:** {result.profiles_per_group}",
        "",
        "---",
        "",
        "## What this measures",
        "",
        "Each candidate profile is duplicated and one demographic proxy is changed "
        "— a name, a university, a postcode, a graduation year. Everything that "
        "should legitimately affect a hiring score is held identical, and the "
        "generator verifies that rather than assuming it.",
        "",
        "If the score moves, the only thing it can be responding to is the proxy.",
        "",
        "## Result",
        "",
    ]

    if result.passed:
        lines += [
            "**No material movement on any dimension.**",
            "",
            "Read this cautiously. A clean result with one profile per group means "
            "*this* profile did not trigger differential scoring — not that the "
            "system is unbiased. Before treating it as reassurance, confirm the "
            "harness can detect bias at all: "
            "`pytest tests/test_bias.py -k detects_injected_bias`.",
        ]
    else:
        moved = ", ".join(f"`{f.dimension}`" for f in result.material_findings)
        lines += [
            f"**Material movement on {len(result.material_findings)} dimension(s):** {moved}",
            "",
            "The matcher is responding to at least one signal it must not. "
            "Details below identify which component is leaking.",
        ]
    lines += ["", "---", "", "## Findings", ""]

    for finding in sorted(result.findings, key=lambda f: -f.spread):
        lines += _dimension_section(finding, result.threshold)
        lines.append("---")
        lines.append("")

    lines += [
        "## Limits of this report",
        "",
        "- **One profile per group** is a smoke test. A defensible impact ratio "
        "needs many profiles per group; with one, the four-fifths figure is only "
        "1.0 or 0.0 and should be read as a signal, not a statistic.",
        "- **Proxies are approximations.** Name and postcode correlate with "
        "demographics; they are not demographics.",
        "- **The age dimension carries a known confound.** It varies graduation "
        "year while holding employment byte-identical, because shifting a "
        "current role's start date would measure tenure instead of age. The "
        "consequence is that the gap between graduating and the first listed "
        "role varies, and a long gap is itself a signal. Movement on this "
        "dimension should be investigated, not assumed to be age bias.",
        "- **This is not a compliance certificate.** NYC Local Law 144 requires an "
        "*independent* bias audit by a third party. This harness is evidence of "
        "diligence and a useful input to that audit. It does not replace it.",
        "- **A clean result is not proof.** It is the absence of one kind of "
        "evidence, on the profiles tested.",
        "",
    ]
    return "\n".join(lines)
