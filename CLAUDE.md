# CLAUDE.md — AI Recruitment System

Project context for AI coding sessions. Read this first, every session.

---

## What this project is

An AI-assisted recruitment pipeline: resume in, ranked and evidence-cited shortlist
out, with a human reviewing every decision that affects a candidate.

**Current state (2026-08-23):** was a documentation blueprint; now a working
product. `src/recruit/` runs ingest → extract → validate → persist → review →
match, behind real authentication with role-based access control, with a
bias-audit harness, a compliance pack, a one-command Docker quickstart, and a
console written in plain English rather than field names. 175 tests pass.

Phases 0–3 complete (the vertical slice runs end to end), plus 4.2, 5.1 and 5.2.
Remaining: the golden set (4.1) and confidence calibration (4.3, blocked on it).

The two scripts under `tools/legacy/` are the original document generators —
they wrote the docs, they do not run the pipeline, and must never be run again.

**Target: a working single-tenant product that ships**, not a specification for
someone else to implement. Estimated 4–6 months of focused solo work.

---

## Scope decision — read before proposing work

**Build WF-03 (extraction) + WF-04 (matching) + the review console — and, from
2026-08-23, WF-02 (intake). Nothing else.**

WF-01, 05, 06, 07, and 08 are workflow and record-keeping that an existing ATS
already does adequately. They stay documented and unbuilt for v1. The commercial
core is extraction, matching, and the review screen.

**WF-02 was cut and is now back in.** Amended deliberately by the operator on
2026-08-23, not drifted into. The reason: with Phases 0–5 complete, every resume
still reaches the system because a person put it there, which caps the product at
the speed of that person. Intake is what makes it a system rather than a tool.
The plan is `docs/intake_playbook.md` (Phase 6, thirteen prompts, 6.0–6.12).

Three constraints came with the amendment and are not negotiable inside it:
LinkedIn has no reachable API and must never be scraped; the safety gate (6.5)
lands before automatic screening (6.8); and the golden set (6.10) is no longer
optional, because automatic screening against uncalibrated thresholds makes
claims about real people that nobody has checked.

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
| Database | **SQLite by default** (zero setup); Postgres 16 for production. SQLAlchemy 2.x, Alembic. |
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
   paste real terminal output — on a machine that does NOT already have the
   dependencies, where that is what is being tested.
7. **No organization-specific value outside `config/`.** No company name, email,
   domain, retention period, SLA, or scoring weight hardcoded anywhere else.
   `python tools/check_branding.py` enforces this; run it in CI.
8. **Two kinds of `{{placeholder}}`.** `{{org.*}}`, `{{contact.*}}`,
   `{{matching.*}}` and friends are **build-time** and resolved by
   `tools/render_docs.py`. `{{candidate_id}}`, `{{source_content}}` and friends are
   **runtime** prompt variables the orchestrator fills per run — the renderer
   deliberately leaves them alone. Do not conflate them.
9. **`pip install -e .` alone must run the pipeline.** Ingest, extract, validate,
   and persist work with no server, no Docker, and no compiled driver. Only the
   web console (`[web]`) and Postgres (`[postgres]`) are extras. Anything that
   breaks that is a defect, not a configuration choice.
10. **Every module-level import must be declared in `pyproject.toml`.**
    `tests/test_packaging.py` enforces it. A dependency that is merely transitive
    works until the package that pulled it in swaps it out.

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

Status: the bias harness exists (`recruit.bias_audit`, self-tested), and DPIA,
candidate-disclosure, and appeal templates are in `docs/compliance/`. **All of
those are internal or template-stage.** LL144 needs an *independent* audit, and
no DPIA has actually been performed — `docs/compliance/README.md` lists what is
still missing as prominently as what exists.

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
| 3.6 | Matching (WF-04) | **done** — vertical slice complete |
| 4.1 | Golden set | **deferred — see register** |
| 4.2 | Bias harness | **done** |
| 4.3 | Confidence calibration | not started (blocked on 4.1) |
| 5.1 | Auth, RBAC, compliance pack | **done** |
| 5.2 | Docker + quickstart + CI | **done** — image build unverified, see below |
| 6 | **Intake automation (WF-02)** — mail intake, landing zone, safety gate, screen on arrival | not started — `docs/intake_playbook.md` |

---

## Deferred work — not done, not forgotten

Things a phase was supposed to deliver but did not. Each names why, and when it
lands. Do not assume anything here exists.

