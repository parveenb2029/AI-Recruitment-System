# CLAUDE.md — AI Recruitment System

Project context for AI coding sessions. Read this first, every session.

---

## What this project is

An AI-assisted recruitment pipeline: resume in, ranked and evidence-cited shortlist
out, with a human reviewing every decision that affects a candidate.

**Current state (2026-08-22): documentation blueprint, no application code.**
136 files, 112 of them Markdown. The two Python files under `tools/legacy/` are
document generators — they wrote the docs, they do not run the pipeline.

**Target: a working single-tenant product that ships**, not a specification for
someone else to implement. Estimated 4–6 months of focused solo work.

---

## Scope decision — read before proposing work

**Build WF-03 (extraction) + WF-04 (matching) + the review console. Nothing else.**

WF-01, 02, 05, 06, 07, and 08 are workflow and record-keeping that an existing ATS
already does adequately. They stay documented and unbuilt for v1. The commercial
core is extraction, matching, and the review screen.

Also cut from v1: Zapier, Make.com, Google Drive intake, SharePoint as primary
store, multi-language locale packs, and the entire 2027 roadmap.

If a session drifts into building a cut workflow, stop and flag it.

---

## Pinned stack

Decided once. Do not re-choose these per session.

| Layer | Choice |
|-------|--------|
| Language | Python 3.12, `uv` for deps, `ruff` for lint+format, `pytest` |
| Models | Pydantic v2 |
| API | FastAPI |
| Database | Postgres 16, SQLAlchemy 2.x, Alembic migrations from day one |
| Documents | `pypdf`, `python-docx`, Tesseract OCR fallback |
| Evidence check | `rapidfuzz` |
| LLM | Adapter interface; **native structured-output / tool-calling mode only** |
| Review console | FastAPI + Jinja + HTMX (server-rendered; React only if highlighting demands it) |
| Packaging | Docker Compose |

---

## Hard rules

1. **Never run `tools/legacy/generate.py`.** It overwrites the entire tree from a
   hardcoded path. Docs are hand-maintained from the initial commit onward. The
   root-level `generate.py` and `_create_docx_samples.py` are inert stubs that
   exit with an explanation; delete them once the initial commit exists.
2. **Never ask an LLM to "return JSON".** Use the provider's native structured
   output. If that removes the repair-prompt loop the specs describe, note the
   simplification here.
3. **Never produce a single opaque fit score.** The match score is decomposed into
   components (must-have coverage, experience band, domain match), each evidenced,
   combined arithmetically **in our code** with weights from config. This is what
   makes a rejection explainable if challenged.
4. **The audit log is append-only.** No UPDATE or DELETE path in code. Every row
   carries `workflow_run_id`, `prompt_version`, `model_id`, actor, timestamp,
   content hash (BR-05).
5. **No real candidate data in the repo.** Synthetic, or consented and anonymized.
6. **Nothing is "done" until it has been run.** Execute the acceptance command and
   paste real terminal output.
7. **No organization-specific value outside `config/`.** No company name, email,
   domain, retention period, SLA, or scoring weight hardcoded anywhere else.
   `python tools/check_branding.py` enforces this; run it in CI.
8. **Two kinds of `{{placeholder}}`.** `{{org.*}}`, `{{contact.*}}`,
   `{{matching.*}}` and friends are **build-time** and resolved by
   `tools/render_docs.py`. `{{candidate_id}}`, `{{source_content}}` and friends are
   **runtime** prompt variables the orchestrator fills per run — the renderer
   deliberately leaves them alone. Do not conflate them.

---

## Known defects in the existing docs — do not propagate

The documentation was template-expanded; sibling files are 84–92% identical and the
boilerplate asserts things that are false per workflow. When implementing from a
spec file, treat these as known-wrong:

- `"results": {}` is still empty in the six unbuilt workflows' `Prompt.md` files
  (line ~103, typed as a bare `object` at line ~133). **Fixed for WF-03 and WF-04**
  — those now reference real schemas. The other six are out of v1 scope.
- Every workflow claims the same `BR-07` SLA of "4 business hours".
- Every workflow carries identical KPI targets, risk tables, and pain-point tables.
- `09_Prompt_Library/*.md` all share one Cross-References table, so each entry
  claims to be used as every other prompt.
- `09_Prompt_Library/resume_parser.md:77` points at `schemas/prompt_metadata.json`;
  the actual file is `schemas/prompt_metadata.schema.json`.
- ~~Retention is a flat 7 years everywhere~~ **Fixed in Phase 2** — retention is
  now per jurisdiction in `config/organization.yaml` (EU/UK 180d for unsuccessful
  candidates, US-NY 1095d for EEOC, IN 365d). Defaults are a starting point, not
  legal advice.
