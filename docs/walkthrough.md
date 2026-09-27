# A Walk Through the AI Recruitment System

*What every folder holds, every decision that shaped it, and why it ended up
this way.*

---

## How to read this

This is not the README. The README is written for a stranger who wants to run
the thing. This is written for **you**, so that you can open any folder in this
repository and say what is in it, why it exists, and what the alternative was.

It assumes no engineering knowledge. Where a technical word is unavoidable it
is explained once, in plain English, the first time it appears.

There are seven parts:

1. **The problem** — what this was built to solve, in one page.
2. **The map** — every folder, what it holds, what it is for.
3. **The decisions** — in the order they were made, each with the alternative
   that was rejected and the reason.
4. **The one idea** — the single pattern that shaped more of this codebase than
   anything else.
5. **What is not true yet** — the honest gaps.
6. **Questions you will be asked** — and the answer that is both true and to
   your credit.
7. **How it was built** — the working method, and what it produced.

Read parts 1, 4 and 6 if you have twenty minutes. Read the rest when you want
the detail.

---

# Part 1 — The problem, and the shape of the answer

## The problem

A recruiter receives a hundred applications for one role. Reading each one
properly takes ten minutes. That is sixteen hours of work before anybody has
been interviewed, so in practice it does not happen: most applications get
fifteen seconds and a decision made on a glance.

This is bad for everybody. Good candidates are missed because their CV was laid
out oddly. Decisions get made on signals nobody would defend out loud — the
university name, the gap in the dates, the surname. And when a candidate asks
"why was I rejected?", there is no answer, because nobody wrote one down.

Language models can read a CV in seconds. That is genuinely useful. It is also
genuinely dangerous, for three reasons that this whole project is arranged
around:

1. **They make things up.** A model will report a job the candidate never had,
   confidently, in the same tone as the eleven true things around it.
2. **They misread.** More common than fabrication and much harder to spot. In
   this project's own testing, a small model read `rahul.sharma@email.com` off
   the page and wrote `rahl.sharma@email.com` into the record — one character,
   in the only field anyone would use to contact that person.
3. **Employment decisions are regulated.** New York, Illinois, Colorado and the
   EU all now have rules about automated hiring tools. "The computer said so" is
   not a defence.

## The shape of the answer

So the system is not "AI reads CVs and picks the best one". It is:

> **AI reads the CV and must show its working. A human makes every decision that
> affects a candidate. Everything that happened is written down permanently.**

Concretely, a CV goes through six stages:

| Stage | What happens |
|---|---|
| **Intake** | The document arrives — uploaded, or by email |
| **Ingest** | Text is pulled out of the PDF or Word file |
| **Extract** | The model reads the text and fills in a structured form |
| **Validate** | Four layers of checking, including quoting every claim back against the document |
| **Persist** | Everything is stored, with a permanent record of who and what |
| **Review** | A person sees it on screen, with each field linked to the exact words it came from, and decides |
| **Match** | The same treatment for scoring against a job description |

The word that matters in that table is **Validate**. Almost anyone can wire a
model to a PDF reader. The part that took the work — and the part worth talking
about — is the machinery that catches the model when it is wrong.

---

# Part 2 — The map

The repository has three distinct layers, and they arrived at different times.
Knowing which layer you are looking at explains a lot.

- **The blueprint** — the numbered folders `01_` to `10_`. Documentation,
  written first. Mostly *not* built.
- **The contracts** — `schemas/`. The precise shape every piece of data must
  take.
- **The product** — `src/`, `tests/`, `config/`, `docker/`. The code that runs.

## The root

| File | What it is |
|---|---|
| `README.md` | The front door. What it does, what it does not do, how to run it in ten minutes. |
| `DECISIONS.md` | **The project's memory.** Scope, rules, roadmap, and a long decision log. Read at the start of every working session so that decisions are made once, not re-argued. This guide you are reading is that file translated for humans. |
| `CHANGELOG.md` | What changed, per release. |
| `LICENSE` | MIT. Anyone may use it, including commercially, provided the copyright notice stays. |
| `pyproject.toml` | The parts list. Every external library the project needs, declared. |
| `Dockerfile` | Instructions for building the whole thing into a single runnable box. |
| `docker-compose.yml` | Starts that box plus a database together, with one command. |
| `render.yaml` | The one-click deploy file. Someone clicks a button, this tells the hosting provider what to build. |
| `generate.py`, `_create_docx_samples.py` | **Dead on purpose.** These are the original document generators. They now refuse to run and explain why. The real ones are quarantined in `tools/legacy/`. |
| `intake-playbook.html`, `portfolio-ledger.html` | Working documents, not part of the product. |

