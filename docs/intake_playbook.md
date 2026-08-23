# Phase 6 — Intake automation playbook

**Goal:** applications arrive on their own, from every source, land in one place,
and get screened the moment they do.

Continues the 14-prompt build playbook (Phases 0–5, complete). Same convention:
one prompt, one commit, each ending in a command you run yourself.

Web version: https://claude.ai/code/artifact/f3e1073f-4413-4500-963c-bc60d5141dad

---

## 1. What each platform actually allows

Checked before writing anything else. A playbook built on an API that does not
exist costs months.

| Source | Direct access? | What is really on offer |
|--------|----------------|-------------------------|
| **Gmail** | **Buildable** | Full API access to a mailbox you own. Reading mail is a *restricted* scope, so Google requires an annual paid security assessment (CASA) — **unless** the app is internal to one Workspace organisation or used only by you, which exempts it. Fine for running your own hiring; a real cost the day you sell this to other companies. |
| **LinkedIn** | **Closed** | No self-serve path to applicant data. It sits behind the Talent Solutions / Recruiter System Connect partnership — enterprise sales, 4–6 months minimum, expects existing scale. Scraping breaches their User Agreement and they enforce it. **Do not build for this API.** |
| **Indeed** | **Partner only** | Indeed Apply will POST each application to your webhook as JSON — exactly what you want — but only after a signed Developer Agreement, a published XML job feed, and an issued API token. |
| **Naukri** | **Partner only** | Apply-integration exists and Indian ATS vendors use it, but it goes through their enterprise team, not a developer portal. Worth starting the conversation, not worth waiting for. |

## 2. The design that follows

Every one of these platforms will deliver applications to an **email address**.
That is the connector they all share, it needs nobody's permission, and it works
today. So: one reliable mail intake with a small parser per source. The partner
APIs become an upgrade slotted in later if Indeed or Naukri ever say yes.

Three decisions worth making once, now:

- **A separate address per source** — `jobs+linkedin@`, `jobs+naukri@`,
  `jobs+indeed@`. Then knowing where an application came from is a fact, not a
  guess from the sender's name, and sender names change without warning.
- **Keep the raw message forever.** Parsers will be wrong and get fixed; the
  evidence they were wrong about must survive that.
- **Never guess at an unrecognised email.** Quarantine it and say so. A parser
  that half-understands a new format silently invents a candidate.

### The one thing that decides how much of this is possible

Some platforms email the resume as an attachment. Others email *"someone applied
— click here to view"*, and the link needs a login. If a source sends links
rather than files, no amount of code gets the resume out, and that source stays
manual until the posting's delivery settings can be changed.

No documentation can tell you which is which — the formats differ by country,
plan, and how the job was posted. You have to look at a real one. That is prompt
6.1, and everything after it is built against what you find.

---

## 3. The twelve prompts

### 6.0 — Amend the scope decision on purpose

`CLAUDE.md` says in writing that intake (WF-02) is cut from v1 and that any
session drifting into it should stop and flag it. This whole phase is that
drift. That is allowed — you own the scope — but it gets recorded as a decision
with a date and a reason, not absorbed quietly.

**DONE WHEN** the scope section names intake as in-scope, and the decision log
says when and why it changed.

### 6.1 — Find out what actually arrives  *(your homework)*

Post a real job on each source you care about. Apply to it yourself from a
personal address. Save each resulting email in full — headers and all — strip
anything personal, commit them as test fixtures.

Every parser is written against these files and every test replays them, so a
format change later shows up as a failing test rather than a silently empty
queue.

**DONE WHEN** one redacted message per source sits in the repo, and you can say
for each whether it carried the resume or only a link.

### 6.2 — Read the mailbox, without reading anything twice

Gmail API, set up as an internal app so no security assessment is needed. Checks
on a schedule to begin with; a live push feed is a refinement, not a starting
point.

The property that matters: running it twice does nothing the second time. Every
message carries an ID; that ID is the key. Get it wrong and a restart re-reads a
hundred resumes and re-bills you for all of them.

**DONE WHEN** the first run imports everything waiting, the second imports
nothing, and both say so.

### 6.3 — Turn four email formats into one record

A parser per source, each producing the same shape: who applied, which job they
named, what files came with it, when it arrived, where from. Anything that does
not match a known format goes to quarantine with the raw message attached.

**DONE WHEN** every fixture from 6.1 parses, and a deliberately mangled one
lands in quarantine instead of producing a half-empty candidate.

### 6.4 — One landing place

Every application from every source in a single list, whatever door it came
through. Source, arrival time, original message, attachments, parsed record.

Duplicates need care. The same file arriving twice is a duplicate. The same
person applying to two different jobs is **not** — and treating them as one is
how a candidate silently disappears from a role they applied for.

**DONE WHEN** one person applying to two jobs produces two entries, and one
application forwarded twice produces one.

### 6.5 — The safety gate  *(must come before 6.8)*

You are about to start opening files sent by strangers, automatically, with no
human looking first. Everything deferred about scanning stops being deferred.

- Virus scanning, actually running, result recorded per file
- Hard limits on size and type, and on what a compressed file may expand to
- A cap on applications processed per hour
- A spending cap, and a switch that stops everything

