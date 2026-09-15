# CLAUDE.md — AI Recruitment System

Project context for AI coding sessions. Read this first, every session.

---

## What this project is

An AI-assisted recruitment pipeline: resume in, ranked and evidence-cited shortlist
out, with a human reviewing every decision that affects a candidate.

**Current state (2026-09-13):** was a documentation blueprint; now a working
product. `src/recruit/` runs ingest → extract → validate → persist → review →
match, behind real authentication with role-based access control, with a
bias-audit harness, a compliance pack, a one-command Docker quickstart, a
console written in plain English rather than field names, a one-click path to
a copy on your own server with your own accounts, and a free local model so it
costs nothing to run for real. 277 tests pass.

Phases 0–3 complete (the vertical slice runs end to end), plus 4.2, 5.1, 5.2,
5.3, 5.4 and 5.5.
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

**Who owes the DPIA — settled 2026-09-14, do not re-raise as project debt.**
The duty under Art. 35 attaches to the **controller**: whoever decides to
process real applicants' data. Publishing code is not processing. So:

- **A stranger who self-hosts** is their own controller and owes their own
  DPIA. We cannot perform it — it needs their lawful basis, their retention
  periods, their DPO, their supervisory authority. What we owe them is an
  honest template and accurate engineering facts to cite, which is what
  `docs/compliance/` is. That is a **shipped deliverable, not an open gap.**
- **The Phase 7 demo** processes invented candidates only. No personal data,
  no DPIA. This is one of the reasons demo mode refuses uploads rather than
  warning about them — the refusal is what keeps the claim true.
- **The operator** owes one **the day Phase 6 intake points at a real inbox
  and a real application lands.** That is the line, and 6.1 is the step that
  crosses it. Recorded against Phase 6 in the register, not carried as a
  standing failure of the project.

---

## Working conventions

- **One prompt, one commit.** Commit message = the prompt's goal.
- **No AI-attribution trailers in commit messages.** The README discloses that
  the build is AI-assisted, in the operator's own framing and where a reader
  actually looks. Putting it in commit metadata as well turns a stated fact into
  a contributor graph, which says something different. Decided 2026-09-13; the
  two commits already carrying a `Co-Authored-By` line stay as they are, because
  rewriting published history to look better is a worse story than the trailer.
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
| 5.2 | Docker + quickstart + CI | **done and verified** — image builds green in CI |
| 6.0 | Scope amendment | **done** |
| 6.1 | Capture real job-board emails | **operator's homework** — blocks 6.3 |
| 6.2a | Mail reading: MIME, attachments, filenames, provenance | **done** |
| 5.3 | Self-hosting: browser account management, public-deploy guard, Render blueprint | **done** — the deploy itself unverified |
| 5.4 | Free local model (Ollama), console redesign, working dark mode | **done and verified** — real extraction run |
| 5.5 | `field_confidence` made grammar-enforceable | **done** — old envelopes still readable |
| 6.2b–6.12 | Gmail connection, per-source parsers, landing zone, safety gate, screening | not started — `docs/intake_playbook.md` |
| 7.0–7.10 | Workspaces, sign-up, demo mode | **planned** — `docs/phase7_playbook.md`, eleven prompts |
| 8.0 | Browser first-run setup (no log reading) | **done and verified** — run natively, both local and public-with-token |
| 8.1 | Public demo page (`/demo`) | **done and verified** — screenshots in `docs/screenshots/` |
| 8.2–8.x | Windows installer, model included | not started — research done, see decision log |

---

## Deferred work — not done, not forgotten

Things a phase was supposed to deliver but did not. Each names why, and when it
lands. Do not assume anything here exists.