## `01_` to `08_` — the blueprint folders

Eight folders, one per stage of hiring: job descriptions, incoming resumes,
extracted data, match results, shortlisting, interview questions, interview
feedback, final decision.

Each contains the same three files — `Prompt.md` (the instructions given to the
model), `Example_Input.md`, and `Automation.md` (how the stage would be
automated).

**Only two of these eight are built**: `03_Extracted_Data` and
`04_Match_Results`. The other six are documented and deliberately unbuilt.

That is the single most important scope decision in the project, and it is
covered in Part 3. But note what it means for the folders: `03_` and `04_` are
*live* — the running code reads `03_Extracted_Data/Prompt.md` at the moment it
calls the model. It is not a copy. Change that file and you change the
product's behaviour. The other six are specifications nobody executes.

## `09_Prompt_Library`

Ten prompt documents — resume parser, JD matcher, candidate summary, rejection
email, and so on. A library of instructions written for the full eight-stage
vision.

**Honest note:** these documents were template-expanded and are 84–92% identical
to each other. They all share one cross-references table, so each one claims to
be used by every other one, which cannot be true. That is written down in
`DECISIONS.md` as a known defect rather than quietly fixed, because pretending the
inherited documentation is better than it is would be the first dishonest thing
in the repository.

## `10_SOPs`

Ten standard operating procedures — hiring, interviewing, data privacy, prompt
governance, prompt testing, prompt versioning, AI quality review, knowledge
management, automation maintenance, resume screening.

These are process documents: how a *team* would operate this system. They are
the part a buyer's operations lead reads, not their engineer.

## `schemas/` — the contracts

Eleven files. This folder is small and it is the backbone of the whole project.

A **schema** is a precise description of what a piece of data must look like:
which fields exist, what type each one is, which are required, and what is
forbidden. Think of it as a form with the boxes drawn, typed, and locked.

| File | What it describes |
|---|---|
| `resume.schema.json` | A candidate profile — name, contact, jobs, education, skills |
| `job_description.schema.json` | A role |
| `envelope.schema.json` | The wrapper every result travels in: status, confidence, evidence, model identity, timestamps |
| `WF-03_results.schema.json` | What extraction must produce |
| `WF-03_output.schema.json` | Extraction's result inside the envelope |
| `WF-04_results.schema.json` | What matching must produce |
| `WF-04_output.schema.json` | Matching's result inside the envelope |
| `candidate_profile.schema.json`, `hiring_recommendation.schema.json`, `interview_feedback.schema.json` | The unbuilt stages' contracts |
| `prompt_metadata.schema.json` | Versioning information attached to a prompt |

Two things about this folder are worth understanding, because they explain a
great deal of the code.

**First: the envelope is defined once.** Every workflow's output uses the same
outer wrapper — status, confidence, evidence, which model answered, when. That
lives in `envelope.schema.json` and the others point at it. The alternative was
copying those fields into each workflow's schema, which is how eight copies of a
definition end up disagreeing after the third edit.

**Second: the schema is not advice, it is a cage.** When the model is called, the
schema is handed to it as a *constraint on what it is physically able to produce*
— not as an instruction in the prompt asking it nicely. This is a hard rule of
the project and it is tested. The difference is invisible from the outside right
up until the day a model ignores the instruction, which is the day it matters.

## `src/recruit/` — the product

About 7,300 lines of Python. This is the system.

### The pipeline, in order

**`ingest.py`** (323 lines) — Gets text out of a document. PDF, Word, or plain
text; Tesseract OCR as a fallback for scanned pages.