The spending cap is not paranoia. One mail loop, one forwarding rule pointed at
the wrong address, and an unbounded pipeline processes the same message
thousands of times overnight and bills you for every one.

**DONE WHEN** a harmless industry-standard test virus is rejected and recorded,
and tripping the hourly cap stops the line cleanly rather than crashing it.

### 6.6 — Work out which job each application is for

An application names a job in words — whatever the applicant typed. Matching
that to a real requisition is its own problem, and getting it wrong means
someone is scored against the wrong requirements.

An explicit mapping you control, plus an "unrouted" pile for anything that does
not match. The pile is a feature: a system that quietly assigns every
unrecognised application to the nearest-looking job is worse than one that
admits it does not know.

**DONE WHEN** an application naming a job you do not have appears in the
unrouted list, and nothing was scored.

### 6.7 — A queue, so one bad email cannot stop everything

Work goes on a durable queue; a worker picks it up. Failures retry with
increasing delays; anything that keeps failing moves to a dead-letter list where
you can see it.

Without this, the first corrupt PDF on a Friday evening blocks every application
behind it until Monday, and nothing tells you.

**DONE WHEN** a deliberately poisonous message dead-letters and the ten
applications queued behind it all process normally.

### 6.8 — Screen on arrival

Connect the landing zone to the pipeline you already have — read, check every
quote against the document, score against the job's requirements — running by
itself as each application lands.

What does not change: everything still arrives in the human review queue.
Nothing is approved by the system and nothing is rejected by it. That is not
caution, it is the legal position — a candidate has the right to a human
decision, and the moment the machine rejects someone on its own you have lost it.

**DONE WHEN** an email sent to the intake address appears as a scored,
evidence-cited candidate in the review queue without anyone touching anything.

### 6.9 — Tell candidates, and mean it

The disclosure and appeal documents in `docs/compliance/` are templates with
blanks. This is where they become real: a notice actually sent when an
application is received, an appeal route that reaches a person, and a retention
clock that starts on arrival and is honoured by a deletion job that genuinely
runs.

**DONE WHEN** a test application receives the notice and appears in a retention
report with a real deletion date.

### 6.10 — The golden set you deferred  *(your homework — no longer optional)*

Fifty to a hundred resumes where you have written down what the right answer is.
Postponed because it costs an evening and nothing was riding on it.

Something is riding on it now. The confidence thresholds deciding what gets
flagged are round numbers somebody typed, and the config says so:
`confidence.calibrated: false`. Screening a handful of resumes you chose
yourself against guessed thresholds is a demo. Screening every applicant
automatically against guessed thresholds is a system making claims nobody has
checked.

**DONE WHEN** the thresholds come from measurement, `calibrated` reads true, and
you can state an accuracy figure and defend where it came from.

### 6.11 — See what it is doing

Volume per source, parse failure rate, cost per day, arrival-to-queue latency,
unrouted and quarantined counts.

Automated intake fails quietly by design — nobody notices missing applications.
A source that stopped delivering three weeks ago looks exactly like a slow week
unless something is counting.

**DONE WHEN** a source going silent for a day is visible on a page without
anyone querying the database.

### 6.12 — Run it live on one job

One real requisition, one source, watched daily, every automated result checked
by hand against what you would have decided. Keep the comparison — it is the
first honest evidence of whether this works on real applicants rather than on
the sample resume.

**DONE WHEN** one requisition has run end to end for two weeks and you have a
written comparison of the system's judgements against yours.

---

## 4. Before any of this touches a real person

**What is true today:** the data is synthetic, the confidence thresholds were
never measured, the bias harness is one you run on yourself rather than an
independent audit, and no accuracy figure exists. None of that is a problem
while you are the only person feeding it resumes you picked.

The moment real applications flow in automatically, every one of those becomes a
live obligation rather than a note in a file — and the people affected did not
choose to be assessed by an uncalibrated system.

- **The impact assessment must be performed, not templated.** Automated
  screening of job applicants is exactly the high-risk processing that requires
  one, and a document with blanks in it is not one.
- **Candidates must be told at the point they apply** that automated processing
  is involved, and given a route to a human. That is 6.9, not optional
  decoration.
- **Keep the human gate absolutely.** Screening automatically is lawful;
  rejecting automatically is what is restricted. Nothing in this phase may
  weaken that — including "just auto-archive the obvious ones".
- **New York applicants need an independent bias audit first** — not the harness
  you run yourself. If your postings are visible in NYC this is a
  before-you-start item.
- **Do not scrape LinkedIn.** Not as a shortcut, not "just for testing". It
  breaches their terms and they have a history of pursuing it.

---

## 5. Where to start

The smallest genuinely useful version stops after **6.4**: Gmail, one source,
applications landing in one list, routed by hand, nothing screened
automatically. About a week of work, no legal groundwork needed, and it already
removes the manual step being done today.

Everything from **6.5** onward is the automatic screening — and the safety gate,
the golden set, and the candidate notices come with it. They are not niceties to
bolt on afterwards; they are the price of the automation, and cheaper to build
in than to retrofit once real applicants are in the database.

**The one prompt to run first: 6.1.** Apply to your own job posting on each
source and look at what lands. Whether those emails carry the resume or only a
link decides how much of this is buildable at all, and no amount of planning
answers it from a desk.
