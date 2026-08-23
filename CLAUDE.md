# CLAUDE.md — AI Recruitment System

Project context for AI coding sessions. Read this first, every session.

---

## What this project is

An AI-assisted recruitment pipeline: resume in, ranked and evidence-cited shortlist
out, with a human reviewing every decision that affects a candidate.

**Current state (2026-08-22):** was a documentation blueprint; now has a working
ingest → extract → validate → persist → review pipeline under `src/recruit/`, a
config layer, a working web console, and 78 passing tests. Phases 0–3.5 complete. The two scripts under `tools/legacy/` are the
original document generators — they wrote the docs, they do not run the pipeline,
and they must never be run again.

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
| Evidence check | `rapidfuzz` — **implemented**, `validate.validate_evidence` |
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
- Every session that touches `src/` adds tests and runs `python -m pytest -q`.
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
| 3.1 | Ingest | **done** |
| 3.2 | Extract (structured output) | **done** |
| 3.3 | Validate (incl. VR-03 evidence grounding) | **done** |
| 3.4 | Persist (Postgres, append-only audit) | **done** |
| 3.5 | Review console | **done** |
| 3.6 | Matching (WF-04) | not started |
| 4.1–4.3 | Golden set, bias harness, confidence calibration | not started |
| 5.1–5.2 | Auth/RBAC/compliance pack, Docker + quickstart | not started |

---

## Deferred work — not done, not forgotten

Things a phase was supposed to deliver but did not. Each names why, and when it
lands. Do not assume anything here exists.

| Item | Owed by | Why deferred | Lands in |
|------|---------|--------------|----------|
| ~~`LLMAdapter` implementation~~ | Phase 2 | **Closed in Phase 3.2.** `AnthropicLLM` uses tool use; `FakeLLM` runs the pipeline with no key. The fake path is fully tested. The real API path is written but not yet exercised against live Anthropic — first real run is the operator's. | — |
| Virus scan on intake | Phase 3.1 | `Validation.md` §2 requires a clean scan before acceptance. Needs a scanner (ClamAV or a cloud API) that is not a Python dependency. Ingest records `scanned: false` rather than pretending. | Phase 5.2 |
| OCR on the operator's machine | Phase 3.1 | The fallback is **verified working** — recovered 408 chars from an image-only PDF in the build environment. But Tesseract and Poppler are system binaries, not wheels, so it is untested on Windows. `pip install -e ".[ocr]"` covers the Python side only. | Phase 5.2 (Docker image bundles them) |
| Cloud storage / ATS / auth adapters | Phase 2 | Only `local`, `csv`/`none`, and `single_user` are implemented. Others raise `NotImplementedError` with a clear message rather than failing obscurely. | Phase 5 |
| Confidence calibration | Phase 2 | `confidence.calibrated: false` in config. Thresholds are round numbers, not measurements. | Phase 4.3 |
| Doc de-duplication | — | Sibling docs still 84–92% identical. Not on the critical path to shipping. | Optional cleanup |

**Rule:** when a phase cannot deliver something it promised, add a row here in the
same session. A gap that is written down is a plan; a gap that is not is a bug.

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
- **2026-08-22** — Phase 3.1. First real code. `src/recruit/ingest.py` validates
  and extracts PDF/DOCX/TXT; `src/recruit/errors.py` gives every failure a reason
  code and a recovery line, so nothing reaches a recruiter as a traceback (9/9
  malformed documents fail cleanly). Magic-byte checking means a renamed
  executable never reaches the parser. **The content hash is taken over the source
  BYTES, not the extracted text** — extraction output varies with the pypdf
  version, so hashing text would silently break idempotency on a library upgrade.
  DOCX table cells are extracted, not dropped: resumes put skills and dates in
  tables. `OCRUnavailable` is kept distinct from `EmptySource` — one is an
  operator install problem, the other is a bad document, and conflating them would
  send good scans to manual transcription while hiding a fixable issue. OCR
  fallback verified end to end. `pyproject.toml` added; 14 tests pass.