Three decisions live here. It checks the file's **magic bytes** — the first few
bytes of a file, which say what it really is — rather than trusting the file
extension, so a renamed program never reaches the parser. It extracts Word
**table cells**, because resumes routinely put skills and dates in tables and
dropping them loses half the CV. And the document's fingerprint is taken over
**the original bytes, not the extracted text**, because extraction output changes
when the PDF library is upgraded, and fingerprinting the text would silently
break the system's ability to recognise a CV it has already seen.

**`extract.py`** (251 lines) — Calls the model and gets back a filled-in
candidate profile.

The important behaviour here is small and easy to miss: facts the *system* knows
— page count, character count, document fingerprint — **overwrite** whatever the
model claims about them. The model is not trusted to report facts we already
have.

**`validate.py`** (613 lines) — **The most important file in the project.**

Four layers of checking. The one that matters is called **VR-03**: every quote
the model gives as evidence is searched for in the original document. If it is
not there — or is only a loose match — the extraction is flagged as a possible
fabrication and blocked.

This works. It has caught an invented "Principal Engineer at Google DeepMind"
(21% similarity to anything in the document) and a plausible-but-absent AWS
certification (52%), while a genuine quote mangled by PDF line breaks still
scored 100%. That last part is why there is a text-normalisation step: without
it, the system would accuse honest extractions of fabrication because of
whitespace.

Then came a harder problem. VR-03 proves *a quote exists in the document*. It
proves nothing about **the field the quote was attached to**. The model quoted
`Email: rahul.sharma@email.com` — a real line, correctly — and wrote
`rahl.sharma@email.com` into the email field. Every check passed.

So **VR-05** was added: the value in the field must actually be supported by the
quote cited for it. Email, phone and links must match **character for
character**, because approximate matching is exactly wrong there —
`rahl.sharma@email.com` is a 95% match for the real address and reaches nobody.
Summaries are skipped entirely, because a summary is *meant* to differ from its
source, and a rule that fires on correct work is a rule somebody switches off.

And **VR-06**: name, email and phone must each be cited if they were extracted
at all. A field nobody cited is exactly as unverified as one cited wrongly — the
difference is that the first kind leaves no trace to argue with, and silence
reads as success.

Validation never returns a yes/no. It returns a report — which rule, how
serious, and exactly where in the data. A reviewer needs that; "invalid" helps
nobody.

**`match.py`** (342 lines) — Scores a candidate against a role.

This file enforces the rule that no single opaque fit score may ever exist. The
model judges three things separately — does the candidate have the must-have
skills, is the experience in the right band, is the domain right — and gives
evidence for each. **Our code**, not the model, combines those into a total using
weights from the configuration file.

Why it matters: a rejection has to be explainable if challenged. "0.62" is not
an explanation. "Meets 3 of 5 must-haves, here are the quotes, experience band
below target, domain matches" is.

It is enforced structurally, not by convention — the score fields are *stripped
out of the schema* before the model is called, so the model is incapable of
returning one. A future edit to the prompt cannot reintroduce it.

Four guard rails, all tested: weights must sum to exactly 1.0; an unweighted
component is rejected; a **missing** component is rejected rather than counted
as zero — silently scoring a missing dimension as zero would change who gets
rejected, invisibly; and every raw judgement must be between 0 and 1.

**`confidence.py`** (60 lines) — Small file, interesting story, told in Part 3.

**`prompts.py`** (393 lines) — Loads the prompts from the markdown files and
prepares the schema for the model.

This file holds the transformations that make the schema safe to send: inlining
external references (no model provider resolves them), stripping regular
expressions (one of them stalled a model for over five minutes), and replacing
free-text fields with menus of allowed values.

### Supporting the pipeline

**`config.py`** (164 lines) — Loads `config/organization.yaml` and validates it
**at startup**, so a badly configured scoring rubric fails immediately instead of
quietly mis-scoring candidates for a month.

**`errors.py`** (82 lines) — Every failure carries a machine-readable code and a
recovery line. A raw error message is not an acceptable failure mode: it tells a
recruiter nothing and gives the retry logic nothing to decide on.

**`names.py`** (31 lines) — Turns an email address into a display name. It exists
as its own 31-line file for a reason covered in Part 3, and the reason is a good
one.

