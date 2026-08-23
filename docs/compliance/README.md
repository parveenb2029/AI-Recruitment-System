# Compliance pack

Documents a buyer's legal team will ask for before they ask about features.

> **These are templates, not legal advice.** Every one needs review by counsel
> qualified in the jurisdictions you hire in, and several need facts only your
> organization can supply. Sections requiring input are marked
> `[ORGANIZATION TO COMPLETE]`. Shipping any of these unreviewed would be worse
> than shipping none, because someone will rely on them.

| Document | What it is | Status |
|---|---|---|
| [`dpia.md`](dpia.md) | Data Protection Impact Assessment — required under GDPR Art. 35 for high-risk automated processing | Template |
| [`candidate_disclosure.md`](candidate_disclosure.md) | Candidate-facing notice that AI is used, and what it does | Template |
| [`appeal_process.md`](appeal_process.md) | How a candidate obtains human review of an automated decision (GDPR Art. 22) | Template |
| [`bias_audit.md`](bias_audit.md) | Output of the internal bias harness | **Generated** — re-run per release |
| `bias_audit.json` | Same result, machine-readable | **Generated** |

---

## Why this exists

Employment screening is a regulated category, and the obligations attach to the
employer using the tool as much as to whoever built it.

- **NYC Local Law 144** — an automated employment decision tool needs an
  *independent* bias audit within the last year, published results, and
  candidate notice at least 10 business days before use.
- **GDPR Art. 22** — a candidate subject to a decision with legal or similarly
  significant effects, made solely by automated means, has the right to obtain
  human intervention, express a view, and contest the decision.
- **GDPR Art. 35** — high-risk processing requires a DPIA before it starts.
- **EU AI Act** — employment and worker-management AI is classified high-risk,
  bringing conformity assessment, logging, and human-oversight obligations.
- **Colorado SB 24-205** and **Illinois HB 3773** create comparable duties.

## What this system already does that helps

These are engineering facts, verifiable in the code, that a DPIA or audit can
cite:

| Obligation | Implementation |
|---|---|
| Human oversight of decisions | Every candidate-affecting outcome routes to a review queue. A recruiter can escalate but not approve — `auth.PERMISSIONS`. |
| Explainability | Match scores are decomposed per component with evidence quoted from the source, never a single opaque number — `match.py`. |
| Traceability | Append-only audit log carrying prompt version, model id, actor, and content hash. Enforced by a database trigger, not convention — `db/migrations.py`. |
| Data minimisation | PII masked in audit detail; full data only in the artifact store — `db/repository.mask_pii`. |
| Storage limitation | Retention per jurisdiction, consent-aware — `config/organization.yaml`. |
| Fabrication control | Every evidence snippet fuzzy-matched back to the source; below threshold the run is blocked — `validate.validate_evidence` (VR-03). |
| Bias monitoring | Perturbation harness across five proxy dimensions, self-tested against injected bias — `recruit.bias_audit`. |

## What it does not do

Stated plainly, because a gap you have written down is a plan and a gap you have
not is a liability:

- **No independent bias audit.** The harness is internal. LL144 requires a third
  party.
- **No DPIA has been performed.** `dpia.md` is a blank to fill in, not a record
  of an assessment that happened.
- **Confidence thresholds are uncalibrated.** `confidence.calibrated: false`.
  Any claim about accuracy is unsupported until Phase 4.3.
- **No candidate-facing surface exists yet.** The disclosure and appeal
  documents describe a process that currently has no UI behind it.

## Regenerating the bias audit

```
python -m recruit.bias_audit --self-test        # prove the harness works first
python -m recruit.bias_audit --out docs/compliance/bias_audit.md \
                             --json docs/compliance/bias_audit.json
```

Re-run on every prompt change, model change, or rubric change. A bias audit
describes one configuration; change the configuration and it describes nothing.