| Item | Owed by | Why deferred | Lands in |
|------|---------|--------------|----------|
| ~~`LLMAdapter` implementation~~ | Phase 2 | **Closed in Phase 3.2.** `AnthropicLLM` uses tool use; `FakeLLM` runs the pipeline with no key. The fake path is fully tested. The real API path is written but not yet exercised against live Anthropic — first real run is the operator's. | — |
| Virus scan on intake | Phase 3.1 | `Validation.md` §2 requires a clean scan before acceptance. Needs a scanner (ClamAV or a cloud API) that is not a Python dependency. Ingest records `scanned: false` rather than pretending. **Not closed by Phase 5.2**: ClamAV in the image would mean a ~200MB signature database, a refresh daemon, and a container that fails to start when a mirror is down — too much weight for a quickstart. It belongs in a separate service. | Not scoped |
| OCR on the operator's machine | Phase 3.1 | The fallback is **verified working** — recovered 408 chars from an image-only PDF in the build environment. But Tesseract and Poppler are system binaries, not wheels, so it is untested on Windows. `pip install -e ".[ocr]"` covers the Python side only. The Phase 5.2 image installs both as apt packages, and CI asserts they are present — **but that image has never been built**, so this stays open until it has. | Open until the image builds |
| **Docker image never built** | Phase 5.2 | The Dockerfile, entrypoint, compose stack and CI were written and every part that can be checked without a registry was checked: `bash -n` on the entrypoint, all three of its branches run against real databases, `docker compose config` valid, first-run bootstrap and login verified end to end natively. **The image itself was never built** — the build sandbox had no route to Docker Hub or any mirror (403 on every registry). The first `docker compose up` is therefore the acceptance test, and it runs on the operator's Windows machine, which is exactly the "machine that does not already have the dependencies" hard rule 6 asks for. | The operator's next `docker compose up` |
| Cloud storage / ATS adapters | Phase 2 | Only `local` and `csv`/`none` are implemented. Others raise `NotImplementedError` with a clear message rather than failing obscurely. | Phase 5.2+ |
| OIDC single sign-on | Phase 5.1 | `local` (scrypt passwords, server-side sessions) and `single_user` are implemented. `oidc` **raises rather than falling back** — an org that configures SSO and silently gets weaker auth has an incident, not a warning. | When a customer needs it |
| Candidate-facing portal | Phase 5.1 | `appeal_process.md` and `candidate_disclosure.md` describe a process with no UI behind it. Today it is manual on the operator's side, and the docs say so. | Not scoped |
| **Golden set (prompt 10)** | Phase 4.1 | **Deliberately deferred at the operator's request.** Needs 50–100 real resumes with human-labelled ground truth — that is the operator's evening, not a coding session. Everything in 4.3 is blocked on it, and no accuracy number can be quoted until it exists. | Next available |
| Confidence calibration | Phase 2 | `confidence.calibrated: false` in config. Thresholds are round numbers, not measurements. Blocked on the golden set. | Phase 4.3 |
| ~~**Plain-language console copy**~~ | Phase 3.5 / 5.1 | **Closed 2026-08-23.** `web/humanize.py` plus rewritten templates; the technical values are hidden behind a toggle, not removed, and `tests/test_humanize.py` fails if either half regresses. Original entry kept below for the reasoning. |
| ~~Plain-language console copy (original entry)~~ | Phase 3.5 / 5.1 | **The console is written for engineers and its users are not.** The audit page column heads are `Run`, `Prompt`, `Model`; the rows carry `workflow_run_id`, `prompt_version`, `model_id`, event names like `auth.login_failed`, and a raw Python dict in `detail`. Reviewers will be recruiters and hiring managers — the operator puts it at 99% non-technical. Needs: human sentences per event ("Parveen signed in" / "Sign-in failed — wrong password"), plain column heads, `detail` rendered as fields rather than a dict, and the same pass over the queue, detail, login and error screens. The jargon must survive *somewhere* — LL144 and GDPR Art. 22 evidence depends on run and model identity — so this is a presentation layer over the existing columns, not a schema change: keep the technical values behind a "Show technical details" toggle or an export. | Next available |
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
- **2026-08-22** — Packaging fixes, both found by running a real install rather
  than by reading code. (1) `pyproject.toml` had been overwritten from a stale
  scratch copy, silently dropping `sqlalchemy`, `alembic`, `psycopg`, and
  `rapidfuzz` plus three console scripts — a fresh install died with
  `ModuleNotFoundError`. `tests/test_packaging.py` now walks every import in
  `src/` and fails if it is undeclared; **it immediately caught a second one**,
  `referencing`, which was working only as a jsonschema transitive.
  (2) The shipped config defaulted to a **Postgres** URL while `psycopg` is an
  optional extra, so `python -m recruit.seed` failed on a clean machine. Default
  is now SQLite — no server, no Docker, no compiled driver — and a missing driver
  raises `DatabaseDriverMissing` naming both fixes instead of a bare import
  error. Postgres remains the production target and is one config line away.
  82 tests pass.
