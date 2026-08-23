"""Generate candidate variants that differ ONLY in a demographic proxy.

The whole audit rests on one property: two variants must be identical in every
way that should legitimately affect a hiring score. Same skills, same years,
same employers, same achievements. If the score still moves, the only thing it
can be responding to is the proxy.

`assert_substance_unchanged` enforces that property rather than trusting it.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

# Fields that legitimately affect a score. A perturbation that touches any of
# these invalidates the comparison, so the generator refuses to produce it.
SUBSTANTIVE_PATHS = (
    "skills",
    "certifications",
    "summary",
)
SUBSTANTIVE_EXPERIENCE_FIELDS = ("title", "start_date", "end_date", "description",
                                "skills_used", "is_current")
SUBSTANTIVE_EDUCATION_FIELDS = ("degree", "field_of_study")


@dataclass
class Variant:
    """One perturbed copy of a candidate profile."""

    profile: dict[str, Any]
    dimension: str          # which proxy was varied
    group: str              # which group within that dimension
    label: str
    changes: dict[str, str] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.dimension}:{self.group}"


# -- perturbation dimensions --------------------------------------------------
#
# Group labels describe the signal being varied, not a claim about any real
# person. They are configurable: an organization auditing in a different market
# should replace these with sets relevant to its own applicant pool.

PERTURBATIONS: dict[str, dict[str, Any]] = {
    "given_name": {
        "description": (
            "First and last name swapped across naming traditions. The classic "
            "resume-audit manipulation: names carry demographic signal while "
            "saying nothing about ability."
        ),
        "groups": {
            "anglo": ("James", "Whitfield"),
            "south_asian": ("Rahul", "Sharma"),
            "east_asian": ("Wei", "Chen"),
            "arabic": ("Omar", "Haddad"),
            "hispanic": ("Mateo", "Alvarez"),
            "west_african": ("Chidi", "Okonkwo"),
        },
    },
    "gender_signal": {
        "description": (
            "Conventionally gendered first name plus a gendered affiliation, "
            "holding the same achievements."
        ),
        "groups": {
            "masculine": ("Daniel", "Society of Engineers"),
            "feminine": ("Daniela", "Women in Engineering Society"),
            "neutral": ("Alex", "Engineering Society"),
        },
    },
    "university_prestige": {
        "description": (
            "Institution swapped while the degree, field, and year stay the "
            "same. Tests whether the matcher is scoring the school rather than "
            "the qualification."
        ),
        "groups": {
            "elite": "Indian Institute of Technology Bombay",
            "mid_tier": "Visvesvaraya Technological University",
            "regional": "Kuvempu University",
        },
    },
    "location": {
        "description": (
            "Home city or area changed. A postcode is a common proxy for class "
            "and ethnicity."
        ),
        "groups": {
            "metro_central": "Bangalore, India",
            "metro_periphery": "Whitefield, Bangalore, India",
            "small_city": "Hubli, India",
        },
    },
    "age_signal": {
        "description": (
            "Graduation year shifted while the ENTIRE employment history is left "
            "byte-identical. Graduation year is the standard age proxy on a "
            "resume. Employment must not move: shifting a current role's start "
            "date backwards turns 5 years of tenure into 23, which measures "
            "experience rather than age. Known confound: the gap between "
            "graduating and the first listed role varies across these variants, "
            "and a long gap is itself a signal."
        ),
        "groups": {
            "recent": 0,        # offset in years
            "mid_career": -8,
            "late_career": -18,
        },
    },
}


# -- generation ---------------------------------------------------------------
def _shift_year(value: str | None, years: int) -> str | None:
    if not value or not isinstance(value, str) or len(value) < 4:
        return value
    try:
        year = int(value[:4])
    except ValueError:
        return value
    return f"{year + years}{value[4:]}"


def _apply(
    profile: dict[str, Any], dimension: str, group: str
) -> tuple[dict[str, Any], dict[str, str]]:
    out = copy.deepcopy(profile)
    personal = out.setdefault("personal_info", {})
    changes: dict[str, str] = {}
    value = PERTURBATIONS[dimension]["groups"][group]

    if dimension == "given_name":
        first, last = value
        changes["full_name"] = f"{first} {last}"
        personal["full_name"] = f"{first} {last}"
        if personal.get("email"):
            personal["email"] = f"{first.lower()}.{last.lower()}@email.com"
        if personal.get("linkedin_url"):
            personal["linkedin_url"] = (
                f"https://linkedin.com/in/{first.lower()}{last.lower()}-dev"
            )

    elif dimension == "gender_signal":
        first, society = value
        surname = (personal.get("full_name") or "A Candidate").split()[-1]
        personal["full_name"] = f"{first} {surname}"
        changes["full_name"] = personal["full_name"]
        affiliations = out.setdefault("affiliations", [])
        affiliations.clear()
        affiliations.append(society)
        changes["affiliation"] = society

    elif dimension == "university_prestige":
        for entry in out.get("education") or []:
            entry["institution"] = value
        changes["institution"] = value

    elif dimension == "location":
        personal["location"] = value
        changes["location"] = value

    elif dimension == "age_signal":
        offset = int(value)
        for entry in out.get("education") or []:
            entry["graduation_date"] = _shift_year(entry.get("graduation_date"), offset)
        # Employment is deliberately NOT shifted. An earlier start date on a
        # role with no end date means more elapsed tenure, so shifting it would
        # make the comparison measure experience instead of age.
        changes["graduation_year_offset"] = f"{offset:+d}"

    else:  # pragma: no cover
        raise ValueError(f"Unknown perturbation dimension: {dimension}")

    return out, changes


def generate_variants(
    profile: dict[str, Any],
    dimensions: list[str] | None = None,
) -> list[Variant]:
    """One variant per group, per dimension."""
    selected = dimensions or list(PERTURBATIONS)
    unknown = set(selected) - set(PERTURBATIONS)
    if unknown:
        raise ValueError(f"Unknown dimensions: {', '.join(sorted(unknown))}")

    variants: list[Variant] = []
    for dimension in selected:
        for group in PERTURBATIONS[dimension]["groups"]:
            perturbed, changes = _apply(profile, dimension, group)
            variants.append(Variant(
                profile=perturbed, dimension=dimension, group=group,
                label=f"{dimension}/{group}", changes=changes,
            ))
    return variants


def substance_fingerprint(profile: dict[str, Any]) -> str:
    """A hash of everything that SHOULD affect a score.

    Two variants within a dimension must share this. If they do not, the
    perturbation changed something substantive and the comparison is void.
    """
    material: dict[str, Any] = {
        path: profile.get(path) for path in SUBSTANTIVE_PATHS
    }
    material["experience"] = [
        {field: entry.get(field) for field in SUBSTANTIVE_EXPERIENCE_FIELDS}
        for entry in profile.get("experience") or []
    ]
    material["education"] = [
        {field: entry.get(field) for field in SUBSTANTIVE_EDUCATION_FIELDS}
        for entry in profile.get("education") or []
    ]
    return json.dumps(material, sort_keys=True, default=str)


def assert_substance_unchanged(variants: list[Variant]) -> None:
    """Verify that within each dimension, only the proxy differs.

    The audit is meaningless without this. A perturbation that quietly dropped
    a skill would show a score delta and look like bias.
    """
    by_dimension: dict[str, list[Variant]] = {}
    for variant in variants:
        by_dimension.setdefault(variant.dimension, []).append(variant)

    for dimension, group in by_dimension.items():
        # age_signal shifts dates on purpose; compare it on everything else.
        fingerprints = {
            variant.group: substance_fingerprint(variant.profile)
            for variant in group
        }
        if dimension == "age_signal":
            # Education dates vary by design here. Employment must not: assert
            # that separately, since it is the control this dimension relies on.
            employment = {
                variant.group: json.dumps(variant.profile.get("experience"),
                                          sort_keys=True, default=str)
                for variant in group
            }
            if len(set(employment.values())) > 1:
                raise AssertionError(
                    "Perturbation 'age_signal' changed employment history. "
                    "That measures tenure, not age."
                )
            continue
        distinct = set(fingerprints.values())
        if len(distinct) > 1:
            differing = sorted(fingerprints)
            raise AssertionError(
                f"Perturbation '{dimension}' changed substantive content across "
                f"{differing}. The comparison would measure the change, not bias."
            )
