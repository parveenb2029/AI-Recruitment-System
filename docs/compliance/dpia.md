# Data Protection Impact Assessment — template

> **This is a template, not a completed assessment.** A DPIA is a process, not a
> document: it requires consulting your DPO, and in some cases the supervisory
> authority, before processing begins. Sections marked
> `[ORGANIZATION TO COMPLETE]` need facts only you have. Have counsel review the
> whole thing.
>
> Required under **GDPR Art. 35** where processing is likely to result in a high
> risk to individuals. Automated evaluation of job applicants qualifies:
> systematic evaluation, automated decision-making with significant effects, and
> vulnerable data subjects (applicants are in an asymmetric power relationship
> with a prospective employer).

---

## 1. Controller and roles

| | |
|---|---|
| **Data controller** | `[ORGANIZATION TO COMPLETE]` |
| **Data Protection Officer** | `{{contact.dpo}}` — `[ORGANIZATION TO COMPLETE if blank]` |
| **Processors** | LLM provider (`[NAME AND REGION]`), hosting provider, ATS vendor |
| **Assessment date** | `[DATE]` |
| **Review due** | Annually, and on any change to model, prompts, or rubric |

## 2. Description of the processing

**Purpose.** Screening job applicants against a job description to produce a
ranked, evidence-cited shortlist for human review.

**Nature.** Resume documents are ingested, text is extracted, an LLM produces a
structured candidate profile and per-component match judgements. The application
combines those into a score using configured weights. Every outcome affecting a
candidate is placed in a human review queue.

**Scope.** `[ORGANIZATION TO COMPLETE: volume per year, roles covered, countries]`

**Context.** Applicants supply data expecting it to be used for the role applied
for. They are not in a position to negotiate terms.

### Data categories

| Category | Source | Necessity |
|---|---|---|
| Identity — name, email, phone | Candidate's resume | Contacting the candidate |
| Employment history | Resume | Assessing relevant experience |
| Education | Resume | Assessing stated requirements |
| Skills, certifications | Resume | Matching against the job description |
| Location | Resume | Right-to-work and location requirements |
| Inferred: match scores, confidence, gap analysis | Generated | Ranking for human review |

**Special category data (Art. 9) is not processed intentionally.** Resumes may
nonetheless contain it — health, religion, trade union membership, political
opinion. `[ORGANIZATION TO COMPLETE: state how incidental special-category data
is handled.]` The system prompt instructs the model never to infer or use
protected characteristics, and `matching.excluded_signals` records what is held
out, but a prompt instruction is a control, not a guarantee.

## 3. Necessity and proportionality

| Question | Response |
|---|---|
| **Lawful basis** | `[ORGANIZATION TO COMPLETE]` — typically legitimate interests (Art. 6(1)(f)) with a balancing test, or consent. Consent is fragile in a hiring context because it is not freely given. |
| **Could the purpose be achieved less intrusively?** | `[ORGANIZATION TO COMPLETE]` |
| **Data minimisation** | Only fields in `schemas/resume.schema.json` are extracted. PII is masked in logs (BR-06). |
| **Storage limitation** | Per jurisdiction in `config/organization.yaml`. EU/UK 180 days for unsuccessful candidates without consent; 730 with. |
| **Accuracy** | Every extracted field carries a confidence score; evidence is verified against the source (VR-03); a human reviews before any candidate-affecting outcome. |
| **Transparency** | See `candidate_disclosure.md`. `[ORGANIZATION TO COMPLETE: confirm it is actually served to candidates.]` |

## 4. Risks to individuals

| Risk | Likelihood | Severity | Mitigation | Residual |
|---|---|---|---|---|
| **Discriminatory outcome** via proxies in the data | Medium | High | Score decomposed and evidenced; protected characteristics excluded by prompt and recorded in `excluded_signals`; perturbation harness run per release | `[ASSESS]` — the internal harness is not an independent audit |
| **Fabricated content** — model invents an employer or qualification | Medium | High | VR-03 fuzzy-matches every cited snippet against the source; below 0.8 the run is blocked and flagged | `[ASSESS]` |
| **Unfair rejection with no recourse** | Medium | High | No fully automated rejection; below-threshold candidates are flagged, not archived; appeal process documented | `[ASSESS]` |
| **Over-reliance on an uncalibrated score** | **High** | Medium | Thresholds are currently unvalidated (`confidence.calibrated: false`). Reviewers must not treat the number as accuracy. | **High until Phase 4.3 calibration** |
| **Unauthorised access to candidate data** | Low | High | Role-based access enforced at the route; passwords scrypt-hashed; session tokens stored hashed; audit log append-only | `[ASSESS]` |
| **Excessive retention** | Low | Medium | Per-jurisdiction retention job | `[ASSESS]` |
| **Processor risk** — resume text sent to an LLM provider | Medium | Medium | `[ORGANIZATION TO COMPLETE: DPA in place? data residency? training opt-out? sub-processors?]` | `[ASSESS]` |

## 5. Data subject rights

| Right | How it is met |
|---|---|
| Access (Art. 15) | `[ORGANIZATION TO COMPLETE: process and SLA]` |
| Rectification (Art. 16) | A reviewer can correct extracted fields; corrections are audited |
| Erasure (Art. 17) | `[ORGANIZATION TO COMPLETE]` — note the audit log is append-only by design; document how erasure and audit integrity are reconciled |
| Restriction (Art. 18) | `[ORGANIZATION TO COMPLETE]` |
| Portability (Art. 20) | Candidate profiles export as JSON |
| Object (Art. 21) | `[ORGANIZATION TO COMPLETE]` |
| **Not subject to solely automated decisions (Art. 22)** | No decision is solely automated — see `appeal_process.md` |

> **Erasure versus the audit log deserves real attention rather than a
> checkbox.** The audit log is deliberately immutable, and a deletion request
> collides with that. The usual resolution is to delete the candidate record and
> the source document while retaining audit entries that carry only pseudonymous
> identifiers. Confirm that position with counsel; do not assume it.

## 6. Consultation

| | |
|---|---|
| DPO consulted | `[DATE / OUTCOME]` |
| Data subjects or representatives consulted | `[ORGANIZATION TO COMPLETE — or record why not, Art. 35(9)]` |
| Supervisory authority consulted | Required under Art. 36 if high residual risk remains after mitigation. `[ASSESS]` |

## 7. Outcome

| | |
|---|---|
| **Decision** | `[PROCEED / PROCEED WITH CONDITIONS / DO NOT PROCEED]` |
| **Conditions** | `[ORGANIZATION TO COMPLETE]` |
| **Sign-off** | `[NAME, ROLE, DATE]` |
| **Next review** | `[DATE]` |
