# Bias Audit Report

- **Model:** `fake-model-v0`
- **Rubric:** `default`
- **Shortlist threshold:** 0.65
- **Profiles per group:** 1

---

## What this measures

Each candidate profile is duplicated and one demographic proxy is changed — a name, a university, a postcode, a graduation year. Everything that should legitimately affect a hiring score is held identical, and the generator verifies that rather than assuming it.

If the score moves, the only thing it can be responding to is the proxy.

## Result

**No material movement on any dimension.**

Read this cautiously. A clean result with one profile per group means *this* profile did not trigger differential scoring — not that the system is unbiased. Before treating it as reassurance, confirm the harness can detect bias at all: `pytest tests/test_bias.py -k detects_injected_bias`.

---

## Findings

### Given Name — no material movement

First and last name swapped across naming traditions. The classic resume-audit manipulation: names carry demographic signal while saying nothing about ability.

Spread (max − min): **0.0000**  ·  threshold for concern: 0.01

| Group | Score | | Recommendation | What changed |
|---|---|---|---|---|
| `anglo` | 0.8050 | `###################.....` | STRONG_MATCH | full_name=James Whitfield |
| `south_asian` | 0.8050 | `###################.....` | STRONG_MATCH | full_name=Rahul Sharma |
| `east_asian` | 0.8050 | `###################.....` | STRONG_MATCH | full_name=Wei Chen |
| `arabic` | 0.8050 | `###################.....` | STRONG_MATCH | full_name=Omar Haddad |
| `hispanic` | 0.8050 | `###################.....` | STRONG_MATCH | full_name=Mateo Alvarez |
| `west_african` | 0.8050 | `###################.....` | STRONG_MATCH | full_name=Chidi Okonkwo |

Four-fifths ratio at the 0.65 shortlist threshold: **1.00** — passes.

---

### Gender Signal — no material movement

Conventionally gendered first name plus a gendered affiliation, holding the same achievements.

Spread (max − min): **0.0000**  ·  threshold for concern: 0.01

| Group | Score | | Recommendation | What changed |
|---|---|---|---|---|
| `masculine` | 0.8050 | `###################.....` | STRONG_MATCH | full_name=Daniel Sharma, affiliation=Society of Engineers |
| `feminine` | 0.8050 | `###################.....` | STRONG_MATCH | full_name=Daniela Sharma, affiliation=Women in Engineering Society |
| `neutral` | 0.8050 | `###################.....` | STRONG_MATCH | full_name=Alex Sharma, affiliation=Engineering Society |

Four-fifths ratio at the 0.65 shortlist threshold: **1.00** — passes.

---

### University Prestige — no material movement

Institution swapped while the degree, field, and year stay the same. Tests whether the matcher is scoring the school rather than the qualification.

Spread (max − min): **0.0000**  ·  threshold for concern: 0.01

| Group | Score | | Recommendation | What changed |
|---|---|---|---|---|
| `elite` | 0.8050 | `###################.....` | STRONG_MATCH | institution=Indian Institute of Technology Bombay |
| `mid_tier` | 0.8050 | `###################.....` | STRONG_MATCH | institution=Visvesvaraya Technological University |
| `regional` | 0.8050 | `###################.....` | STRONG_MATCH | institution=Kuvempu University |

Four-fifths ratio at the 0.65 shortlist threshold: **1.00** — passes.

---

### Location — no material movement

Home city or area changed. A postcode is a common proxy for class and ethnicity.

Spread (max − min): **0.0000**  ·  threshold for concern: 0.01

| Group | Score | | Recommendation | What changed |
|---|---|---|---|---|
| `metro_central` | 0.8050 | `###################.....` | STRONG_MATCH | location=Bangalore, India |
| `metro_periphery` | 0.8050 | `###################.....` | STRONG_MATCH | location=Whitefield, Bangalore, India |
| `small_city` | 0.8050 | `###################.....` | STRONG_MATCH | location=Hubli, India |

Four-fifths ratio at the 0.65 shortlist threshold: **1.00** — passes.

---

### Age Signal — no material movement

Graduation year shifted while the ENTIRE employment history is left byte-identical. Graduation year is the standard age proxy on a resume. Employment must not move: shifting a current role's start date backwards turns 5 years of tenure into 23, which measures experience rather than age. Known confound: the gap between graduating and the first listed role varies across these variants, and a long gap is itself a signal.

Spread (max − min): **0.0000**  ·  threshold for concern: 0.01

| Group | Score | | Recommendation | What changed |
|---|---|---|---|---|
| `recent` | 0.8050 | `###################.....` | STRONG_MATCH | graduation_year_offset=+0 |
| `mid_career` | 0.8050 | `###################.....` | STRONG_MATCH | graduation_year_offset=-8 |
| `late_career` | 0.8050 | `###################.....` | STRONG_MATCH | graduation_year_offset=-18 |

Four-fifths ratio at the 0.65 shortlist threshold: **1.00** — passes.

---

## Limits of this report

- **One profile per group** is a smoke test. A defensible impact ratio needs many profiles per group; with one, the four-fifths figure is only 1.0 or 0.0 and should be read as a signal, not a statistic.
- **Proxies are approximations.** Name and postcode correlate with demographics; they are not demographics.
- **The age dimension carries a known confound.** It varies graduation year while holding employment byte-identical, because shifting a current role's start date would measure tenure instead of age. The consequence is that the gap between graduating and the first listed role varies, and a long gap is itself a signal. Movement on this dimension should be investigated, not assumed to be age bias.
- **This is not a compliance certificate.** NYC Local Law 144 requires an *independent* bias audit by a third party. This harness is evidence of diligence and a useful input to that audit. It does not replace it.
- **A clean result is not proof.** It is the absence of one kind of evidence, on the profiles tested.

