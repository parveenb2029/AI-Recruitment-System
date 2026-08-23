# Candidate appeal and human review — template

> **Template, not legal advice.** Review with counsel.
>
> **GDPR Art. 22** gives a candidate subject to a decision based solely on
> automated processing, with legal or similarly significant effects, the right to
> obtain human intervention, to express their point of view, and to contest the
> decision. Employment decisions are significant effects.

---

## Position

**No decision in this system is solely automated.** Every candidate-affecting
outcome passes through a human reviewer before it takes effect, which is
enforced in code rather than by policy:

- Below-threshold candidates are marked `auto_archive_eligible` — **eligible**,
  not archived. A person still decides.
- A recruiter can review and escalate but cannot approve or reject; that
  requires a hiring manager or admin role.
- Every decision is recorded with the reviewer's identity in an append-only log.

That reduces Art. 22 exposure. It does not remove the obligation to offer review
and contest, because a candidate's perception of the process matters and because
the burden of proving human involvement sits with the controller.

## The process

### 1. Candidate requests review

Route: `[ORGANIZATION TO COMPLETE: email or form]`

The candidate needs to supply only enough to identify their application. Do not
require them to explain what the AI got wrong — they cannot see it.

### 2. Acknowledge

Within `[ORGANIZATION TO COMPLETE: target, e.g. 5 business days]`.

### 3. Assemble the record

For any application, the system can produce:

| Item | Where it comes from |
|---|---|
| The source document as received | Artifact store, addressed by content hash |
| What was extracted, field by field, with confidence | `workflow_runs.envelope` |
| The evidence quoted for each conclusion | `envelope.evidence`, with source offsets |
| Component scores, weights, and the arithmetic | `results.components` and `results.weighting` |
| Which requirements were met, partial, not met, or unknown | `results.must_have_requirements` |
| Who reviewed it, when, and any reason code | `review_tasks` and `audit_log` |

This is the practical payoff of decomposed scoring. "You scored 0.61" is not an
answer to a person asking why they were rejected. "Terraform was not evidenced
anywhere in your CV, and it carries 15% of the must-have component" is.

### 4. Human re-review

By someone **not involved in the original decision**.
`[ORGANIZATION TO COMPLETE: name the role.]`

The reviewer should:

- Read the original CV directly, not the extracted summary.
- Check each evidence citation against the source.
- Consider anything the candidate has told you that was not in the CV.
- Record the outcome with a reason code.

### 5. Respond

Within `[ORGANIZATION TO COMPLETE: target]`. Say what was reviewed, what was
found, and what happens next. If the original outcome stands, say why in terms
of the job requirements.

### 6. Escalation

`[ORGANIZATION TO COMPLETE: internal escalation, then the right to complain to a
supervisory authority — name the relevant one per jurisdiction.]`

---

## What to record

Every appeal, in the audit log:

- Request received, and when
- Who conducted the re-review, and that they were not the original decision-maker
- What the candidate said
- Outcome and reasoning
- Response sent, and when

Appeal volume and overturn rate are quality signals. A rising overturn rate means
the pipeline is wrong more often, not that candidates are complaining more.

## Known gap

There is **no candidate-facing interface** in the system today. This document
describes a process that is currently manual on your side. Building the
candidate portal is not in the current scope; see the deferred register in
`CLAUDE.md`.