**`hosting.py`** (149 lines) — Refuses to start a public deployment that has no
login screen. Covered in Part 3.

### `src/recruit/adapters/` — the swappable parts

Four files. An **adapter** is a plug: the rest of the code talks to "a language
model" or "a place to store files", and the adapter decides which actual one.

- `base.py` — the shapes an adapter must match
- `llm.py` (468 lines) — the two real models: Anthropic (paid, accurate) and
  Ollama (free, runs on your own laptop)
- `local.py` — storage on the local disk, no cloud account needed
- `registry.py` — the only place that maps a name in the config to a class

Everything unimplemented raises a clear error naming what is missing, rather than
silently falling back to something weaker.

### `src/recruit/db/` — storage

Six files, six tables.

The headline feature is that **the audit log cannot be altered**. Not "we don't
alter it" — cannot. It is enforced in two independent layers: the code exposes no
method that could change a row (there is a test that checks this by *inspecting
every method*, not by trying three of them), and the database itself has a rule
that rejects any attempt to update or delete one.

Both layers are needed. Code rules are bypassed by anyone with direct database
access. Database rules are silently absent if a setup step is skipped.

Also here: **PII is masked, not deleted**, in the audit trail.
`rahul.sharma@email.com` is stored as `r***[22]`, so a reviewer can still see
that a field was present without the record itself becoming a copy of the
candidate's contact details.

And **idempotency** — a fancy word for "submitting the same CV twice costs
nothing and creates nothing". The document fingerprint is unique in the
database, so a duplicate is recognised rather than reprocessed and re-billed.

### `src/recruit/web/` — the review console

The screens. Server-rendered HTML with Jinja templates; seven templates —
sign-in, queue, candidate detail, team, audit, and an access-denied page.

Two files carry most of the thinking.

**`app.py`** (519 lines) — the routes. Every permission check happens **at the
route, not in the template**. There is a test that renders the Approve button for
a recruiter and then confirms that posting to the URL directly still returns
"forbidden". Hiding a button is decoration; refusing the request is security.

**`humanize.py`** (418 lines) — translates the machine language into English.
This exists because you looked at the audit screen and said the people who will
use this are non-technical almost all the time, and the screen was written for
somebody who already knew what `workflow_run_id` and `auth.login_failed` meant.

The constraint that shaped it: **the jargon is hidden, not removed.** A "Show
technical details" toggle brings back every identifier. That is not politeness —
the regulations turn on being able to name the model and prompt version behind a
decision, so a console that translated them away would read beautifully and be
useless in an audit.

Three rules held throughout: an unrecognised code is *tidied*, never guessed at,
because a confident mistranslation is worse than a visible code; warnings are
worded to land harder, not softer; and the wording lives in one place, so the
reject dropdown, the audit sentence and the summary cannot drift apart.

### `src/recruit/bias/` — the fairness harness

Four files. It takes a CV, changes one thing — the name, a gender signal, the
university, the location, the graduation year — runs it through again, and
reports what moved.

**The harness is itself under test.** A deliberately biased fake model is run
through it, and the test *requires* the harness to catch the bias that was
injected. A fairness checker that has never found anything cannot support a claim
of finding nothing.

Findings are reported **per component** — "the domain-match score leaks the
university name" — which is fixable, rather than "the total moved", which is not.

**A bug this caught in its own code:** the age dimension originally shifted
employment dates alongside graduation year, which turned five years of tenure
into twenty-three. It was measuring experience, not age. It now shifts education
only and *discloses the resulting confound in the report* rather than hiding it.

The report also states its own limits: one profile per group is a smoke test, not
a statistic, and it is explicitly **not** a New York Local Law 144 compliance
certificate, which requires an independent third party.

### `src/recruit/intake/` — email

One file so far, `mail.py` (476 lines), and the line that explains it is:
**structure is standard, meaning is not.**

How an email encodes an attachment is the same for every sender alive, so that
half can be built and tested today. *Which paragraph of a LinkedIn notification
holds the applicant's name* is a guess until one is in hand, so no per-source
parser exists yet and none should be written.