- `confidence_aggregate >= 0.85` gates the whole architecture and is model
  self-reported. Uncalibrated. Treat the threshold as provisional until Phase 4.3.

---

## What the docs get right — preserve these

- Human-in-the-loop gates with named approvers and an explicit never-automated list.
- **Evidence citations + fuzzy match-back against source (VR-03)** — the primary
  hallucination defense. Implement it strictly.
- `PARTIAL` as a first-class status alongside `SUCCESS` / `FAILED`.
- Idempotency keyed on content hash.
- Protected-characteristic prohibition in the system prompt.

---

## Compliance is a shipping gate, not a feature

Buyers' legal teams ask for these before they ask about features:

- **Bias audit** — NYC Local Law 144 requires a published annual bias audit for
  automated employment decision tools. Illinois and Colorado have parallel duties.
- **DPIA** — required under GDPR Art. 35 for high-risk automated processing.
- **Candidate rights** — GDPR Art. 22 gives a right to human review of automated
  decisions. Needs disclosure and an appeal path.
- **EU AI Act** — employment screening is classified high-risk.

Build the bias harness early (Phase 4.2). It is ~half a day and it forces the
scoring-decomposition decisions that are hardest to change later.

---

## Working conventions

- **One prompt, one commit.** Commit message = the prompt's goal.
- Every prompt carries a `DONE WHEN:` acceptance command. Run it; paste the output.
- Add tests from Phase 3.3 onward; run the suite every session.
- Record decisions here, in this file, in the session that makes them.
- Flag contradictions found in the docs rather than silently fixing them.

---

## Roadmap

Phases 0–5, with a scoped prompt for each, live in the Build Prompt Playbook
artifact. Summary:

| Phase | Work | Status |
|-------|------|--------|
| 0 | Repo foundation | **done** |
| 1 | WF-03 + WF-04 result schemas | **done** |
| 2 | Config layer, de-branding, adapters | **done** |
| 3.1–3.6 | Ingest → extract → validate → persist → review console → match | not started |
| 4.1–4.3 | Golden set, bias harness, confidence calibration | not started |
| 5.1–5.2 | Auth/RBAC/compliance pack, Docker + quickstart | not started |

---

## Decision log

Append here. Newest last.

- **2026-08-22** — Phase 0. Stack pinned (above). Scope cut to WF-03 + WF-04 +
  review console. `generate.py` and `_create_docx_samples.py` retired to
  `tools/legacy/` (byte-identical, checksum-verified) and replaced at the root by
  inert stubs; docs are hand-maintained from now on. Licence MIT, © Parveen Bajaj.
  Repository initialized on branch `main`; initial commit made. Phase 0 complete.
  Root stubs `generate.py` / `_create_docx_samples.py` can be deleted whenever.
- **2026-08-22** — Phase 1. Output contracts written for WF-03 and WF-04.
  `envelope.schema.json` holds the shared response envelope so it is defined once
  rather than copied per workflow. `results` sets `additionalProperties: false` on
  both, which makes it structurally impossible to smuggle an undeclared overall
  score into a match result. Score decomposition locked in: the model judges
  `must_have_coverage`, `experience_band`, and `domain_match` separately with
  evidence; `overall_score` and each `weighted_score` are computed in application
  code from config weights. `UNKNOWN` kept distinct from `NOT_MET` on requirement
  resolution — absence of evidence is not evidence of absence. Arithmetic rules
  (BV-04 weight sum, score consistency, BR-04 archive eligibility) cannot be
  expressed in JSON Schema and are listed in each `Prompt.md` for the validator to
  enforce in Phase 3.3. `tools/validate_output.py` added; 10/10 deliberately broken
  documents rejected.
- **2026-08-22** — Phase 2. `config/organization.yaml` now holds every
  organization-specific value; `.example.yaml` is committed, the real file is
  gitignored. All 51 Contoso references across 27 files replaced with placeholders,
  plus 14 more files carrying `recruitment.example.com` / `@company.com`.
  `tools/render_docs.py` renders to `build/`; `tools/check_branding.py` fails CI on
  any hardcoded value. Adapter protocols added for storage / LLM / ATS / auth with
  local implementations that need no cloud account — the default install requires
  one API key and nothing else. `OrganizationConfig` validates at load: rubric
  weights must sum to 1.0 (BV-04), confidence thresholds must descend,
  `default_scheme` and `default_jurisdiction` must exist. 5/5 invalid configs
  rejected. Retention is now per jurisdiction, closing the GDPR conflict.
  Caveat recorded: `confidence.calibrated: false` — the thresholds are still round
  numbers, not measurements. Phase 4.3 fixes that.
