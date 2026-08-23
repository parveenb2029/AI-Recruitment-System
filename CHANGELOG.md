# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- Git repository initialized. Prior to this commit the project had no version
  control and no recovery path.
- `LICENSE` (MIT), `.gitignore`, `CHANGELOG.md`.
- `CLAUDE.md` — project context for AI coding sessions: target state, scope
  decision, pinned stack, hard rules, known documentation defects, and the
  decision log.

### Changed
- `generate.py` and `_create_docx_samples.py` retired to `tools/legacy/` and marked
  **SUPERSEDED**. They overwrite the entire tree from a hardcoded path. From this
  commit onward the documentation is hand-maintained and these scripts must not
  be run. The preserved copies are byte-identical to the originals apart from a
  banner comment (verified by checksum).
- The root `generate.py` and `_create_docx_samples.py` are now inert stubs that
  exit with an explanation if invoked, so habitual `python generate.py` cannot
  destroy the project. They can be deleted once this commit exists.
- Added `tools/legacy/README.md` explaining why the generators are kept:
  they are the templates that produced the documentation's known defects, and
  are a useful reference while the docs are de-duplicated.

- **Phase 1** — real output contracts for WF-03 and WF-04: `envelope.schema.json`,
  `WF-0{3,4}_results.schema.json`, `WF-0{3,4}_output.schema.json`, worked examples,
  and `tools/validate_output.py`. Replaces the `"results": {}` placeholder.
- **Phase 2** — `config/organization.example.yaml`, `.env.example`, adapter
  interfaces under `src/recruit/adapters/`, `tools/render_docs.py`, and
  `tools/check_branding.py`.

- **Phase 3.1** — `src/recruit/ingest.py` and `src/recruit/errors.py`: document
  validation, text extraction for PDF/DOCX/TXT, OCR fallback, content hashing, and
  a CLI (`python -m recruit.ingest <file>`). `pyproject.toml` and a 14-test suite.

- **Phase 3.2** — `src/recruit/extract.py`, `src/recruit/prompts.py`, and
  `src/recruit/adapters/llm.py`: WF-03 extraction via native structured output,
  prompt loading from the markdown specs, JSON Schema `$ref` dereferencing, and a
  `FakeLLM` that runs the pipeline without an API key. CLI:
  `python -m recruit.extract <file> [--fake]`.

- **Phase 3.3** — `src/recruit/validate.py`: four-layer validation (schema, data,
  business rules, evidence grounding). VR-03 fuzzy-matches every evidence snippet
  against the source document and flags `POTENTIAL_HALLUCINATION` below 0.8.
  Wired into the extract CLI.

- **Phase 3.4** — `src/recruit/db/`: SQLAlchemy models, repository, and schema
  bootstrap. Append-only audit log enforced by a database trigger. Idempotency on
  content hash. Per-jurisdiction retention queries. `docker-compose.yml` and
  `python -m recruit.db_init`.

- **Phase 3.5** — `src/recruit/web/`: review console with queue, detail view,
  click-through evidence highlighting, keyboard shortcuts, and audited decisions.
  `python -m recruit.seed` and `python -m recruit.web`.

- **Phase 3.6** — `src/recruit/match.py`: WF-04 matching with a decomposed,
  config-weighted score. Computed fields are stripped from the model's schema so
  it cannot return an overall score. CLI: `python -m recruit.match <profile>
  <job> [--fake]`. Completes the WF-03 + WF-04 + review console vertical slice.

- **Phase 4.2** — `src/recruit/bias/`: bias audit harness with five perturbation
  dimensions, per-component attribution, four-fifths calculation, and a
  publishable Markdown report. `python -m recruit.bias_audit [--fake]
  [--self-test] [--fail-on-bias]`. The harness is self-tested against injected
  bias.

- **Phase 5.1** — `src/recruit/auth.py`, `src/recruit/db/auth_repository.py`:
  scrypt password hashing, server-side sessions, four roles, route-level
  authorization, login/logout/audit routes, and `python -m recruit.users`.
  Compliance pack under `docs/compliance/`: DPIA, candidate disclosure, and
  appeal process templates.

- **Phase 5.2** — packaging and quickstart. `Dockerfile` (bundling Tesseract and
  Poppler so OCR needs no manual install), `docker/entrypoint.sh`, a full
  `docker-compose.yml` bringing up Postgres and the console with one command,
  `.dockerignore`, and `.github/workflows/ci.yml` running lint, tests on Python
  3.11 and 3.12, the branding check, schema validation, the bias self-test, and
  a Docker build that asserts the OCR binaries are really in the image.
- `python -m recruit.bootstrap` — idempotent first-run setup: schema, plus an
  administrator whose password is **generated and printed once** rather than
  defaulted. Safe to run on every container start.
- `RECRUIT_CONFIG` environment variable overrides the organization config path,
  so a container can point at a mounted file without editing the image.
- README rewritten for someone who has never seen the project: a ten-minute
  quickstart that needs no API key, and a "before you use this on real
  candidates" section stating plainly that the bias harness is not an LL144
  audit, that no DPIA has been performed, and that no accuracy figure exists.

### Fixed
- Retention was a flat 7 years for every artifact in every jurisdiction, which
  conflicts with GDPR storage limitation for unsuccessful EU candidates. Now set
  per jurisdiction in organization config.
- The numbered folders `01_`–`08_` were serving as documentation, pipeline stage,
  and artifact store at once. Postgres is now the system of record; the folders
  are documentation and an optional export view.
- 60 references to a fictional company ("Contoso Ltd", `*@contoso.com`,
  `recruitment.contoso.com`) across 36 files, plus `recruitment.example.com` and
  `@company.com` in 14 more. All now resolve from config.
  Nine of those files were found by `tools/check_branding.py` rather than by
  inspection — which is the argument for keeping that check in CI.
- One more of them survived until Phase 5.2: `samples/Software_Engineer.json`
  still carried a `Contoso` EEO statement in the build tree.
- `ruff check .` was not actually clean. Adding CI surfaced 165 findings in the
  retired `tools/legacy/generate.py` and an unsorted import in
  `tests/test_packaging.py`. Legacy is now excluded from lint — it is preserved
  byte-identical on purpose — and the import is fixed.

### Notes
- The project began as a documentation blueprint with no application code.
  As of Phase 3.2 it has a working ingest → extract pipeline and 29 passing tests.
  See `CLAUDE.md` for the roadmap and the deferred-work register.
- Scope for v1 fixed to WF-03 (extraction), WF-04 (matching), and the review
  console. The remaining six workflows stay documented and unbuilt.

---

<!--
Template for future entries:

## [0.1.0] - YYYY-MM-DD

### Added
### Changed
### Deprecated
### Removed
### Fixed
### Security
-->