Four decisions here. Provenance comes from **the address the mail was sent to**
(`jobs+linkedin@`), not the sender's display name, which changes without notice.
Filenames are treated as **hostile** — a filename in an email is attacker-supplied
text about to become a path on a Windows machine, so path segments, nulls, absurd
lengths and the reserved device names are all handled (`CON.pdf` is not a file,
it is the console). Magic bytes decide the file type, not the declared one. And
nothing raises on bad content: an unreadable message is quarantined with its raw
bytes kept, so one malformed email cannot stop a batch of two hundred.

## `tests/` — 16 files, about 4,000 lines, 297 passing tests

Roughly one line of test for every two lines of product code.

They are not written as "does this function return the right number". They are
written as **statements about what must remain true**, with the reason in the
test's own name and docstring. A sample of real test names:

- `test_the_schema_is_sent_as_a_constraint_not_as_a_request`
- `test_a_model_must_cite_at_least_once`
- `test_the_model_is_not_asked_to_count_characters`
- `test_ollama_not_running_says_so_in_plain_words`
- `test_runs_recorded_before_the_change_still_open`

`test_packaging.py` deserves a special mention: it walks every import in the
entire codebase and fails if a library is used but not declared in the parts
list. It caught a real defect the moment it was written, and then a second one.

## `config/`

Two files: `organization.example.yaml` (committed) and `organization.yaml` (your
real one, **never** committed).

Everything organisation-specific lives here — company name, contact addresses,
retention periods, scoring weights, which model to use. A tool called
`check_branding.py` fails the build if a company name, email or domain is
hardcoded anywhere else in the repository.

Retention is **per jurisdiction**: EU and UK 180 days for unsuccessful
candidates, US-NY 1095 days because of EEOC record-keeping, India 365 days. The
original documentation said a flat seven years everywhere, which was wrong and is
now listed as a fixed defect.

## `docs/`

- `compliance/` — DPIA, candidate disclosure, appeal process, and the generated
  bias audit report. **Every one marked a template** with `[ORGANIZATION TO
  COMPLETE]` blanks, because shipping finished-looking legal text is worse than
  shipping none: somebody relies on it.
- `intake_playbook.md` — the plan for Phase 6, email intake.
- `phase7_playbook.md` — the plan for Phase 7, multiple organisations and a
  public demo.
- `screenshots/` — browser evidence, because several defects in this project were
  caught by looking at a screen and not by any test.

## `tools/`

- `check_branding.py` — fails the build on hardcoded company values. It once
  caught a hardcoded Windows path in a docstring written minutes earlier, which
  is the gate working on its own author.
- `validate_output.py` — checks a result document against its schema. Ten
  deliberately broken documents, ten rejections.
- `render_docs.py` — fills the placeholders in the documentation from the config.
- `legacy/` — **the quarantine.** The original generators, preserved byte for
  byte with checksums. One of them overwrites the entire repository from a
  hardcoded path. Hard rule 1 of the project is that it must never be run, and it
  is excluded from linting so that nobody is tempted to "tidy" a file whose value
  is being unchanged.

## `golden/cases/`

Eight case files, newly written, holding the ground truth for measuring accuracy
— a plain baseline, a two-column layout, a dot-separated email address, skills in
a table, contradictory dates, an employment gap, eleven jobs, and one carrying
protected characteristics that must **never** be extracted.

They are synthetic, deliberately: the project's rule 5 forbids real candidate
data in the repository. That limitation is real and gets stated wherever a number
from this set is quoted.

## The remaining folders

- `samples/` — example inputs and outputs, so a new install has something to show
- `data/` — where a running instance puts its files; empty in the repository
- `docker/entrypoint.sh` — what runs when the container starts
- `.github/workflows/ci.yml` — the automated checks on every push: tests on two
  Python versions, linting, branding, schemas, and a real Docker build

---

# Part 3 — The decisions, in order

Each of these was a fork. What follows is what was chosen, what was rejected, and
why.

## 1. Cut six of the eight workflows

**Chosen:** build extraction, matching, and the review screen. Nothing else.

**Rejected:** build all eight stages of the documented pipeline.