- **2026-08-22** — Phase 3.6. Matching, `src/recruit/match.py`. The vertical
  slice is complete. **Hard rule 3 is now enforced structurally rather than by
  convention**: `model_facing_schema()` strips `overall_score`, `recommendation`,
  `auto_archive_eligible`, `weighting`, `weight`, and `weighted_score` from the
  tool schema before the call, so the model is *incapable* of returning a fit
  score — a future prompt edit cannot reintroduce one. The model judges each
  component 0..1 with evidence; `combine()` applies config weights in code.
  Verified: `sum(raw x weight)` equals `overall_score` to six decimals, and
  switching `default` (0.5/0.3/0.2) to `swe-ic` (0.6/0.2/0.2) moves the
  must-have contribution 0.400 -> 0.480 while leaving every raw judgement
  untouched. Four guard rails, all tested: weights must sum to 1.0 (BV-04); an
  unweighted component is rejected; a **missing** component is rejected rather
  than scored as zero (silently zeroing a dimension would change who gets
  rejected, invisibly); `raw_score` must lie in 0..1. `weighting` provenance is
  stamped per result so a historical match stays reproducible after the rubric
  changes. BR-04 implemented as *eligibility*, not permission — a 0.20 candidate
  is flagged `auto_archive_eligible` and still routed to a human. `seed.py` now
  filters to resume-like documents; it was seeding a queue of five identical
  rows from reports and a job description. 105 tests pass; ruff clean.
- **2026-08-22** — Phase 4.2. Bias audit harness, `src/recruit/bias/`. Five
  perturbation dimensions: name, gender signal, university prestige, location,
  graduation year. **The harness is itself under test**: `BiasedFakeLLM` injects
  a known penalty and `test_detects_injected_bias` requires it to be caught — a
  harness that has never found bias cannot support a claim of finding none.
  `--self-test` runs that check from the CLI. Findings are attributed **per
  component**, so a report says "`domain_match` leaks the university name",
  which is fixable, rather than "the total moved", which is not.
  `assert_substance_unchanged` refuses to report on an uncontrolled comparison:
  if a perturbation altered a skill, the delta would be the change, not bias.
  **A bug this caught in my own code**: the age dimension originally shifted
  employment dates alongside graduation year, which turned 5 years of tenure
  into 23 on a role with no end date — measuring experience, not age. It now
  shifts education only, holds employment byte-identical, and the report
  discloses the resulting graduation-gap confound rather than hiding it. The
  report also states its own limits: one profile per group is a smoke test, not
  a statistic, and this is **not** an LL144 compliance certificate — that
  requires an independent third-party audit. 121 tests pass; ruff clean.
- **2026-08-22** — Phase 5.1. Real authentication and RBAC. Passwords use
  `hashlib.scrypt` from the **standard library** rather than bcrypt or argon2 —
  both are compiled dependencies and hard rule 9 requires installing without a
  compiler. Session tokens are stored **hashed**: a database dump then yields no
  usable cookies, and SHA-256 is correct there rather than scrypt because a
  256-bit random token has nothing to brute-force. **Authorization is enforced at
  the route, never in the template** — `require(permission)` is a FastAPI
  dependency, and there is a test that renders the Approve button for a recruiter
  and then asserts POSTing to the URL still returns 403. Four roles from the RACI
  tables; a recruiter may review and escalate but **not** approve, which is the
  §15 human-in-the-loop boundary expressed in code. Login failures are
  indistinguishable from unknown users (the adapter hashes a dummy password on
  the miss so timing does not leak account existence), and deactivating a user
  revokes live sessions rather than waiting for cookie expiry. Compliance pack
  added under `docs/compliance/`: DPIA, candidate disclosure, and appeal process,
  every one marked a template with `[ORGANIZATION TO COMPLETE]` blanks — shipping
  unreviewed legal text is worse than shipping none, because someone relies on
  it. The README lists what the system does **not** do as prominently as what it
  does. 143 tests pass; ruff clean.
