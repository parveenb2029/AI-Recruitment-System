# AI Recruitment System

Read a resume, pull out the facts, score it against a job's requirements, and put
the result in front of a human — with a quote from the document behind every
claim, and a record of who decided what.

It is a screening assistant. **It does not decide anything.** Every candidate-
affecting outcome is approved, rejected, or escalated by a named person, and the
record of that is append-only.

---

## Try it in ten minutes

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/). You
do **not** need an API key, a database, or Python.

```bash
git clone <your-copy-of-this-repo> AI-Recruitment-System
cd AI-Recruitment-System
docker compose up
```

First run takes a few minutes to build. Then open **http://localhost:8000**.

You will see a review queue with one candidate in it, produced by running the
real pipeline over the sample resume with a **fake model** — no key, no cost, no
network call. Click the candidate. Every extracted field is clickable, and
clicking one highlights the exact span of the resume it came from. Approve it,
reject it, or escalate it, then open **/audit** and watch what you just did
appear in a log that cannot be edited or deleted.

That is the whole product in three minutes. The remaining seven are below.

**Watch the terminal on first start.** If the config asks for real accounts, an
administrator is created and its password is printed **once**:

```
  ================================================================
   FIRST-RUN PASSWORD — shown once, never stored in readable form

     email     admin@localhost
     password  HRkcijWsfJZkK-7b
  ================================================================
```

Stop it with `Ctrl+C`, then `docker compose down`. Add `-v` to erase the
database too.

### Without Docker

Python 3.11 or newer. This path uses SQLite, so there is no server to install
and no database driver to compile.

```bash
pip install -e ".[web]"
cp config/organization.example.yaml config/organization.yaml
python -m recruit.bootstrap --email you@example.com
python -m recruit.seed
python -m recruit.web
```

Same console, at http://localhost:8000.

---

## What it does, and what it does not

| It does | It does not |
|---------|-------------|
| Read PDF, DOCX and TXT resumes, including scanned ones (OCR) | Decide who to hire, or reject anyone by itself |
| Extract structured facts with a quote backing each one | Produce a single "fit score" — see below |
| Check every quote actually appears in the document | Source, contact, or schedule candidates |
| Score against a job's requirements, component by component | Replace your ATS |
| Route everything to a human, with keyboard-fast review | Give legal advice, or certify your compliance |
| Keep an append-only audit trail of every decision | Guarantee an accuracy number — none has been measured |

Three of those deserve the detail.

**No single fit score.** A number like "78% match" cannot be defended when a
candidate asks why they were rejected. Instead the model judges three things
separately — must-have coverage, experience band, domain match — each with its
own evidence, and *your code* combines them using weights from your config. The
model is not even shown the fields where a total would go; it is structurally
incapable of returning one.

**Every quote is checked.** The model's own confidence is not evidence. Each
snippet it cites is fuzzy-matched back against the source text, and anything
scoring below 0.8 blocks the run as a possible fabrication. In testing this
caught an invented "Principal Engineer at Google DeepMind" (0.46) and a
plausible-but-absent AWS certification (0.52), while a real quote mangled by PDF
line breaks still scored 1.00.

**The audit log cannot be rewritten.** Not by convention — the repository class
exposes no method that mutates it, *and* a database trigger rejects `UPDATE` and
`DELETE`. Either layer alone is theatre: application rules fall to anyone with a
database prompt, database rules vanish if a migration is skipped.

---

## Using it on your own resumes

### 1. Add your API key

The demo queue is fake. Real extraction needs a model.

```bash
cp .env.example .env          # copy .env.example .env   on Windows
```

Put your key in `ANTHROPIC_API_KEY=`. Nothing else in that file is required.

### 2. Point it at your organization

`config/organization.yaml` holds every value specific to you: legal name,
contacts, retention periods per jurisdiction, confidence thresholds, and the
scoring weights. Nothing organization-specific is hardcoded anywhere else, and
`python tools/check_branding.py` fails the build if that ever stops being true.

The one you will change first:

```yaml
matching:
  default_scheme: "default"
  schemes:
    default:
      weights:
        must_have_coverage: 0.5
        experience_band: 0.3
        domain_match: 0.2
```

Weights must sum to 1.0 — the config refuses to load otherwise, because weights
that sum to 0.9 silently deflate everyone's score.

### 3. Run a resume through

```bash
python -m recruit.extract path/to/resume.pdf
python -m recruit.match --candidate <id> --requisition <id>
```

Or drop files into the queue for review:

```bash
python -m recruit.seed path/to/resume.pdf another.docx
```

### 4. Give people accounts