**Why:** stages 1, 5, 6, 7 and 8 are workflow and record-keeping that an existing
applicant tracking system already does adequately. Nobody buys a second one. The
commercial value is entirely in the two hard parts — reading the CV and scoring
it — plus the screen where a human checks the work.

This decision is written at the top of the project's memory file with an
instruction: *if a session drifts into building a cut workflow, stop and flag
it.* It has held.

## 2. Retire the generator

The project inherited a script that regenerated the entire folder tree from a
hardcoded path. Running it once would have destroyed every hand-written change.

**Chosen:** move it to `tools/legacy/`, preserve it byte-identical with a
checksum, replace it at the root with a stub that refuses to run and explains
why, and make "never run this" hard rule number one.

**Rejected:** delete it. It is the provenance of the documentation; deleting it
would leave no record of where the docs came from.

## 3. Never ask a model to "return JSON"

**Chosen:** use the model provider's native structured-output mode, where the
required shape is compiled into a constraint the model must produce output
within.

**Rejected:** ask for JSON in the prompt and repair the answer when it comes back
malformed, which is what the original specifications described.

**Why:** asking is a request. Constraining is a guarantee. The original design had
an entire repair-and-retry loop to handle bad output; with real structured output
that loop is unnecessary, and the whole class of failure disappears rather than
being handled.

## 4. Never produce a single fit score

Covered under `match.py` above. The score is decomposed, each part evidenced, and
combined in our code with weights from the config.

**Rejected:** ask the model for an overall 0–100 fit score, which is what almost
every product in this space does.

**Why:** a number you cannot decompose is a number you cannot defend, and
employment decisions get challenged.

## 5. The audit log is append-only, enforced twice

**Rejected:** a normal table with a convention that nobody updates it.

**Why:** the audit log is the evidence that the process was followed. Evidence
that can be edited after the fact is not evidence. One layer is not enough for
the reasons given in Part 2.

## 6. SQLite by default, Postgres for production

**Chosen:** the default install uses SQLite — a database that is a single file,
with no server to run.

**Rejected:** require Postgres from the start, which is what the system actually
uses in production.

**Why:** a hard rule of this project is that installing the package alone must
run the whole pipeline — no server, no Docker, no compiled drivers. Someone
evaluating this should reach a working queue in ten minutes. Requiring a database
server is how that becomes an afternoon.

This was caught by *running* it, not by reading code: the shipped config
defaulted to a Postgres URL while the Postgres driver was an optional extra, so a
clean install failed immediately. Now a missing driver raises an error naming both
fixes instead of a cryptic import failure.

## 7. The first-run password is generated, never defaulted

**Chosen:** on first start, create an administrator and print a randomly
generated password once.

**Rejected:** ship `admin` / `admin` and document that it should be changed.

**Why:** shipping a default password is how products end up indexed by search
engines that catalogue exposed systems. A credential nobody was given cannot be
leaked.

The subtlety is in the second run: it must **not** create a second account and
must **not** rotate the first password, because a restart that silently
invalidated the only administrator would look exactly like a break-in. There is a
test for it.

## 8. Local, not free-hosted, when you don't want to pay

**Chosen:** Ollama — a model running on your own machine. No key, no card, no
quota.

**Rejected:** the free tiers of the large providers.

**Why:** those tiers are free because they train on what you send. A CV is a named
person's address, phone number and employment history, handed over for one
purpose. Putting it into a training set to save a few pence is not a trade an
employer may make on a candidate's behalf.

The cost is stated in the same breath, in the config, the README and the error
message: a model small enough to run on a laptop reads a CV less reliably than a
frontier one. Free and accurate are different axes, and the operator picks.

## 9. A public deployment with no login refuses to start

The shipped configuration says "single user, no sign-in" — correct on a laptop.
On a public URL it is a list of everyone who applied, readable by anyone with the
address.

**Chosen:** detect the major hosting platforms by their own environment markers,
and refuse to start there without authentication unless somebody explicitly sets
an override.

**Rejected:** document it in the README.

**Why:** a deploy button makes that gap reachable by accident, and nobody reads the
README before clicking a button. The session cookie also defaults to
HTTPS-only on a public deployment regardless of what the config says: being wrong
that way means nobody can sign in over plain HTTP, which is loud and reversible.
Being wrong the other way puts a session cookie in clear text.

