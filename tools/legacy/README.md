# tools/legacy

Retired scripts, kept for provenance. **Nothing in this directory should be run.**

| File | What it was | Why it is retired |
|------|-------------|-------------------|
| `generate.py` | Produced all 136 original project documents from Python format strings. | Rewrites the entire tree from a hardcoded path. Would overwrite every hand edit. |
| `_create_docx_samples.py` | Wrote the sample `.docx` files in `samples/`. | Overwrites `samples/` from a hardcoded path. Fixtures are becoming a curated, labelled asset instead. |

Both files are byte-identical to the originals apart from a `SUPERSEDED` banner
prepended at the top.

---

## Why they are kept rather than deleted

`generate.py` is the reason the documentation looks the way it does. Sibling
documents are 84–92% identical because they came from a small number of templates
in this file, and that templating introduced defects that are still present in the
docs — identical SLAs across workflows, shared pain-point tables, an empty
`"results": {}` contract repeated eight times.

When you hit something in the documentation that looks oddly generic or
contradicts a neighbouring file, the template that produced it is in here. That
makes this directory useful as a reference while the docs are being
de-duplicated (see `CLAUDE.md`, the optional documentation cleanup phase).

Once that cleanup is finished, this directory can be deleted — the git history
will still hold it.

---

## Root stubs

Inert stubs remain at the project root as `generate.py` and
`_create_docx_samples.py`. They exist so that muscle memory — `python generate.py`
— exits with an explanation instead of destroying the project. Delete them once
the repository is committed and the habit has faded.