| Item | Owed by | Why deferred | Lands in |
|------|---------|--------------|----------|
| ~~`LLMAdapter` implementation~~ | Phase 2 | **Closed in Phase 3.2.** `AnthropicLLM` uses tool use; `FakeLLM` runs the pipeline with no key. The fake path is fully tested. The real API path is written but not yet exercised against live Anthropic — first real run is the operator's. | — |
| Virus scan on intake | Phase 3.1 | `Validation.md` §2 requires a clean scan before acceptance. Needs a scanner (ClamAV or a cloud API) that is not a Python dependency. Ingest records `scanned: false` rather than pretending. **Not closed by Phase 5.2**: ClamAV in the image would mean a ~200MB signature database, a refresh daemon, and a container that fails to start when a mirror is down — too much weight for a quickstart. It belongs in a separate service. | Not scoped |
| OCR — narrowed, not closed | Phase 3.1 | **The image half is closed**: CI proves Tesseract and Poppler are present and answering inside the container, so anyone running via Docker has working OCR on any host. What remains open is OCR for someone who installs natively on Windows, where both are manual downloads. That is now a documentation problem, not a shipping blocker — the supported answer is the image. |
| ~~**Docker image never built**~~ | Phase 5.2 | **Closed 2026-08-23.** Built on a GitHub Actions runner — a machine with none of the dependencies installed, which is exactly what hard rule 6 asks for. `docker` job green in 1m 6s: image built, `tesseract --version` and `pdftoppm -v` both answered from inside it, `docker compose up --wait` brought up Postgres and the console, and `/health` returned OK. The build sandbox could not do this (every registry 403'd) and the operator has no Docker installed; CI did it for free on the first run. |
| Cloud storage / ATS adapters | Phase 2 | Only `local` and `csv`/`none` are implemented. Others raise `NotImplementedError` with a clear message rather than failing obscurely. | Phase 5.2+ |
| OIDC single sign-on | Phase 5.1 | `local` (scrypt passwords, server-side sessions) and `single_user` are implemented. `oidc` **raises rather than falling back** — an org that configures SSO and silently gets weaker auth has an incident, not a warning. | When a customer needs it |
| Candidate-facing portal | Phase 5.1 | `appeal_process.md` and `candidate_disclosure.md` describe a process with no UI behind it. Today it is manual on the operator's side, and the docs say so. | Not scoped |
| **Golden set (prompt 10)** | Phase 4.1 | **Deliberately deferred at the operator's request.** Needs 50–100 real resumes with human-labelled ground truth — that is the operator's evening, not a coding session. Everything in 4.3 is blocked on it, and no accuracy number can be quoted until it exists. | Next available |
| Confidence calibration | Phase 2 | `confidence.calibrated: false` in config. Thresholds are round numbers, not measurements. Blocked on the golden set. | Phase 4.3 |
| ~~**Plain-language console copy**~~ | Phase 3.5 / 5.1 | **Closed 2026-08-23.** `web/humanize.py` plus rewritten templates; the technical values are hidden behind a toggle, not removed, and `tests/test_humanize.py` fails if either half regresses. Original entry kept below for the reasoning. |
| ~~Plain-language console copy (original entry)~~ | Phase 3.5 / 5.1 | **The console is written for engineers and its users are not.** The audit page column heads are `Run`, `Prompt`, `Model`; the rows carry `workflow_run_id`, `prompt_version`, `model_id`, event names like `auth.login_failed`, and a raw Python dict in `detail`. Reviewers will be recruiters and hiring managers — the operator puts it at 99% non-technical. Needs: human sentences per event ("Parveen signed in" / "Sign-in failed — wrong password"), plain column heads, `detail` rendered as fields rather than a dict, and the same pass over the queue, detail, login and error screens. The jargon must survive *somewhere* — LL144 and GDPR Art. 22 evidence depends on run and model identity — so this is a presentation layer over the existing columns, not a schema change: keep the technical values behind a "Show technical details" toggle or an export. | Next available |
| **Render deploy never performed** | 5.3 | `render.yaml` is parsed and asserted by a test, and everything it configures was run natively against a live server with `RECRUIT_PUBLIC=1` — but no blueprint has ever been submitted to Render. The first click is the acceptance test. Same shape as the Docker image, carried open for a day and then green in CI on the first try. | Operator's next sitting |
| ~~**`OllamaLLM` never run against a real Ollama**~~ | 5.4 | **Closed 2026-09-14.** The operator installed Ollama, pulled a 3B model and ran a real extraction: correct name, email, two roles and nine skills out of an actual PDF, with no API key. It immediately found a defect no test could — the digest lookup asked `/api/show`, which carries no digest at all; it lives in `/api/tags`. Right by the documentation, wrong against the daemon. | — |
| Refused account changes are not logged | 5.3 | Blocking a lockout raises before anything is written, so an attempt to switch off the last administrator leaves no trace. Successful changes are recorded; refused ones are not, and repeated attempts are the more interesting signal of the two. Small to add — the guard already holds a session — and deliberately not bundled into a change that was already wide. | Next available |
| **DPIA for the operator's own instance** | Phase 6 | Not project debt — see the compliance section above. A self-hoster owes their own; the demo has no personal data to assess. This row exists for the one case that *is* the operator's: the day 6.1 points intake at a real inbox and a stranger's application arrives, the operator becomes a controller of real applicants' data and owes a performed DPIA, not a template. Filling in `docs/compliance/dpia.md` is the deliverable, and it needs facts (lawful basis, retention, who the DPO is) rather than code. | Before 6.1 processes a real application |
| **Project walkthrough guide — owed to the operator** | asked 2026-09-13 | Not technical debt; a promised deliverable. A plain-language tour of the whole repository for someone who is not an engineer: what every folder holds, what decision was made at each step, why it was made, what the alternative was, and why the architecture ended up this shape. The raw material already exists in this file's decision log — but that log is written for a coding session, not for a reader, and it is 700 lines. Written **after** the build is ready, not during, so it describes what shipped rather than what was planned. | After Phase 7 |
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
- **2026-08-23** — Phase 6, the standards-based half of intake.
  `src/recruit/intake/mail.py`. Built while the operator gathers real job-board
  captures, on a line worth keeping: **structure is standard, meaning is not.**
  MIME says how an attachment is encoded, how a non-ASCII subject is wrapped and
  what a Message-ID is for — the same for every sender alive, so it can be built
  and tested against messages the standard library generates. Which paragraph of
  a LinkedIn notification holds the applicant's name is a guess until one is in
  hand, so no per-source parser exists yet and none should be written.
  Four decisions. (1) **Provenance comes from the delivery address**, via
  plus-addressing — `jobs+linkedin@` — not from the sender's display name, which
  changes without notice while an address you published does not; an
  unrecognised tag is returned as itself rather than invented. (2) **A missing
  Message-ID falls back to the content hash.** It is unusual but legal, and the
  alternatives are dropping an application or reprocessing it on every poll
  forever. (3) **Filename sanitising assumes hostility**, because a MIME
  filename is attacker-controlled text about to become a path on a Windows
  machine: path segments, `..`, nulls and control characters, trailing dots
  (Windows strips them, so `a.pdf.` and `a.pdf` collide), absurd lengths, and
  the device names — `CON.pdf` is not a file, it is the console. The original is
  kept beside the safe version, because if a filename turns out to be an attack
  the sanitised one is not what belongs in the report. (4) **Magic bytes decide,
  not Content-Type**, reusing the ingest table one step earlier so a renamed
  executable never becomes a candidate at all.
  Nothing raises on content: an unreadable message is quarantined with its raw
  bytes kept, so one malformed mail cannot stop a batch of two hundred.
  `LIKELY_LINK_ONLY` is called out separately from `NO_ATTACHMENTS` — it is the
  case the playbook warns about, where a board sends "someone applied, click
  here" behind a login, and it is a settings problem on the board rather than a
  parsing failure. **A defect my own test caught**: the HTML flattener stripped
  `<a>` tags before reading them, and in job-board mail the URL exists *only* in
  the href while the visible text is "View application" — so link-only
  detection, the whole point of the check, would have failed on exactly the
  emails it was written for. Anchors are now unwrapped to `text (url)` first.
  41 new tests; 216 pass; ruff clean. No new dependencies — all standard library.
- **2026-08-23** — The image builds. Published to GitHub (public, for the
  operator's portfolio) and the CI written in Phase 5.2 ran for the first time:
  `test (3.11)`, `test (3.12)` and `docker` all green, 1m 11s total.
  **This closes the largest open honesty gap in the project.** Phase 5.2 shipped
  a Dockerfile, an entrypoint and a compose stack that had *never been built* —
  every container registry returned 403 from the build sandbox, and the operator
  has no Docker installed, so the quickstart was a promise with nothing behind
  it. It was recorded as open rather than assumed, and the acceptance test was
  left for whoever could run it first. A GitHub runner turned out to be that
  machine: it built the image, answered `tesseract --version` and `pdftoppm -v`
  from inside the container, brought the whole stack up with `compose up --wait`,
  and got a healthy response from `/health`. On a machine with none of the
  dependencies installed — precisely the condition hard rule 6 exists to force.
  The OCR row is narrowed rather than closed in the same breath: OCR through the
  image is proven, OCR for a native Windows install is not, and the honest
  position is that the image *is* the supported answer rather than that the
  problem went away.
  Repository is **public**, deliberately, as portfolio work. Two things were
  checked before pushing, because history is permanent: `git ls-files` confirmed
  no `.env`, no `config/organization.yaml`, no database file and no key had ever
  been committed; and the README now states plainly that the build was
  AI-assisted, that no accuracy figure has been measured, that no DPIA has been
  performed, and that the bias harness is not an independent audit. Publishing a
  hiring-decision system without those sentences would invite someone to deploy
  it on real applicants on the strength of claims nobody has verified.
- **2026-08-23** — Source detection now takes two signals, not one, and says
  which answered. Prompted by the first real capture: a test message sent to
  `parveenb2029+indeed@gmail.com` arrived with **no tag at all** — zero
  occurrences of `+indeed` in 93KB — because Gmail's address-book autocomplete
  had silently replaced the typed address with the saved contact. The `To:`
  header read `Parveen <parveenb2029@gmail.com>`, display name and all.
  The fix is not "be more careful when typing". A delivery tag is easy to lose —
  forwarding rules, clients that rewrite recipients, autocomplete — and a system
  that answers "unknown" for every application whenever that happens is useless
  in exactly the case where provenance matters. `detect_source` now falls back
  to the sender's domain (`@linkedin.com` -> linkedin, suffix-matched so
  `alerts@e.indeed.com` still resolves) and returns `(source, signal)` so the
  record says *how* it knows. The tag wins where both are present: it is the
  signal the operator chose and published, while a domain only says who sent the
  mail, not which posting it belongs to — and a board forwarding on another's
  behalf would otherwise be mislabelled.
  `source_signal` is stored rather than derived because "this is a LinkedIn
  application" is a materially different claim under each signal, and a reviewer
  asking why a candidate was routed somewhere deserves to know which one
  answered.
  Also added: `.gitignore` now refuses every `.eml` by default, with an
  exception only for `tests/fixtures/intake/redacted/`. The repository went
  public today, the first capture carried a real personal PDF, and the gap
  between "downloaded a message" and "published someone's attachment" was one
  `git add -A`. Raw captures live beside it in `raw/`, ignored, never leaving
  the machine that made them. 219 tests pass; ruff clean.

- **2026-09-12** — Self-hosting. Raised by the operator: *"fix the design first so
  everybody can have their own copy at their server, create their account and so
  on."* The system was built for one person on one machine and every default
  said so. Three things changed.
  **(1) Accounts moved into the browser.** `manage_users` has existed as a
  permission since Phase 5.1 and was never wired to a route, so adding a
  colleague meant a terminal — which a one-click deployment does not have.
  `/team` now adds people, changes roles, resets passwords and switches accounts
  off, with the guard on the route rather than the link: a recruiter who types
  the URL gets 403, and there is a test that signs in as one and POSTs to all
  three endpoints. Passwords are generated and shown once, never emailed and
  never stored readable. **The lockout guard is the part that matters**:
  `_last_active_admin` refuses to deactivate or demote the last working
  administrator, and a deactivated admin does not count as cover. On a hosted
  instance that mistake is unrecoverable — no shell, no fix, redeploy and lose
  the data.
  **(2) A public deployment with no sign-in screen now refuses to start.**
  `src/recruit/hosting.py`. The shipped config says
  `adapters.auth.provider: single_user`, which means *no login at all* — correct
  on a laptop, and on a public URL a list of everyone who applied, readable by
  anyone with the address. Nothing in the codebase knew the difference because
  until now there was nowhere to deploy it; a deploy button makes that gap
  reachable by accident. Hosting settings are read from the environment rather
  than `config/organization.yaml`, because that file is gitignored and a hosted
  operator has a dashboard, not a shell. Render, Fly, Railway, Heroku, Cloud Run
  and Azure are detected by their own env vars so the protection does not depend
  on reading the README, `RECRUIT_PUBLIC` overrides the detection in both
  directions, and `RECRUIT_ALLOW_OPEN_CONSOLE=1` exists so an open demo is a
  decision somebody made rather than a default they inherited. The session
  cookie defaults to `Secure` on a public deployment regardless of what the
  config says — being wrong that way means nobody can sign in over plain HTTP,
  which is loud and reversible; being wrong the other way puts a session cookie
  in clear text. The refusal is caught in `recruit.web.__main__` and printed as
  a sentence, because the person reading it is looking at a hosting dashboard,
  not a traceback.
  **(3) `render.yaml` and a deploy button.** Postgres plus the existing
  Dockerfile, `sync: false` on the admin email and the API key so Render prompts
  for them at creation and nothing secret is written into a public repository,
  and no `RECRUIT_ADMIN_PASSWORD` at all — it is generated on first start and
  printed to the service log once. A test parses the blueprint and fails if
  authentication is ever switched off in it, because the blueprint is the button
  and if it is wrong then everyone gets it wrong. `db.session.normalise_url`
  rewrites `postgres://` and bare `postgresql://` to `postgresql+psycopg://`:
  every managed platform emits one of those, neither works with the psycopg 3
  this project ships, and the alternative is every operator hand-editing a URL
  the platform generated and getting `ModuleNotFoundError: psycopg2` when they
  do not.
  **Three defects worth keeping.** (a) The first audit sentence read *"Boss
  created an account for S***[14]."* — `append_audit` masks any key named
  `email` under BR-06. That rule protects *candidates*; an operator account is
  system identity, the same class of fact as the `actor` column, which has
  always stored a staff address in full. The key is now `account`, and the
  exemption is a named comment beside `MASK_KEYS` rather than something a future
  reader has to infer. The exact address moved into the technical block, not
  out of the page — two different addresses can tidy to the same display name.
  (b) **A browser screenshot caught what 256 tests did not**: the people table
  showed `Priya.Nair` while the activity log called the same account
  `Priya Nair`, because the route fell back to `email.split("@")[0]` and the log
  went through `humanize`. Fixing it by importing `humanize` into `bootstrap`
  would have dragged FastAPI into a core CLI and broken hard rule 9, so the
  tidying rule moved to `recruit/names.py` (standard library only) and
  `tests/test_packaging.py` now runs bootstrap with fastapi, starlette, uvicorn
  and jinja2 blocked at import. That is the fourth packaging defect invisible to
  a machine that already had the libraries. (c) The entrypoint ignored `PORT`,
  which every managed platform sets and expects to be listened on; a service
  that ignores it is marked unhealthy and restarted forever.
  Verified by running it, not by asserting it: bootstrap, console, sign-in,
  `/team`, adding a person, the generated password working, the lockout refusal
  arriving as a 400 with a sentence on screen, the audit rows, and the `Secure`
  attribute actually present on the cookie — all against a live server with
  `RECRUIT_PUBLIC=1`, plus four browser screenshots. 256 tests pass; ruff clean;
  branding gate green. **Not verified**: a real Render deploy. The blueprint is
  parsed and asserted but has never been submitted to Render, and that is in the
  deferred register rather than assumed — the same way the Docker image was
  carried as open for a day until CI built it.

- **2026-09-13** — A free way to actually run it, and a console worth looking at.
  Two asks from the operator in one sitting: *"the interface is pretty drab like
  a file not an exciting website"*, and *"i want the visitors to be able to
  download the app and use it for personal use on their own server in a fully
  functional way."*
  **The second one turned out not to be a licensing or packaging problem.** The
  repository is public and MIT; anyone could already download it. The wall was
  the model: `AnthropicLLM` needs a paid key, so a stranger who cloned this got
  `FakeLLM`, the sample queue, and no way to read an actual resume. That is a
  demo wearing a product's clothes. `OllamaLLM` closes it — a model on the
  operator's own machine, no key, no card, no quota.
  **Why Ollama and not a free hosted tier.** The free tiers of the big providers
  are free because they train on what you send. Gemini's, checked today, says so
  outright. A resume is a named person's address, phone number and employment
  history, handed over for one purpose; putting it into a training set to save a
  few pence is not a trade an employer may make on a candidate's behalf. So the
  choice is local or paid, and the config comment, the README and the
  `NotImplementedError` all say why rather than leaving it as an unexplained
  gap. The accuracy trade is stated in the same breath, in all three places: a
  model small enough for a laptop reads a resume less reliably than a frontier
  one. Free and good are different axes and the operator picks.
  Hard rule 2 holds without an exception: Ollama's `format` takes a JSON schema
  and constrains decoding to it, which is the same guarantee as Anthropic's
  forced tool use — `test_the_schema_is_sent_as_a_constraint_not_as_a_request`
  asserts the schema arrives in `format` rather than in the prompt, because the
  difference is invisible from outside until the day a model ignores it.
  Two decisions worth keeping. (1) **`model_id` carries the digest**, not just
  the tag. `llama3.1:8b` is a moving pointer exactly like a cloud alias; pull it
  next year and the weights differ under the same name, and BR-05 exists so that
  "which model rejected this candidate" has an answer. The lookup is best-effort
  and a failed one never fails an extraction. (2) **Standard library `urllib`,
  no `ollama` package.** Two calls against a documented local API do not justify
  a dependency when hard rule 9 promises the pipeline installs with no extras.
  The two errors a first-time user will actually hit — daemon not running, model
  not pulled — are tested for their *wording*, not just their type: one names
  `ollama serve` and states plainly that nothing is sent over the internet, the
  other names `ollama pull <model>`. 11 new tests against a real HTTP server
  rather than a mocked client, because this adapter is almost entirely
  transport. 268 pass; ruff clean.
  **The redesign.** Warm paper and warm ink instead of enterprise grey, a
  display serif against a humanist sans, cards with soft shadows, one terracotta
  accent, and a sign-in screen that says what the product is rather than only
  taking a password. Webfonts load from a CDN with a full system stack behind
  them — an improvement, not a dependency, which is the only basis on which a
  container-first app should reach out at all.
  **Dark mode had never worked.** `data-theme="light"` was hardcoded on `<html>`
  since Phase 3.5, so `:root:not([data-theme="light"])` could never match and
  the entire dark palette sat dead in the stylesheet. It works now, with a
  three-state control — system, light, dark — because a toggle that only knows
  on and off takes away "follow my laptop" the first time it is touched. The
  dark palette is written once in a Jinja `set` and emitted into both selectors;
  two hand-maintained copies of twelve colours is how a theme ends up
  half-applied. A pre-paint inline script reads the saved choice so dark-mode
  users do not get a white flash on every page.
  **Two defects the screenshots caught.** White text on the dark-mode accent was
  unreadable — dark mode lightens the accent to stay visible against a dark
  page, at which point `#fff` on it fails contrast. What goes *on* the accent is
  now its own token that flips with the theme. And a single-letter display name
  stacked above "Administrator" in the header read as a rendering fault rather
  than a person; it is one line now.
  Also this sitting: the branding gate caught a hardcoded Windows path in a
  docstring I had just written, which is the gate working on its author.
  And `render.yaml` was pointing at Render's free Postgres, **which deletes
  itself 30 days after creation** — a demo that would quietly die a month after
  being set up, at precisely the moment nobody is watching it. The blueprint and
  the README now say so in those words and walk through pointing `DATABASE_URL`
  at a free Neon database instead, which has no timer.

- **2026-09-14** — `field_confidence` becomes a list, because a grammar cannot
  constrain an object key. Found by the operator running the first real
  extraction any model has ever done on this project — a 3B model, on their own
  laptop, no key. It read the name, email, two roles and nine skills correctly
  and then failed validation **31 times**, every failure the same: the schema
  asks for `field_confidence` keyed by JSON Pointer, and the model returned
  `full_name` where it should have returned `/personal_info/full_name`.
  **The instinct — "use a bigger model" — is wrong, and worth writing down.**
  Structured output works by compiling the schema into a grammar the model must
  decode within. A grammar constrains the shape and type of a *value*. It cannot
  constrain an arbitrary object *key* to a regular expression, in Ollama or in
  Anthropic's tool use. So `propertyNames: {pattern: ...}` was never enforced —
  it was a request the model was free to ignore. A larger model would ignore it
  *less often*, which is worse than failing consistently: intermittent
  correctness is the kind you cannot build a review process on.
  So the fix is the schema. `field_confidence` is now a list of
  `{pointer, confidence}` pairs, where `pointer` is an ordinary string property
  the grammar does constrain. **This is the Phase 3.6 move again** — there, the
  fit-score fields were stripped from the model-facing schema so the model was
  incapable of returning a score; here the pointer moves into a position where
  getting the format wrong stops being possible rather than being discouraged.
  Worth noting what this says about the older work: no real model had ever met
  this schema. The Anthropic path still has not run. Every green test to date
  was `FakeLLM` answering with a hand-written fixture whose pointers were
  correct because a person typed them. The fixture was right and the contract
  was unenforceable, and only a real model could tell those apart.
  **Both shapes are read, forever.** `src/recruit/confidence.py` is the single
  place that knows, and every call site — extract, validate, the review console
  — goes through it. Extraction envelopes are evidence and the audit log is
  append-only; a run recorded last month is a record of what happened, not a
  file to migrate. A console that could not open it would make the older half
  of the archive unreadable, which is the opposite of what an evidence trail is
  for. Verified by writing an old-shape envelope into a real database and
  opening it in a running console: confidences rendered 0.99, 0.98, 0.94 as
  they always did.
  The worked example in `03_Extracted_Data/Prompt.md` changed in the same
  breath, with a test asserting it matches the schema. Models imitate the
  example at least as strongly as they obey the schema, so an example left
  showing the old shape would actively teach the mistake the change exists to
  prevent. 277 tests pass; ruff clean; branding and schema gates green.

  **Postscript, same day — the fix cost five minutes of somebody's laptop.**
  With the pointer pattern on a string property, the first real run **did not
  finish**: `Unexpected failure: timed out` after 300 seconds. The regex is why.
  Structured output compiles the schema into a grammar, and `^(/[^/]*)+$` — a
  repeated group around a repeated character class — becomes a state machine
  re-evaluated at every token. The same schema without it answers in the usual
  couple of minutes.
  What makes this worth recording is *why it appeared only now*: the identical
  regex had been in the schema all along under `propertyNames`, and cost
  nothing — because `propertyNames` is one of the keywords grammar conversion
  ignores. The same silence that left the pointer format unenforced for the
  project's whole life was also what made it free. Moving the constraint
  somewhere it is honoured is what made it expensive. That is a fair price and
  a real trade, not a regression.
  So `prompts.without_regex_constraints` strips `pattern` from the schema the
  model is handed, and only that: the SHAPE stays enforced — a list of objects,
  each with a `pointer` string and a `confidence` number — while the pointer's
  *format* is taught by the worked example and enforced afterwards by VR-02.
  Getting it wrong now costs a clear finding on the review screen instead of an
  unexplained stall. `format` is left in place; date and email are cheap hints,
  not compiled expressions.
  **A second defect in the same run.** `socket.timeout` is `TimeoutError`,
  which is **not** a subclass of `URLError` — so it walked straight past the
  adapter's connection handler and surfaced as "Unexpected failure: timed out".
  True, useless, and indistinguishable from a crash. Timeouts now name the
  three things that actually help, cheapest first, and a bare `OSError` — a
  connection dropped mid-answer, usually Ollama stopping or running out of
  memory — gets its own sentence too. Both found by the operator running it;
  neither reachable from a test that had not first been told what to look for.
  279 tests pass.

  **Second postscript — the pointer becomes a menu.** Stripping the regex fixed
  the stall and the run completed, with the shape correctly enforced: the errors
  moved from `field_confidence` to `field_confidence/0/pointer`, which is the
  grammar doing its job. The model then filled that string with `email`,
  `company`, `degree` — field names, not paths, for the second time. Free text
  in, field names out, and `company` is ambiguous anyway: it occurs once per job,
  so nothing recovers afterwards what was meant.
  `prompts.with_pointer_enum` replaces the pointer's type with an **enum of every
  pointer the profile schema actually admits** — 136 of them at an array bound of
  ten, 3.5KB, derived from `resume.schema.json` at request time rather than
  hand-listed so it cannot rot. An enum in a grammar is a flat alternation:
  cheap, unlike the nested-quantifier regex that caused the timeout. The wrong
  answer stops being reachable rather than being discouraged.
  **That is now three times this project has taken the same route** — strip the
  score fields so a fit score cannot be returned, list-shape `field_confidence`
  so the key format can be constrained, enumerate the pointers so an invented one
  cannot be written. The pattern is worth naming: when a model keeps getting
  something wrong, the useful question is not "how do we ask better" but "why is
  the wrong answer expressible at all".
  Two schemas, two audiences, stated because it looks like duplication and is
  not: the model gets a menu with no regex, validation keeps the pattern, so an
  envelope arriving from anywhere else — an older run, a different adapter, a
  hand-edited file — is still checked properly. The array bound is a real limit
  and is documented as one: a candidate with more than ten jobs cannot have
  confidence reported for the eleventh. 283 tests pass; ruff clean.

  **Third postscript, and the most important thing found all week.** With the
  pointer menu in place the run came back clean: `status SUCCESS`, validation
  `PASS`, confidence 0.92, **human review not required** — and *zero evidence
  citations*. One warning, which did not block.
  That is the exact combination this project exists to make impossible. VR-03 is
  the hallucination defence; with no citations it checked nothing, and the
  extraction arrived wearing the same green tick as one that had been verified
  line by line. Every field in it was the model's unsupported word, and the
  screen said it was fine. **An extraction that cannot be checked is more
  dangerous than one that fails**, because a reviewer has no reason to look
  harder at it.
  "No evidence citations" is now an **ERROR**, so it blocks: status drops to
  PARTIAL and a human is required. The model's own confidence is no answer to
  this — it is self-reported, `confidence.calibrated` is still false, and a model
  fabricating an employer is not less sure while doing it. 0.92 from a 3B model
  with nothing to back it is not evidence of anything.
  This was a WARNING from Phase 3.3 onward and nobody noticed for three weeks,
  because `FakeLLM`'s fixture has always carried three citations — so the branch
  never ran in anger. The same shape as the `field_confidence` bug: a contract
  that looked enforced, a fixture that was too well-behaved to test it, and only
  a real model able to tell the difference. Third defect the operator's own run
  has surfaced in two days. 284 tests pass; ruff clean.

  **Fourth postscript — why there were no citations, and it was never the model.**
  The obvious reading of "0 citations from a 3B model" is that the model is too
  small. It is not. **`results` sets `additionalProperties: false` and `evidence`
  was not one of its properties**, so the grammar would not let any model emit
  the key at all — while `extract` did `results.pop("evidence", [])` and
  collected an empty list every single time. VR-03, described in this file as the
  most important code in the project, **had never once been handed real model
  output**, from Phase 1 until today.
  Nothing caught it because `FakeLLM` returns its fixture object directly,
  without passing it through the schema, and that fixture has always carried
  three citations. A fake that is not bound by the contract will tell you the
  contract works. There is now a test that validates the fixture against the real
  schema, which fails loudly the next time the two drift.
  `evidence` is declared in the results schema, and `prompts.with_required_evidence`
  adds `minItems: 1` and `required` **to the model-facing copy only** — the stored
  schema cannot require it, because `extract` lifts the array onto the envelope
  and by validation time the key is legitimately gone. The same transform strips
  `char_start`, `char_end` and `match_score`: the validator fills those in while
  it is already searching for the snippet, and asking a model for a character
  offset asks it to count, which is the one thing it is reliably bad at. A wrong
  offset highlights the wrong words in the console, which is worse than none.
  **Fourth time, same move.** Prose in the system prompt asked for citations and
  the schema permitted `[]`, so the model took the schema at its word — exactly
  like the pointer format, one layer up.
  **A fifth defect, mine, found in the same hour.** Inlining
  `envelope.schema.json#/$defs/evidence_ref` left its *own* internal refs —
  `#/$defs/json_pointer`, `#/$defs/confidence` — pointing at nothing, because the
  results schema has no `$defs`. A validator raises on that, which is the loud
  half; the dangerous half is silent, since a provider compiling a grammar leaves
  an unresolvable field simply unconstrained. `dereference` now carries the
  source document's definitions across, and only the ones still pointed at, since
  the schema travels on every request. A test asserts no `$ref` in a loaded
  schema points at nothing.
  Also worth recording from the operator's run: the 3B model returned
  `rahl.sharma@email.com` — the `u` dropped out of a name it had read correctly
  two lines earlier. A single wrong character in the one field used to contact a
  candidate, invisible to every check in the system *except* the one that had
  been disconnected since Phase 1. 289 tests pass; ruff clean.

  **Fifth postscript, and the one worth telling people about. VR-05.**
  With citations finally flowing — ten of them, VR-03 satisfied, validation
  `PASS`, zero findings, `SUCCESS`, no review required — the extracted email
  was `rahl.sharma@email.com`. One character missing from the only field anyone
  would use to contact that candidate, and every check in the system passed it.
  **VR-03 proves a snippet exists in the document. It proves nothing about the
  field the snippet was cited for.** The model quoted
  `Email: rahul.sharma@email.com` correctly — a real snippet, found in the
  source — and wrote something else into the field. The citation was honest and
  the extraction was wrong, and nothing in four layers of validation was looking
  at the gap between them.
  `VR-05` closes it: for every citation carrying a pointer, the value at that
  pointer must be supported by the snippet cited for it. Two classes,
  deliberately. **Verbatim fields** — email, phone, links — must match character
  for character, because fuzzy matching is precisely wrong there:
  `rahl.sharma@email.com` scores 0.95 against the real address and reaches
  nobody. **Everything else short and scalar** is fuzzy, since tidied
  capitalisation is legitimate. **Paraphrased fields are skipped entirely** —
  a summary is meant to differ from its source, and a rule that fires on correct
  work is a rule somebody switches off.
  Worth naming what this run actually demonstrated: the hallucination defence
  had been pointed at the wrong half of the problem. Fabricating a quote is one
  failure; misreading a real one is another, it is more common, and it looked
  identical from every angle the system had. 293 tests pass; ruff clean.

  **Sixth postscript — VR-05 did not fire, and the reason was the same shape.**
  The next run produced six citations, validation green, and the same
  `rahl.sharma@email.com`. VR-05 said nothing because **the email was not among
  the six**, and `pointer` on a citation was *optional*, so a quote could be
  attached to nothing at all — reading as evidence, counting as evidence, and
  checkable against nothing. Two holes, one habit.
  `pointer` is now **required on every citation and drawn from the same menu of
  real paths**, so a citation always lands on something. And `VR-06` closes the
  other half: the candidate's name, email and phone must each be cited if they
  were extracted. **A field nobody cited is exactly as unverified as one cited
  wrongly** — the only difference is that the first kind leaves no trace to
  argue with, and silence reads as success.
  Those three fields, and not the rest, because a wrong one of them is not a
  quality problem: it is a candidate who never hears back, or the wrong person
  contacted about someone else's application.
  **The rule immediately failed our own reference extraction**, which cited a job
  title, an employer and a skill but neither the name nor the phone. That is the
  fixture being unrealistic again — the third time today it has been too
  well-behaved to catch anything — so it now cites the contact fields, and a
  test pins the count as "at least", since a hard number turns every future rule
  into an unrelated failure. 296 tests pass; ruff clean.

  **Seventh postscript — the enum was decoration, and the email fixed itself.**
  Two things in one run. The email came back **correct** —
  `rahul.sharma@email.com`, after three runs of `rahl` — and I wrote here that
  requiring citations had made the model read more carefully.
  **That was wrong, and the next run said so**: `rahl` again, same model, same
  document, same schema. What I had was one sample of a variable process, and I
  reported it as an effect. Correcting it rather than deleting it, because the
  mistake is the useful part: a 3B model gets this character right sometimes and
  wrong sometimes, which is *worse* than getting it wrong every time — an
  intermittent error is the kind a reviewer stops expecting. The citation
  requirement exposes the error when the field is cited. It does not fix it, and
  nothing here has yet shown that it improves accuracy at all. That claim needs
  the golden set (4.1), not an anecdote.
  The bad one: every pointer came back as the *value* — `"RAHUL SHARMA"`,
  `"Infosys Limited"` — and six VR-02 errors with it. The enum I had just added
  did nothing, because `pointer` arrives from the envelope schema as
  `{"$ref": "#/$defs/json_pointer"}` and I **added `enum` beside the `$ref`**
  instead of replacing the property. Grammar conversion follows the reference
  and drops the sibling, so the constraint was decoration: present in the
  schema, absent from the grammar, and indistinguishable from a working one
  unless something goes looking. My own test passed, because it asserted the
  enum existed rather than that it applied.
  The property is replaced outright now, and both tests assert no `$ref`
  survives beside it. **This is the second time today a schema keyword was
  silently ignored** — `propertyNames` was the first — and the lesson is the
  same one at a different altitude: a constraint that the grammar does not
  compile is a comment. When something must be enforced, the test has to check
  the shape of what is *sent*, not the shape of what was intended.
  296 tests pass; ruff clean.

  **Eighth postscript — a true warning that was still noise.** The same run
  warned `candidate_id` was "not supported by the text cited for it, similarity
  0.20". Perfectly true: `candidate_id` is passed in on the command line and
  appears in no resume ever written, so the comparison can only fail. A warning
  that is correct, unactionable and unavoidable is how a reviewer learns to skim
  past the warnings that matter — so `SYSTEM_SUPPLIED_FIELDS` skips the values
  we supplied ourselves. The `degree` warnings in the same run are left standing:
  those are the model genuinely citing text that does not contain the value it
  extracted, which is exactly what VR-05 is for. 297 tests pass; ruff clean.

- **2026-09-14** — Phase 8.0. The first account moves into the browser, and why
  that needed a security decision rather than a form.
  Asked for by the operator, who wants the download path usable by people who
  do not code: *"we need to hand it to them on a platter."* Auditing the
  easiest existing route — the Render button — found exactly two steps a
  non-technical person cannot complete: pasting an API key, and **opening a
  service log to find the generated first-run password.** The second is this
  prompt; the first is what the installer is for.
  **The hole this opens, stated before the fix.** A console with no accounts is
  a console anyone can claim. Between an instance starting and its owner first
  visiting it, whoever reaches `/setup` first becomes its administrator — and on
  a public URL that is everyone. This is not theoretical; it is how self-hosted
  software gets taken over.
  **So the rule is split by where the thing is running**, reusing
  `hosting.is_public()` rather than growing a second definition of "public".
  On a machine somebody is sitting at, setup is open: whoever can reach
  localhost is already the person at the keyboard, and a token there protects
  nothing while costing the entire benefit. On a public deployment setup needs
  a token supplied out of band — the operator has a dashboard, which is the one
  channel a stranger holding the URL does not have. `render.yaml` uses
  `generateValue: true` so the platform invents it, nothing secret is written
  into a public repository, and nobody is asked to make up a password in a web
  form before the service has finished deploying.
  **Fail closed, as everywhere else in `hosting`.** A public deployment with no
  token configured gets *no setup page at all* and falls back to `bootstrap`.
  An unset variable is somebody who has not made a decision, and guessing
  "open" on their behalf is how the window gets left open by accident instead
  of on purpose. A test asserts the blueprint generates the token rather than
  carrying a literal one.
  **404, never 403 — three times over.** Setup that is finished, setup that is
  not configured, and a wrong token all answer identically. A 403 would confirm
  there is a configured console at this address, which is a true fact about
  somebody else's system that a stranger should not be able to harvest by
  probing; and "wrong token" specifically tells a prober that guessing is worth
  continuing. Same reasoning the Phase 7 plan reaches for on cross-workspace
  reads, arrived at independently here, which is mildly reassuring about the
  rule.
  Three smaller decisions. The token is compared with `hmac.compare_digest` and
  an unset variable can never be satisfied by a missing parameter — the
  empty-versus-empty case is the one that quietly opens a door. The policy
  lives in `src/recruit/firstrun.py`, not in a route, so it can be read and
  tested without starting a web server. And **`OBVIOUS_PASSWORDS` moved from
  `users.py` into `auth.py`**: the wordlist refusal had existed on the command
  line since Phase 5.1, and a browser path that accepted `password1` would mean
  the enforced policy depended on which door somebody walked through. A rule
  enforced on one of two paths is not a rule.
  `bootstrap` no longer exits 1 when no administrator email is supplied — it
  says the console will offer a setup screen and returns 0. That was correct
  until there was a second way in; a container that dies on a missing optional
  variable is precisely what a non-technical person cannot diagnose. It still
  fails loudly in the one case where *neither* door is open, because exiting 0
  there would leave a healthy-looking console nobody can ever sign in to.
  **A real defect the tests caught, on the database everyone actually gets.**
  The route wrote its audit row on the request's session and then called
  `auth.login`, which opens its own. The first write takes a lock the second
  waits on, and on SQLite — the default install, per hard rule 9 — that is a
  deadlock rather than a slowdown. Login now happens first. Postgres would have
  hidden this completely.
  Verified by running it, not by asserting it: bootstrap on an empty database,
  the redirect from `/` to `/setup`, the wordlist refusal on screen, a real
  sign-up returning a session cookie, the queue rendering as "K / Administrator",
  `/setup` answering 404 immediately afterwards, the audit row
  (`auth.first_run_setup`, actor `k@example.com`, `via: browser`), and then the
  whole thing again with `RECRUIT_PUBLIC=1` where no token and a wrong token
  both 404 while the right one opens. 318 tests pass; ruff clean; branding gate
  green.

- **2026-09-14** — Phase 8 research: how a non-coder gets this on Windows.
  Recorded because it changes the plan and because two of the four findings are
  counter-intuitive enough to be re-litigated otherwise.
  **(1) Paying would not have solved it.** EV code-signing certificates stopped
  conferring SmartScreen reputation in 2024; Microsoft's own documentation now
  says paying the premium for that purpose "is no longer justified". A
  $400/year certificate still shows "Windows protected your PC" until
  reputation accrues over weeks and hundreds of clean installs. The operator's
  constraint — no money — costs less than it appears to.
  **(2) The Microsoft Store is free and removes the warning entirely.**
  Individual developer registration was $19 and the fee was waived in September
  2025. Store apps are re-signed by Microsoft and carry full reputation, so
  there is no SmartScreen prompt at all. The price is not money: it is
  government-ID-and-selfie identity verification plus Store certification. That
  is the operator's call to make and nobody else's, and it stays open — the
  packaging is to be built so a Store submission is a later step rather than a
  rewrite.
  **(3) Unsigned is shippable but hostile to exactly our audience.** A plain
  installer from GitHub Releases costs nothing, but every visitor sees a
  security warning, and unsigned files cannot inherit reputation — **every new
  version starts from zero.** To a non-technical person that prompt reads as a
  virus alert, which is precisely the reaction we are trying to avoid.
  **(4) Ollama is MIT licensed**, so the inference engine can legally be
  redistributed inside an installer. That is what removes the API-key wall: no
  account, no card, and nothing about a candidate leaving the machine. Note as
  a risk to verify rather than assume: Ollama's own tracker carries an open
  issue about silent/administrative installation being unreliable, so the
  unattended-install path must be proven on a real Windows machine before the
  design depends on it.
  **Where the build has to happen.** Neither the coding environment (Linux) nor
  the operator's bridge (also a Linux VM) can produce a Windows binary, so the
  installer is a GitHub Actions artifact from a `windows-latest` runner. Same
  machine that built the Docker image when nothing local could, and the same
  reason it satisfies hard rule 6: a runner has none of the dependencies
  installed.

- **2026-09-15** — Phase 8.1. The demo page, and the question that produced it.
  The operator asked something better than "where do I host it": *"how will a
  visitor get a feel that wow this might come in handy for me — and this
  visitor is gonna be a total layman."*
  **The answer was that the comprehension moment already existed and was four
  clicks behind a login.** Click an extracted detail, watch the exact line of
  the CV light up. A non-technical person needs no explanation for that: they
  see the machine point at where it got something, and understand in one
  gesture both that it read the document and that it cannot simply invent
  things. Reaching it required finding the URL, signing in, knowing what a
  review queue is, picking a candidate, and thinking to click a field. Nobody
  does that. So the fix was not a better deployment — it was putting the moment
  on the first screen.
  **`/demo` is public, replays recordings, and touches no database.** Three
  decisions, each load-bearing. It calls no model, because a live call on the
  one screen an employer looks at is slow, needs a key or a running Ollama, and
  could produce a *different, worse* answer than the one that was checked. It
  reads no database, so it works on a freshly deployed copy whose database is
  empty — which is precisely when it has to work — and no visitor can change
  what the next visitor sees. And it says in plain words that it is a
  recording, because a demo implying live inference when there is none is a
  small lie of exactly the kind this README spends its length refusing to tell.
  Worth noting what makes a public page safe here at all: **there is no upload
  route anywhere in this console.** Resumes enter through the command line.
  That is not a control added for the demo; it is the absence of a route, which
  is the strongest kind. A stranger cannot put a real person's CV on the
  operator's instance because there is nowhere to put it.
  **The second recording is the product.** One panel shows a clean read. The
  other reproduces the September defect: `rahl.sharma@email.com`, one character
  short, with the model's citation still quoting the correct line — the honest
  quote attached to the wrong value, which is what VR-05 exists for. Nothing is
  simulated; `tools/bake_demo.py` runs the real validator and **refuses to bake
  at all if VR-05 stops firing**, because the alternative is a page that
  silently starts showing a wrong answer with a green tick, which is the exact
  failure it exists to dramatise.
  The best line on the page was found by looking at it rather than by writing
  it: beside the wrong address the console reports **98% sure**. Confident and
  wrong simultaneously, on screen, which makes the argument for checking
  against evidence better than any paragraph could. `confidence.calibrated` is
  still false and this is what that means in practice.
  **Three defects a screenshot caught and no test would have.** (1) The profile
  is stored alphabetically, so the candidate's *name* sorted below
  `certifications` and `gpa` and was scrolled off the top — on a page whose
  headline is about reading a CV. Display order is now an explicit decision in
  the route rather than an accident of `json.dumps(sort_keys=True)`. (2) The
  opening highlight called `scrollIntoView`, which dragged the field list past
  the email on the page whose entire text says *look at the email*. It no
  longer scrolls on load, only on a click. (3) The page rendered
  `candidate_id` — a reference this system generates, present in no resume ever
  written — among details genuinely quoted from the document. The review
  console is right to show it; this page makes a different claim, so
  `SYSTEM_SUPPLIED_FIELDS` are dropped here. That is the fifth time in this
  project a browser screenshot has found something the suite could not.
  Also fixed in passing: `gpa` title-cased to "Gpa", which reads as a typo and
  quietly undermines every correct label beside it.
  `tests/test_demo.py` mostly checks the **claims** rather than the rendering,
  because this is the one page that makes assertions in prose to people who
  cannot verify them — that the misread is still caught, that the citation
  still quotes the correct address, that the page still says a person decides,
  and that `samples/` is not excluded from the Docker image. That last one is
  the `.dockerignore` shape again: an image that builds, starts, serves every
  other page, and 404s on the one page everybody was linked to.
  333 tests pass; ruff clean; branding gate green. Verified in a real browser,
  both panels, signed out.

- **2026-09-15** — Phase 8.2. Three things the operator caught by using it.
  **(1) "Review Console" was breaking the fourth wall.** That is what the
  people who build the software call it; nobody using it thinks of their
  morning as operating a console. The bar now carries the organization's own
  name where one is configured — `console.name`, falling back to
  "<display_name> Hiring", then plain "Hiring" — and the letter in the mark is
  derived from it rather than a hardcoded "R". A template global, not a value
  each route passes, because a name that depends on every route remembering it
  is a name that will be missing from the next screen somebody adds.
  Also removed: **"Not signed in"**, which told a person staring at a sign-in
  form something they already knew. Nothing beats noise.
  **(2) A password you cannot see, typed twice, is how people lock themselves
  out** of an account they made ninety seconds earlier. Every password field
  now has a Show/Hide button — one implementation in `base.html`, because
  sign-in, first-run setup and reset all need it and three copies would drift.
  The state is deliberately **not** remembered between page loads: a box left
  readable by a choice made last week, on a screen now being shown to a
  colleague, is a worse default than one extra click. Worth stating plainly in
  the comment, since "show my password" sounds like a weakening and is not: it
  changes what the screen displays, never what is transmitted or stored.
  **(3) Forgotten passwords, with nothing able to send email.** Every product
  answers this with a link in an inbox. This one **cannot send email at all** —
  Phase 6 receives applications, it does not send, and there is no SMTP
  configuration to borrow. A page promising a message that never arrives is the
  worst screen a product can have, so `/forgot` says so and offers the two real
  routes instead.
  **The new distinction: `hosting.is_from_this_machine(client_host)`, which is
  narrower than `is_public()` and not a substitute for it.** `is_public()` asks
  what kind of deployment this is; this asks who is knocking. At the keyboard,
  a self-service reset is offered, because that person can already open the
  database file and run `recruit-users set-password` — a browser form grants
  them nothing new, and withholding it only punishes the person who installed
  it. From anywhere else there is no form at all. The gap that makes the
  narrower question necessary: **a console started with `--host 0.0.0.0` on a
  laptop sets no platform environment variable**, so `is_public()` calls it
  private while every machine on the office network can reach it. There is a
  test with a client on 192.168.1.44 proving the POST is refused, not just the
  form withheld.
  One deliberate inconsistency worth recording: the sign-in form hides whether
  an account exists, and this form does not — it says "No user with that
  email". Silence there protects against harvesting by strangers; here the
  request already came from the machine, where the accounts can simply be
  listed, so being unhelpful buys nothing and costs somebody a confusing
  afternoon.
  A test caught my own copy: the page explaining that nothing would arrive in
  an inbox contained the phrase it was warning about, and the assertion
  guarding against a future "check your inbox" fired on it. Reworded the page
  rather than weakening the test.
  Also: an inline SVG favicon, because a missing one logs a 404 on every first
  page load — noise in the one place an operator looks when something is
  actually wrong. Found in the operator's own server log.
  348 tests pass; ruff clean; branding gate green. Verified in a browser:
  header renamed, Show/Hide revealing a typed password, `/forgot` offering the
  form on loopback.
  **Still owed from this sitting:** the operator's "I want some visuals, this
  is too drab" — the sign-in and demo screens are all type and no picture. Not
  started; it is a design pass, not a defect.