## 10. No AI-attribution in commit messages

**Chosen:** disclose that the build was AI-assisted in the README, in your own
words, where a reader actually looks.

**Rejected:** add a co-author line to every commit.

**Why:** putting it in commit metadata turns a stated fact into a contributor
graph, which says something different from what is true. The two commits already
carrying that line stay as they are — rewriting published history to look better
is a worse story than the line itself.

## 11. `names.py` exists as its own file because of hard rule 9

A screenshot showed the team page saying `Priya.Nair` while the activity log
called the same account `Priya Nair`. The fix was one shared function.

The obvious place to put it was the existing text-tidying module — but that
module imports the web framework, and importing it into the first-run setup
script would have dragged the entire web stack into a command-line tool, breaking
the rule that the pipeline installs with no extras.

So it moved to a 31-line file that uses nothing but the standard library, and the
packaging test now runs the setup script **with the web libraries blocked at
import** to prove it.

That is what a hard rule is for: it turned a two-minute fix into a ten-minute one
and kept a promise that a user would otherwise have discovered was broken.

---

# Part 4 — The one idea

Say this one out loud and people will listen.

> **When a model keeps getting something wrong, the useful question is not
> "how do we ask it better?" It is "why is the wrong answer expressible at
> all?"**

This project took that route five separate times, and it was right every time.

**One — the fit score.** The rule said never produce a single opaque score.
Rather than instructing the model not to, the score fields are deleted from the
schema before the call. The model is now *incapable* of returning one.

**Two — the confidence format.** The system asked for per-field confidence keyed
by a path like `/personal_info/email`. The first real model run produced `email`
instead — thirty-one validation failures on an extraction that was otherwise
correct.

The instinct is "use a bigger model". That is wrong, and knowing why is the
technically interesting part. Structured output works by compiling the required
shape into a grammar the model must produce output within. **A grammar can
constrain a value. It cannot constrain an arbitrary key.** So the rule was never
enforced — it was a request the model was free to ignore. A bigger model would
ignore it *less often*, which is worse than failing consistently: intermittent
correctness is the kind you cannot build a review process on.

The fix was to change the shape, from an object keyed by path to a list of
`{path, confidence}` pairs — where the path is now an ordinary value the grammar
does constrain.

**Three — the path itself.** Still free text, so the model wrote `email`,
`company`, `degree`. Field names, not paths. And `company` is ambiguous anyway —
it occurs once per job — so nothing afterwards recovers what was meant.

The fix: replace the free-text field with a **menu of every path the schema
actually allows** — 136 of them, generated from the schema at request time so it
cannot go stale. The wrong answer stopped being reachable.

**Four — the citations.** The prompt said "include evidence". The schema allowed
an empty list. The model took the schema at its word and sent none, and the
extraction arrived with a green tick and zero verification behind it. Requiring
at least one citation made citing the only way to answer.

**Five — the citation's target.** A quote could be attached to nothing at all,
reading as evidence, counting as evidence, and checkable against nothing. The
target is now required, and drawn from the same menu.

The same lesson at five different altitudes: **a constraint the machine does not
enforce is a comment.**

---

# Part 5 — What is not true yet

These are in the project's own register, and they are in the README, because a
gap you have written down is a plan and a gap you have not is a liability.

**No accuracy figure exists.** Nobody has measured how often the extraction is
right. The confidence thresholds in the config are round numbers, not
measurements, and the config says `calibrated: false` in so many words. Building
the measurement set is the work in progress.

**What a small local model actually does** was measured informally and it is
worth knowing: it reads names, job titles and skills correctly, and mangles a
character of the email address roughly half the time. Sometimes. That
intermittence is worse than consistent failure, because a reviewer stops
expecting it. This is exactly why every run stops for a human.

**The bias harness is not an independent audit.** New York Local Law 144 requires
a third party. The harness is a smoke test you run yourself, and it says so in
its own output.

