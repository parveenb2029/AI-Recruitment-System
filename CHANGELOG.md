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

### Fixed
- Retention was a flat 7 years for every artifact in every jurisdiction, which
  conflicts with GDPR storage limitation for unsuccessful EU candidates. Now set
  per jurisdiction in organization config.
- 60 references to a fictional company ("Contoso Ltd", `*@contoso.com`,
  `recruitment.contoso.com`) across 36 files, plus `recruitment.example.com` and
  `@company.com` in 14 more. All now resolve from config.
  Nine of those files were found by `tools/check_branding.py` rather than by
  inspection — which is the argument for keeping that check in CI.

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
