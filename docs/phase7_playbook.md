# Phase 7 — Workspaces, sign-up, and a demo anyone can try

**Status:** planned, not started. Eleven prompts, 7.0 to 7.10.
**Decided with the operator, 2026-09-14.**

---

## What this phase is, and what it deliberately is not

Visitors can create an account on the hosted copy and use the system with
**synthetic candidates**. Real hiring means deploying their own copy with the
button that already exists.

That sentence is the whole scope, and each half of it is a decision.

**Why sign-up at all.** Self-hosting already works, but "clone this repository
and install Docker" is not something a hiring manager evaluates. A working
sign-up flow is what turns a repository into something a person can *see*
working in thirty seconds.

**Why synthetic candidates only.** The moment a stranger uploads a real CV to
the operator's instance, the operator is processing another person's personal
data on their behalf. Under GDPR that makes them a processor: a written
agreement with every user, a lawful basis, a retention obligation, and personal
liability if it leaks. That is a real business decision, not a technical one,
and it is not worth taking on to demonstrate a portfolio project. Demo mode is
how the flow gets shown without the duty of care.

**Not in this phase:** email intake (Phase 6 owns it), billing, teams spanning
workspaces, SSO. Anything that starts to look like running a service rather
than showing one.

---

## The one design decision everything else follows from

**Row-level tenancy, with a `workspace` as the unit.** Every table that can hold
candidate data carries a `workspace_id`. Users belong to a workspace. Nothing is
visible across workspaces, ever.

The alternative — a database per tenant — is safer by construction and wrong
here: it needs an orchestration layer the project does not have, and it breaks
the promise that `pip install -e .` runs everything with SQLite and no server.

**Row-level tenancy has exactly one failure mode, and it is catastrophic**: a
query that forgets its filter returns somebody else's candidates. So the
defence cannot be "remember the filter". It has to be the same move this project
has now made five times — make the wrong thing unexpressible. The repository
takes a workspace at construction and exposes no method that can return a row
without one. A query with no filter should be impossible to *write*, not
merely absent.

---

## 7.0 — Write the decision down before writing code

Amend `CLAUDE.md`: the scope section, a Phase 7 row in the roadmap, and a
decision-log entry recording the tenancy model, why row-level rather than
database-per-tenant, and why demo mode rather than real data.

Add a **hard rule 11**: *no query for candidate data may be written without a
workspace; the repository must make it impossible rather than discouraged.*

**DONE WHEN:** `CLAUDE.md` carries the rule, and a session reading it would know
why demo mode exists without being told again.

---

## 7.1 — The workspace table and the column on everything

A `workspaces` table (id, name, created_at, plan, is_demo). A `workspace_id`
foreign key on `documents`, `candidates`, `workflow_runs`, `review_tasks`,
`requisitions`, `users`, and `audit_log`.

Alembic migration with a backfill: **every existing row joins workspace 1.** A
self-hosted copy that upgrades must open on the same data it had before, with
nobody signing in again.

**The audit log is append-only and this is a schema change to it.** Adding a
nullable column is not an UPDATE of existing rows' content, and the backfill
runs once in a migration rather than through application code. Record that
distinction in the migration's docstring, because the next reader will
reasonably ask.

**DONE WHEN:** a database created before this phase opens after it, with every
row in workspace 1 and the review queue showing what it showed before. Run the
console against a copy of a real pre-migration database and paste the queue.

---

## 7.2 — Make a cross-workspace read impossible to write

`Repository(session, workspace_id)`. Every method filters. No method takes an id
without also taking the workspace, and no method returns a bare query object a
caller could execute unfiltered.

Test it the way the append-only audit log is tested — **by introspection, not by
example.** Walk every public method of `Repository` and assert that each one
either takes a workspace-scoped session or is on an explicit allow-list of
non-tenant methods (migrations, health checks). A test that checks three
specific methods proves nothing about the fourth one somebody adds next year.

**DONE WHEN:** the introspection test passes, and deliberately removing the
filter from one method makes it fail.

---

## 7.3 — The workspace comes from the session, never from the URL

`Principal` gains a workspace. Every route resolves it from the signed-in user,
and **no route ever reads a workspace from a path or query parameter** — that
is how tenancy bugs become tenancy incidents.

Cross-workspace access returns **404, not 403.** A 403 confirms the record
exists, which tells one user something true about another's data. Not a leak of
content, but a leak, and the cheaper answer is to say nothing.

**DONE WHEN:** a test creates two workspaces, puts a candidate in each, signs in
as A, and requests B's review task *by URL* — and gets 404. Repeat for the
document, the audit page and the match result. This is the test the whole phase
exists to pass.

---

## 7.4 — Sign-up, closed by default

`POST /signup` creates a workspace and its first administrator.