- **2026-08-23** — Phase 5.2. Packaging, quickstart, and CI. The goal of this
  phase is a stranger reaching a working review queue in ten minutes with no
  API key, no database, and no Python — so `docker compose up` seeds the queue
  with the **fake** model and the console runs without a credential of any kind.
  Three decisions worth keeping. (1) **The first-run password is generated, not
  defaulted.** `recruit.bootstrap` runs on every container start, creates an
  administrator only when none exists, and prints a `secrets.token_urlsafe`
  password once; an operator-supplied `RECRUIT_ADMIN_PASSWORD` is used but never
  echoed. Shipping `admin/admin` is how products end up indexed by Shodan, and a
  credential nobody was given cannot be leaked. Idempotency is tested directly:
  a second start must not create a second account **and must not rotate the
  first password**, because a restart that silently invalidated the only
  administrator would be indistinguishable from a break-in. (2) **Both published
  ports bind to `127.0.0.1`**, and a test parses `docker-compose.yml` and fails
  if that ever changes — the console shows candidate data and, under the shipped
  example config, has no login at all, so exposing it must be a decision someone
  makes rather than a default they inherit. (3) `RECRUIT_CONFIG` now overrides
  the config path, resolved per call rather than at import, so a container can
  point at a mounted file and the entrypoint can fall back to the example when
  `config/` is mounted read-only instead of refusing to start. **A defect caught
  while writing the `.dockerignore`**: excluding the numbered workflow folders
  looked obviously right — they are documentation — but `prompts.WorkflowPrompt`
  loads the live system and user prompts from `03_Extracted_Data/Prompt.md` at
  run time, so the image would have shipped a working console whose first real
  extraction raised `PromptError`. There is now a test asserting no `0N_` pattern
  appears in `.dockerignore`. Also found by adding CI rather than by reading:
  `ruff check .` was **not** clean — `tools/legacy/generate.py` contributed 165
  findings, and `tests/test_packaging.py` had an unsorted import. Legacy is now
  excluded from lint (it is preserved byte-identical on purpose; linting it means
  either permanent red or edits that break the checksum guarantee) and the import
  is fixed. The README was rewritten for someone who has never seen the project:
  what it does, what it does not, the ten-minute path, and a "before you use this
  on real candidates" section that says plainly that the bias harness is not an
  LL144 audit, that no DPIA has been performed, and that **no accuracy figure
  exists**. Two drift repairs while syncing: `samples/Software_Engineer.json`
  still carried a `Contoso` EEO statement in the build tree (the operator's copy
  was correct and won), and `adapters/local.py` / `config.py` were behind on
  their side. **The image was never built** — every container registry returned
  403 from the build sandbox — so what was verified is everything short of that:
  `bash -n` on the entrypoint, all three of its branches exercised against real
  databases including the read-only-config fallback as an unprivileged user,
  `docker compose config`, and the full first-run sequence run natively end to
  end (bootstrap → generated password → seed → console → sign in → queue showing
  the seeded candidate). The first `docker compose up` on Windows is the
  acceptance test, and it is recorded as open in the deferred register rather
  than assumed. 160 tests pass; ruff clean; branding, schema, render and bias
  self-test gates all green.
  **Postscript, same day, found by the operator running the suite on Windows.**
  Two defects the build environment could not have shown. (1)
  `test_entrypoint_is_valid_shell` shells out to `bash -n`, which Windows does
  not have — it now skips there rather than failing, because a machine with no
  shell to check the file with proves nothing about the file, and CI on Linux
  still checks it. (2) The `dev` extra declared `httpx`, but **Starlette 1.2
  (May 2026) moved its TestClient to `httpx2`** and a current Starlette raises
  `RuntimeError` on import without it. The build machine had Starlette 1.0 and
  never saw it; the operator's had a newer one and could not collect
  `test_web.py` or `test_auth.py` at all. Reproduced deliberately by upgrading
  Starlette to 1.6 here, then verified the whole suite passes with `httpx2`
  installed and `httpx` **removed**. Both are now declared. This is the third
  time a packaging defect has been invisible to a machine that already had the
  right libraries, and the second time hard rule 6 caught it — the rule is
  earning its place.
