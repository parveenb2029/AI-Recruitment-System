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

### Notes
- Project state at this commit: documentation blueprint, no application code.
  136 files, 112 Markdown. See `CLAUDE.md` for the roadmap.
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