**Closed unless switched on**, by `RECRUIT_SIGNUP=open`. A company running its
own copy does not want strangers creating accounts on it, and the default has to
be the safe one — the same reasoning as `hosting.refuse_unsafe_public_start`.
The self-hosted default must not change behaviour for anyone who upgrades.

Rules: address must be unique across the system; password minimum enforced by
the existing rules (the common-password refusal already works); no email
verification, because nothing can send mail yet — so **a sign-up is an
unverified account and the demo must be safe under that assumption.** Say so on
the page rather than implying otherwise.

**DONE WHEN:** with `RECRUIT_SIGNUP` unset, `POST /signup` returns 404 and no
form is rendered anywhere. With it open, signing up produces a working account
in a fresh workspace with no visibility of any other.

---

## 7.5 — Demo mode: synthetic candidates, and no way to upload a real one

`RECRUIT_DEMO=1`. Every new workspace is seeded with the sample candidates the
existing `recruit.seed` produces, so the first screen is a working queue.

**Uploads are refused in demo mode** — not warned about, refused. This is the
control that keeps real candidate data off the instance, and a warning is a
control that works until somebody is in a hurry. The refusal explains why and
links to the deploy button.

A banner on every screen: this is a demonstration, the candidates are invented,
do not put real applicants here.

**DONE WHEN:** a fresh sign-up lands on a populated queue; the upload route
returns a refusal naming demo mode; and the banner is present on queue, review,
audit and team screens.

---

## 7.6 — Limits, and a switch that closes it

Public sign-up is an open door. Before it opens:

- sign-ups per IP per day, capped
- workspaces per instance, capped, with a stated maximum
- documents per workspace, capped
- `RECRUIT_SIGNUP=closed` takes effect on the next request, no redeploy

The caps exist because free hosting has finite disk and the operator is not
watching it at 3am. The kill switch exists because the first thing to do about
abuse is stop it, and the second is work out what happened.

**DONE WHEN:** exceeding each cap returns a plain-English refusal rather than a
traceback, and flipping the switch closes sign-up without a restart.

---

## 7.7 — Deleting a workspace, and the question it raises

A workspace owner can delete their workspace: every candidate, document and
review task goes.

**The audit log is the hard part and needs a decision, not a default.** It is
append-only by design and by database trigger. Two defensible positions:

1. Audit rows are retained per the jurisdiction's retention rule even after the
   workspace is deleted, because they are the record that the deletion happened
   and of what went before it.
2. A deletion request under GDPR Art. 17 covers them too, and retaining them
   needs a lawful basis.

The project already has per-jurisdiction retention in config, and the honest
answer is probably (1) with the candidate identifiers masked — but **this is the
one place in Phase 7 where the right answer is a question for a lawyer, not an
engineer.** Write the code to make either possible, implement (1), and put it in
the compliance pack as an open question rather than a settled one.

**DONE WHEN:** deletion removes candidate data, the trigger still refuses to
update or delete an audit row through application code, and
`docs/compliance/README.md` names the open question.

---

## 7.8 — A demo that is still there in three months

`render.yaml` currently provisions Render's free Postgres, **which deletes
itself 30 days after creation.** For a demo whose entire job is to be running
when someone clicks a link on a CV, that is a failure with a timer on it.

Point `DATABASE_URL` at a free Neon database — no expiry, no card, scales to
zero when idle. Update the README's deploy section accordingly.

**DONE WHEN:** the demo is deployed, reachable, and its database is not on a
countdown. This also closes the **"Render deploy never performed"** row in the
deferred register, which has been open since 5.3.

---

## 7.9 — Verify it the way this project verifies things

- the two-workspace leak test from 7.3, by URL, for every route that returns
  candidate data
- the full suite on 3.11 and 3.12 in CI
- a real browser pass: sign up, land on a seeded queue, try to upload, read the
  refusal, open the team page, sign out
- a second account in a second workspace, proving the first cannot see it

**DONE WHEN:** all four are done and pasted. Hard rule 6: nothing is finished
until it has been run.

---

## 7.10 — Say what is still not true

Update the README and the deferred register together:

- the demo holds invented candidates and is not a service
- accounts are unverified, because nothing sends mail
- no accuracy figure exists; the golden set (4.1) is still owed
- what a small local model actually does, which the README now measures
- multi-tenancy is implemented and has never been load-tested or
  security-reviewed by anyone but its author

**DONE WHEN:** a stranger could read the README and correctly predict what they
are about to get.

---

## What this phase does not solve, stated now

**One reviewer's mistake is still one reviewer's mistake.** Tenancy separates
data; it does nothing about the quality of a decision inside a workspace.

**Unverified accounts mean the email address on a workspace is a claim.** Fine
for a demo, not fine the day real applicants are involved.

**Nobody has attacked this.** The leak test proves the cases it thinks of. It is
not a penetration test, and the README must not imply that it is.