- **2026-08-22** — Phase 3.2. First LLM call. `AnthropicLLM` uses **tool use with
  forced `tool_choice`**, so the model physically cannot answer in prose — this
  removes the repair-prompt loop the original specs designed around, exactly as
  predicted in the Phase 3.2 note. `FakeLLM` satisfies the same protocol and lets
  the whole pipeline, validation included, run with no key and no cost.
  `prompts.py` loads the system and user prompts **from `Prompt.md`**, not from
  Python literals — the markdown is the governed artifact and duplicating it in
  code would guarantee drift. It also **dereferences file `$ref`s**: no provider
  resolves external refs in a tool schema, so `resume.schema.json` is inlined
  before the call. Three decisions worth keeping: `confidence_aggregate` is the
  **minimum** field confidence, not the mean (averaging lets nine good fields hide
  one fabricated employer); ingest facts (page count, char count, content hash)
  **overwrite** whatever the model claims, since the model must not be trusted to
  report them; an unfilled `{{runtime_var}}` raises rather than reaching the model
  as literal text. 29 tests pass.
- **2026-08-22** — Phase 3.3. Validation, four layers, in `src/recruit/validate.py`.
  **VR-03 is live and is the most important code in the project**: every evidence
  snippet is fuzzy-matched back against the source text; below 0.8 similarity the
  run is flagged `POTENTIAL_HALLUCINATION` and blocked. Demonstrated catching a
  fabricated "Principal Engineer at Google DeepMind" (0.46) and a plausible-but-
  absent "AWS Certified Solutions Architect Professional" (0.52), while a verbatim
  quote with mangled PDF whitespace still scores 1.00 — the normalization step
  exists precisely so line-break noise does not produce false accusations of
  fabrication. Returns a `ValidationReport`, never a bool: a reviewer needs rule,
  severity, and JSON Pointer, not "invalid". Severity ladder is
  CRITICAL > ERROR > WARNING > INFO; only the first two block. `VR-01` is CRITICAL
  when confidence is below threshold while `human_review_required` is false —
  that combination is the one that would put an unreviewed extraction in front of
  a hiring manager. Validation is wired into the extract CLI and downgrades status
  to PARTIAL on any blocking finding. 45 tests pass; ruff clean.
- **2026-08-22** — Phase 3.4. Postgres replaces the folder-as-database design.
  Six tables under `src/recruit/db/`. **The append-only audit log is enforced in
  two layers**: the `Repository` exposes no mutating method (a test asserts this
  by introspection), and a database trigger raises on UPDATE or DELETE. Verified
  against real Postgres 16 — both operations rejected with
  `audit_log is append-only ... (BR-05)`. One layer alone is insufficient: app
  rules are bypassed by anyone with a psql prompt, DB rules are silently absent if
  a migration is skipped. Idempotency is a `UNIQUE(content_sha256)` on documents
  plus `UNIQUE(workflow_id, document_id)` on runs, so re-submitting a resume
  costs nothing and never duplicates API spend; `force=True` is the documented
  manual re-run path. PII is **masked, not dropped**, in audit detail (BR-06) —
  `rahul.sharma@email.com` stores as `r***[22]`, so a reviewer can still see a
  field was present. Models declare `JSON` so the suite runs on SQLite with no
  server; the migration upgrades to `JSONB` on Postgres. The same 16 persistence
  tests pass on both. Retention now queries per jurisdiction and consent extends
  the window rather than removing it. `docker-compose.yml` and
  `python -m recruit.db_init` added. 61 tests pass; ruff clean.
- **2026-08-22** — Phase 3.5. Review console: FastAPI + Jinja, `src/recruit/web/`.
  **Evidence click-through works and is verified in a real browser** — clicking an
  extracted field highlights the exact span of the source document it came from.
  To make that possible, `validate.locate_snippet` records `char_start`/`char_end`
  during the VR-03 pass: the search has already happened there, so locating is
  free, and reconstructing it later would search twice. **Highlighting uses
  offsets, not client-side text search** — searching for the snippet in the
  browser would highlight the wrong occurrence whenever a phrase repeats; there is
  a test for exactly that. Source text is stored on the **envelope, not in
  `results`** — `results` sets `additionalProperties: false`, so putting it there
  fails schema validation on every run. Rejections require a reason code from a
  fixed list rather than free text, so they can be counted and fed back into
  prompt quality in Phase 4. Keyboard-first: A approve, R reject, E escalate,
  J/Esc back. Resolving twice returns 409. Every decision writes to the
  append-only audit log with reviewer identity, prompt version, and model id.
  `python -m recruit.seed` populates a working queue so a new install never opens
  on an empty screen. 78 tests pass; ruff clean.
