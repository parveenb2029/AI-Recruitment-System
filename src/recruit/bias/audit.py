"""Run the matcher across perturbed variants and measure what moved.

Two measures, because they answer different questions:

- **Score delta** — does the number move at all when only a proxy changes? This
  is disparate *treatment*, and any movement is a defect.
- **Four-fifths rule** — do groups pass the shortlist threshold at comparable
  rates? This is disparate *impact*, the EEOC's rule of thumb, and it can fail
  even when individual deltas look small.

Per-component deltas matter more than the overall number: knowing that
`domain_match` leaks the university name tells you what to fix. Knowing only
that the total moved does not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from ..match import match
from .perturb import assert_substance_unchanged, generate_variants

# Any movement above this when only a proxy changed is treated as a real signal
# rather than noise. Deliberately tight: this is a defect threshold, not a
# tolerance.
MATERIAL_DELTA = 0.01

# EEOC four-fifths rule: the least-selected group must be selected at >= 80% of
# the most-selected group's rate.
FOUR_FIFTHS = 0.80


@dataclass
class GroupResult:
    dimension: str
    group: str
    label: str
    overall_score: float
    recommendation: str
    components: dict[str, float]
    changes: dict[str, str] = field(default_factory=dict)
    error: str | None = None


@dataclass
class DimensionFinding:
    dimension: str
    description: str
    results: list[GroupResult]
    baseline_score: float

    @property
    def scores(self) -> dict[str, float]:
        return {r.group: r.overall_score for r in self.results if r.error is None}

    @property
    def spread(self) -> float:
        values = list(self.scores.values())
        return round(max(values) - min(values), 6) if values else 0.0

    @property
    def is_material(self) -> bool:
        return self.spread > MATERIAL_DELTA

    @property
    def best_group(self) -> str | None:
        scores = self.scores
        return max(scores, key=scores.get) if scores else None

    @property
    def worst_group(self) -> str | None:
        scores = self.scores
        return min(scores, key=scores.get) if scores else None

    def component_spreads(self) -> dict[str, float]:
        """Which sub-score is leaking. This is what makes a finding fixable."""
        names: set[str] = set()
        for result in self.results:
            names.update(result.components)
        spreads: dict[str, float] = {}
        for name in sorted(names):
            values = [r.components[name] for r in self.results
                      if r.error is None and name in r.components]
            if values:
                spreads[name] = round(max(values) - min(values), 6)
        return spreads

    def selection_rates(self, threshold: float) -> dict[str, float]:
        return {group: (1.0 if score >= threshold else 0.0)
                for group, score in self.scores.items()}

    def four_fifths_ratio(self, threshold: float) -> float | None:
        """Selection rate of the worst group over the best.

        With one profile per group this is 1.0 or 0.0 — a smoke signal, not a
        statistic. A defensible impact ratio needs many profiles per group;
        `run_audit` says so in the report rather than implying otherwise.
        """
        rates = self.selection_rates(threshold)
        if not rates:
            return None
        best = max(rates.values())
        if best == 0:
            return None
        return round(min(rates.values()) / best, 4)


@dataclass
class AuditResult:
    findings: list[DimensionFinding]
    threshold: float
    profiles_per_group: int
    model_id: str
    scheme: str

    @property
    def material_findings(self) -> list[DimensionFinding]:
        return [f for f in self.findings if f.is_material]

    @property
    def passed(self) -> bool:
        return not self.material_findings

    def summary(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "model_id": self.model_id,
            "scheme": self.scheme,
            "shortlist_threshold": self.threshold,
            "profiles_per_group": self.profiles_per_group,
            "material_delta_threshold": MATERIAL_DELTA,
            "dimensions": [
                {
                    "dimension": finding.dimension,
                    "spread": finding.spread,
                    "material": finding.is_material,
                    "best_group": finding.best_group,
                    "worst_group": finding.worst_group,
                    "scores": finding.scores,
                    "component_spreads": finding.component_spreads(),
                    "four_fifths_ratio": finding.four_fifths_ratio(self.threshold),
                }
                for finding in self.findings
            ],
        }


def run_audit(
    profile: dict[str, Any],
    job_description: dict[str, Any],
    *,
    llm_factory,
    config: Any | None = None,
    dimensions: list[str] | None = None,
    scheme: str | None = None,
    root: Any = None,
) -> AuditResult:
    """Score every variant and compare.

    `llm_factory` is a zero-argument callable returning a fresh adapter, so each
    variant gets an independent call rather than a shared, possibly stateful one.
    """
    variants = generate_variants(profile, dimensions)
    # Refuse to report on a comparison that is not actually controlled.
    assert_substance_unchanged(variants)

    threshold = 0.65
    if config is not None:
        threshold = float(config.get("matching.recommendation_bands.match_min", 0.65))

    baseline_envelope = match(profile, job_description, llm=llm_factory(),
                              config=config, scheme=scheme, root=root)
    baseline = baseline_envelope["results"]["overall_score"]
    model_id = baseline_envelope["model_id"]
    active_scheme = baseline_envelope["results"]["weighting"]["scheme_id"]

    by_dimension: dict[str, list[GroupResult]] = {}
    for variant in variants:
        try:
            envelope = match(variant.profile, job_description, llm=llm_factory(),
                             config=config, scheme=scheme, root=root)
            results = envelope["results"]
            group_result = GroupResult(
                dimension=variant.dimension, group=variant.group, label=variant.label,
                overall_score=results["overall_score"],
                recommendation=results["recommendation"],
                components={c["component_id"]: c["raw_score"]
                            for c in results["components"]},
                changes=variant.changes,
            )
        except Exception as error:  # noqa: BLE001 - one bad variant must not
            # abort the audit; a partial report is more useful than none.
            group_result = GroupResult(
                dimension=variant.dimension, group=variant.group, label=variant.label,
                overall_score=0.0, recommendation="ERROR", components={},
                changes=variant.changes, error=str(error),
            )
        by_dimension.setdefault(variant.dimension, []).append(group_result)

    from .perturb import PERTURBATIONS
    findings = [
        DimensionFinding(
            dimension=dimension,
            description=PERTURBATIONS[dimension]["description"],
            results=results,
            baseline_score=baseline,
        )
        for dimension, results in by_dimension.items()
    ]

    return AuditResult(
        findings=findings, threshold=threshold, profiles_per_group=1,
        model_id=model_id, scheme=active_scheme,
    )


def mean_absolute_delta(finding: DimensionFinding) -> float:
    """Average distance from the dimension's own mean. Useful when one group is
    an outlier and max-minus-min would overstate the general picture."""
    values = list(finding.scores.values())
    if not values:
        return 0.0
    centre = mean(values)
    return round(mean(abs(v - centre) for v in values), 6)