- **2026-08-23** — Plain-language console. Raised by the operator on seeing the
  audit screen: the people who will use this are "layman 99 eprcent time", and
  the screen was written for someone who already knew what `workflow_run_id`
  and `auth.login_failed` meant. `src/recruit/web/humanize.py` now translates
  events, review reasons, rejection reasons, validation rules, severities,
  states, roles, confidences and field names into sentences, and every template
  reads through it. **The technical values are hidden, not removed** — a "Show
  technical details" toggle (remembered per browser) reveals `workflow_run_id`,
  `prompt_version`, `model_id`, content hashes and rule identifiers on every
  screen. That constraint is the whole design: LL144 and GDPR Art. 22 turn on
  being able to name the model and prompt version behind a decision, so a
  console that translated them away would read well and be useless in an audit.
  `tests/test_humanize.py` enforces both halves — it parses the rendered HTML,
  strips everything inside a `tech*` class, and fails if any identifier appears
  in what is left, then separately asserts those identifiers are still in the
  page. Three rules held throughout: an unrecognised code is tidied
  (`SOME_NEW_THING` -> `Some new thing`), never guessed at, because a confident
  mistranslation is worse than a visible code; warnings are worded to land
  harder, not softer; and wording lives in one place, so the reject dropdown,
  the audit sentence and the summary cannot drift apart.
  **Four defects the screenshots caught that the tests did not.** (1) A failed
  sign-in read "Someone tried to sign in as Admin" — `actor_name` had tidied the
  mistyped address into a display name, destroying the one fact that makes the
  row useful. It now quotes the address character for character; the screenshot
  shows `"admin@localhostt"` beside a genuine `"admin@localhost"` failure, which
  is exactly the distinction that took an hour to find during the operator's own
  login incident. (2) `Reason invalid_credentials` leaked as a raw code.
  (3) `Seeded: Yes` was rendered as if it were information. Both fixed by making
  `detail_pairs` event-aware, with a per-event hide list for keys the sentence
  already covers. (4) Field labels were mechanically title-cased into
  `Candidate Id`, `Linkedin Url` and `Is Current: True` — schema, not resume.
  Verified in a real browser at five screens, both toggle states. 175 tests
  pass; ruff clean.
- **2026-08-23** — Scope amended: WF-02 (intake) is back in, as Phase 6. The
  operator asked to connect Gmail, LinkedIn, Naukri and Indeed so applications
  arrive and are screened without anyone pasting a file. Recorded here rather
  than absorbed quietly, because the scope section explicitly told a session
  finding itself doing this to stop and flag it — and it did.
  **What the research changed about the ask.** Three of the four named sources
  have no reachable API. LinkedIn applicant data sits behind the Talent
  Solutions / Recruiter System Connect partnership: an enterprise sales track,
  four to six months minimum, expecting existing scale — and scraping instead
  breaches their User Agreement, which they enforce. Indeed Apply will POST
  applications to a webhook, which is precisely the right shape, but only after
  a signed Developer Agreement, a published XML job feed and an issued token.
  Naukri is the same, through their enterprise team. Only Gmail is buildable
  today, and its restricted read scope needs an annual paid CASA assessment
  **unless** the app is internal to one Workspace org or used only by its
  developer — an exemption that covers running your own hiring and expires the
  day this is sold to someone else.
  **So the design is email, not four integrations.** Every one of those
  platforms will deliver to an address, which needs nobody's permission. One
  mail intake, a small parser per source, a separate alias per source so
  provenance is a fact rather than a guess from a sender name, and the raw
  message kept forever because parsers get fixed and the evidence they were
  wrong about must outlive them. Partner APIs become an upgrade slot, not a
  prerequisite. **The unknown that gates everything**: some sources attach the
  resume, others send "someone applied, click here" behind a login, and which
  one you get varies by country, plan and how the job was posted. No
  documentation answers it. Prompt 6.1 is the operator applying to their own
  posting and reading what lands; every parser is built against those captures.
  **Three constraints recorded with the amendment.** Never build for or scrape
  LinkedIn. The safety gate (6.5) lands before automatic screening (6.8) —
  opening files sent by strangers with no human looking first is what finally
  makes the deferred virus-scan item mandatory, alongside expansion limits, an
  hourly cap, a spend cap and a kill switch, because one mail loop pointed at
  the intake address bills for the same message all night. And the golden set
  (6.10) stops being optional: `confidence.calibrated: false` is tolerable while
  the operator hand-picks the resumes, and indefensible once every applicant is
  screened automatically against thresholds nobody measured. The human decision
  gate does not move — screening automatically is lawful, rejecting
  automatically is the part that is not.