The example config ships with `adapters.auth.provider: single_user`, which means
**the console has no login at all** — fine on your laptop, wrong the moment
anyone else can reach it. For real accounts:

```yaml
adapters:
  auth:
    provider: "local"
```

Then:

```bash
python -m recruit.users add someone@example.com --role recruiter
python -m recruit.users list
python -m recruit.users set-password someone@example.com
```

Four roles, taken from the responsibility tables in the SOPs:

| Role | Can |
|------|-----|
| `admin` | everything, including the audit trail and user management |
| `hiring_manager` | review, **approve**, reject, escalate |
| `recruiter` | review, reject, escalate — **not** approve |
| `auditor` | read the audit trail; change nothing |

A recruiter who cannot approve is not a UI decision. The Approve button is
hidden *and* the route returns 403, and there is a test that renders the button
for a recruiter and then asserts the POST still fails.

---

## Before you use this on real candidates

This is screening software for employment decisions, which is regulated in more
places every year. `docs/compliance/` contains a DPIA template, a candidate
disclosure template, and an appeal process template. **They are templates.**
Every one carries `[ORGANIZATION TO COMPLETE]` blanks, because shipping
finished-looking legal text is worse than shipping none — someone relies on it.

Three specific things are yours, not ours:

- **NYC Local Law 144** requires an *independent* annual bias audit before an
  automated employment decision tool is used on New York candidates. This
  project includes a bias-testing harness (`python -m recruit.bias_audit`) that
  perturbs names, gender signals, university prestige, location and graduation
  year and reports per-component drift. It is a smoke test you run yourself. **It
  is not an independent audit and cannot satisfy LL144.**
- **GDPR Article 35** requires a DPIA to be *performed*, not templated.
- **GDPR Article 22** gives candidates a right to human review. The process is
  documented; the candidate-facing side of it is manual, because there is no
  candidate portal.

And one measurement that does not exist yet: **no accuracy figure has been
established.** The confidence thresholds in the config are round numbers, not
calibrated ones — `confidence.calibrated: false` says so in the file. That needs
a golden set of human-labelled resumes, which is a deliberate, tracked gap (see
`CLAUDE.md`). Until it exists, treat every number the system reports as a
prompt for a human to look, not a measurement to act on.

---

## Commands

| Command | What it does |
|---------|--------------|
| `python -m recruit.bootstrap` | Create the schema and the first administrator. Safe to re-run. |
| `python -m recruit.seed` | Fill the queue from `samples/`, using the fake model. `--force` replays it. |
| `python -m recruit.web` | Start the review console. |
| `python -m recruit.extract <file>` | Extract one document. Real model. |
| `python -m recruit.match` | Score a candidate against a requisition. |
| `python -m recruit.users` | Add, list, deactivate people; set passwords and roles. |
| `python -m recruit.bias_audit` | Run the bias harness. `--self-test` proves it can still detect bias. |
| `python -m recruit.db_init` | Schema only. `--drop` destroys everything. |
| `python tools/check_branding.py` | Fail if any organization value is hardcoded outside `config/`. |
| `python tools/validate_output.py <f>` | Validate a result against its JSON Schema. |

Each is also installed as a console script: `recruit-web`, `recruit-seed`,
`recruit-users`, and so on.

---

## How it fits together

```
resume file
   │
   ├─ ingest     magic-byte check, text extraction, OCR fallback,
   │             content hash over the SOURCE BYTES (so a pypdf upgrade
   │             cannot silently break idempotency)
   │
   ├─ extract    Anthropic tool use with a forced tool choice — the model
   │             cannot answer in prose, so there is no JSON to repair
   │
   ├─ validate   schema, business rules, evidence grounding (VR-03),
   │             cross-field consistency. Returns findings, never a bool
   │
   ├─ persist    Postgres or SQLite. Append-only audit log, PII masked
   │
   ├─ review     the console. Human approves, rejects, or escalates
   │
   └─ match      components scored by the model, combined in our code
```

Configuration, storage, LLM, ATS and auth are all behind adapters. Unimplemented
providers raise a clear `NotImplementedError` rather than silently falling back —
an organization that configures single sign-on and quietly gets password auth has
an incident, not a warning.

---

## Development

```bash
pip install -e ".[all]"
python -m pytest -q
ruff check .
```

CI runs the suite on Python 3.11 and 3.12, the branding check, schema validation
of the sample outputs, the bias harness self-test, and a full Docker build that
asserts the OCR binaries are really in the image.

`CLAUDE.md` is the project's memory: scope decisions, the hard rules, a register
of work that was deferred and why, and a dated decision log. Read it before
changing anything — several of its rules exist because the alternative was tried
and broke something.

---

## Licence

MIT. See `LICENSE`.