**No DPIA has been performed — and mostly, that is not this project's job.** The
duty belongs to whoever decides to process real applicants' data. Someone who
self-hosts this owes their own; the project owes them an honest template and
accurate engineering facts to cite, which is what the compliance pack is. The
demo instance processes invented candidates, so there is nothing to assess. The
one case that *is* yours arrives the day email intake points at a real inbox and
a stranger's application lands — that is when you become a controller and owe a
performed assessment rather than a template.

**There is no virus scanning on incoming files**, and email intake means opening
files sent by strangers. The record says `scanned: false` rather than pretending.
This is why the safety gate lands *before* automatic screening in the Phase 6
plan.

**There is no candidate portal.** The appeal process is documented and the
candidate-facing half of it is manual.

**Nobody has attacked this.** The tests prove the cases somebody thought of. That
is not a penetration test and the README must never imply that it is.

---

# Part 6 — Questions you will be asked

## "Did you build this or did AI build it?"

Both, and the honest answer is more interesting than either extreme.

The code was written with AI assistance and the README says so plainly. What was
yours: the scope decision that cut six of eight workflows, the insistence that
the interface be usable by non-technical people, the requirement that a stranger
be able to run it without paying anyone, and — most importantly — **running it**.

Every one of the five most serious defects in this project was found by you
running it on your own machine, not by any test:

- The model that returned field names instead of paths (31 validation failures)
- The schema that stalled a model for over five minutes
- The extraction that passed every check with zero evidence behind it
- The email address with a character missing that every layer of validation
  approved
- The display name that two hundred and fifty-six tests agreed was fine and that
  a screenshot showed was wrong

That is not a small contribution. Knowing to run the thing, on a real document,
and to look at what came back — that is the skill that separates working software
from a demo. The project has a rule about it: *nothing is "done" until it has
been run.*

## "What's the hardest thing you solved?"

The gap between "the model quoted something real" and "the model got the field
right". Part 4, item four and five, and the `rahl.sharma` story. It is a good
story because the bug is invisible, the fix is structural, and the reason the
first fix did not work is genuinely subtle.

## "How do you know it's not biased?"

You do not, and saying so is the correct answer. There is a harness that tests
for it across five dimensions and is itself tested against injected bias — and it
reports its own limits: one profile per group is a smoke test, not a statistic,
and it cannot satisfy Local Law 144, which requires an independent auditor.

An applicant who claims their tool is unbiased is telling you they have not
thought about it.

## "Why should a human review every decision?"

Because the law requires it for decisions with significant effects on people, and
because the system's own measurements show a small model gets a character of the
email wrong some of the time and not others. Screening automatically is lawful.
Rejecting automatically is the part that is not.

## "What would you do next, with more time?"

Measure the accuracy. Everything else — the confidence thresholds, automatic
screening, any claim about how well it works — is blocked on a measurement that
does not exist yet. That is already the next item in the plan, and it is written
down as blocking rather than skipped.

---

# Part 7 — How it was built

**One prompt, one commit.** Each unit of work has a stated goal and an acceptance
command that must be run, with real output pasted, before it counts as done.

**Decisions are recorded in the session that makes them**, in `DECISIONS.md`, which
is read at the start of every session. That file is now about 700 lines of
decision log. It is why the same argument never happens twice, and why this guide
could be written at all.

**Contradictions in the inherited documentation are flagged, not silently
fixed.** There is a list of known-wrong things in the specification documents, and
implementing from one of those documents means checking the list first.

**Nothing counts until it has been run on a machine that does not already have
the dependencies.** This rule has caught four separate packaging defects that
were invisible on a developer machine — including a library that a newer version
of a web framework had moved, which meant a third of the test suite would not
even load on your computer while passing perfectly on the build machine.

## What that produced

| | |
|---|---|
| Product code | ~7,300 lines |
| Test code | ~4,000 lines |
| Tests passing | 297 |
| Automated gates on every push | tests on two Python versions, linting, branding, schema validation, bias self-test, Docker build |
| Phases complete | 0–3 (the full pipeline), plus bias harness, auth, packaging, self-hosting, local models, evidence trail |
| Phases planned and written but not started | 6 (email intake), 7 (multiple organisations and a public demo) |

---

*Written 2026-09-14, after the build settled, so that it describes what shipped
rather than what was planned.*
