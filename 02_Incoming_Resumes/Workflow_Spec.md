# Incoming Resume Intake — Workflow Specification

**Workflow ID:** WF-02  
**Version:** 1.0.0  
**Last Updated:** 2026-08-03  
**Document Owner:** AI Operations — Talent Technology  
**Classification:** Internal — Operational  

---

## 1. Purpose

Accept, deduplicate, virus-scan, and route candidate applications into the processing queue. This workflow is a core stage in the enterprise AI Recruitment Operations platform. It ensures that every downstream automation receives consistent, auditable inputs while preserving mandatory human oversight at defined approval gates.

The workflow exists because recruitment at scale cannot rely on ad hoc documents, inbox-driven processes, or inconsistent reviewer judgment. By codifying triggers, actors, and success criteria, the organization reduces time-to-fill, improves candidate experience, and maintains defensible hiring records for compliance audits.

---

## 2. Business Goal

| Goal | Target | Measurement Horizon |
|------|--------|---------------------|
| Reduce manual handling time | ≥ 40% vs baseline | Quarterly |
| Improve data consistency | ≥ 95% schema compliance | Monthly |
| Maintain compliance | Zero critical audit findings | Annual |
| Accelerate pipeline velocity | ≥ 25% faster stage transitions | Quarterly |

The business goal is not full automation—it is **augmented operations**: AI handles extraction, matching, and drafting; humans retain authority over shortlist, interview design approval, and final hire decisions.

---

## 3. Business Problem

### 3.1 Current State

Recruiting teams receive unstructured inputs from multiple channels. Hiring managers write job descriptions in inconsistent formats. Recruiters manually copy data into spreadsheets and ATS fields. Interview feedback arrives as free text with incompatible rating scales. Decision meetings lack a single source of truth.

### 3.2 Impact

- **Time:** Recruiters spend 60–70% of time on administrative tasks rather than candidate engagement.
- **Quality:** Inconsistent JD language leads to mismatched applicants and rework.
- **Risk:** Incomplete audit trails expose the organization during EEO or privacy reviews.
- **Experience:** Candidates wait days for acknowledgment because intake is manual.

### 3.3 Root Causes

1. Fragmented tooling (email, SharePoint, ATS, calendars).
2. No canonical data model across hiring stages.
3. Prompt and automation sprawl without governance.
4. Unclear RACI between HR, TA, and hiring managers.

---

## 4. Current Manual Process

1. Hiring manager emails a Word document to recruiter.
2. Recruiter reformats JD and posts to careers site manually.
3. Applications arrive via portal and email; recruiter downloads attachments.
4. Recruiter reads each resume and updates ATS fields by hand.
5. HM receives unstructured resume summaries via email.
6. Interviewers invent questions independently before each loop.
7. Feedback collected in separate forms; recruiter compiles in spreadsheet.
8. Offer drafted from template with manual copy-paste errors.

**Average cycle time (manual baseline):** 18–25 business days from application to offer for mid-level roles.

---

## 5. Pain Points

| Pain Point | Severity | Frequency | Owner |
|------------|----------|-----------|-------|
| Duplicate candidate records | High | Daily | TA Ops |
| Missing mandatory JD fields | High | Weekly | HRBP |
| Low-confidence extractions accepted silently | Critical | Weekly | AI Ops |
| HM bottleneck on shortlist | Medium | Daily | Hiring Manager |
| Inconsistent interview rubrics | High | Per requisition | TA Lead |
| Delayed feedback submission | Medium | 30% of loops | Interviewers |

Additional pain points specific to **Resume Intake**:

- Inputs arrive without required metadata, blocking automation.
- Reviewers lack explainability for AI-generated recommendations.
- Legacy files (scanned PDFs) break parsing assumptions.

---

## 6. Proposed AI Solution

Classify document type, detect duplicates against existing candidate records, and assign priority based on referral or critical role flags.

### 6.1 Design Principles

1. **Human-in-the-loop by default** for decisions affecting candidate outcomes.
2. **Schema-first** — all AI outputs validate against versioned JSON schemas.
3. **Explainability** — every score or recommendation cites source evidence.
4. **Fail safe** — low confidence routes to human review, never silent pass-through.
5. **Auditability** — prompt version, model ID, and reviewer ID logged per artifact.

### 6.2 Components

| Component | Responsibility |
|-----------|----------------|
| Intake Gateway | Accept files, assign IDs, enforce virus scan |
| AI Orchestrator | Invoke prompts, enforce timeouts, retry policy |
| Validation Service | Schema + business rule checks |
| Review Console | HR/HM approval UI |
| Artifact Store | Immutable storage under `02_Incoming_Resumes/` |
| Metrics Emitter | KPI events to analytics warehouse |

---

## 7. Workflow Trigger

**Primary trigger:** Candidate applies via careers portal, email alias, or recruiter upload.

**Secondary triggers:**
- Scheduled batch reprocessing (nightly) for failed items in dead-letter queue.
- Manual re-run by TA Specialist with `force=true` and documented reason.
- Upstream workflow completion event (webhook `workflow.completed`).

**Preconditions:**
- Active requisition exists with valid department and headcount approval.
- Candidate consent on file where required by jurisdiction.
- Prompt library version compatible with orchestrator runtime.

---

## 8. Inputs

- Resume file
- Application form data
- Source channel
- Consent flags
- Referral metadata

### 8.1 Input Quality Requirements

| Input | Format | Max Size | Required Fields |
|-------|--------|----------|-----------------|
| Primary document | PDF, DOCX, TXT | 10 MB | Readable text layer or OCR path |
| Metadata envelope | JSON | 50 KB | `requisition_id`, `source`, `timestamp` |
| Actor context | JSON | 10 KB | `submitter_email`, `role` |

---

## 9. Outputs

- Intake receipt ID
- Quarantined or accepted file
- Candidate master key
- Routing decision

Outputs are written to `02_Incoming_Resumes/` with naming convention:  
`{requisition_id}_{candidate_id}_{artifact_type}_{iso_timestamp}.{ext}`

---

## 10. Actors

- **Candidate**
- **Recruiter**
- **ATS Webhook**
- **Email Parser**
- **Security Scanner**
- **HR Coordinator**

### RACI Matrix (Summary)

| Activity | TA Specialist | Hiring Manager | AI System | HRBP | Legal |
|----------|---------------|----------------|-----------|------|-------|
| Submit/trigger | R/A | C | I | I | I |
| AI processing | I | I | R/A | I | I |
| Quality review | R | C | I | A | I |
| Approve stage output | C | A | I | R | C |
| Exception override | R | A | I | C | C |

*R = Responsible, A = Accountable, C = Consulted, I = Informed*

---

## 11. Dependencies

| Dependency | Type | Failure Impact |
|------------|------|----------------|
| Upstream workflow completion | Hard | Blocks start |
| Prompt Library v1.x | Hard | Blocks AI step |
| JSON Schema Registry | Hard | Blocks validation |
| ATS API (Workday/Greenhouse) | Soft | Manual fallback |
| Identity Provider (SSO) | Hard | Blocks human review |
| Object storage (SharePoint/S3) | Hard | Blocks artifact persistence |

**Upstream:** Prior workflow in pipeline must emit valid handoff envelope.  
**Downstream:** Next workflow consumes validated outputs only.

---

## 12. Step-by-Step Workflow

### Phase A — Initiation
1. Trigger fires; orchestrator creates `workflow_run_id`.
2. Load workflow config and active prompt versions from registry.
3. Validate inputs (file type, size, required metadata).
4. Write intake record to audit log with SHA-256 of source file.

### Phase B — AI Processing
5. Pre-process document (text extraction or OCR if needed).
6. Invoke AI with system + user prompts from `Prompt.md`.
7. Parse response; attempt JSON extraction if structured output expected.
8. Run schema validation and business rule engine.
9. Compute confidence aggregate; compare to threshold (default 0.85).

### Phase C — Human Review (Conditional)
10. If confidence < threshold OR mandatory review flag → enqueue review task.
11. Reviewer accepts, edits, or rejects with reason code.
12. Edited outputs re-validate before release.

### Phase D — Publication
13. Persist approved artifacts to `02_Incoming_Resumes/`.
14. Emit `workflow.completed` event to downstream subscribers.
15. Update ATS status via API or manual task if API unavailable.
16. Record KPI metrics (latency, automation rate, review rate).

---

## 13. Business Rules

1. **BR-01:** No candidate-facing action without HR review for rejection templates.
2. **BR-02:** Duplicate candidates merged under single `candidate_master_id`.
3. **BR-03:** JD must include EEO statement before external publish.
4. **BR-04:** Match scores below 0.40 auto-archive unless recruiter overrides with justification.
5. **BR-05:** All AI outputs retain prompt version and model ID for 7 years.
6. **BR-06:** PII fields masked in logs; full data only in secured artifact store.
7. **BR-07:** Resume Intake-specific: processing SLA = 4 business hours for standard priority.

---

## 14. Decision Points

| Decision ID | Question | Default Path | Escalation |
|-------------|----------|--------------|------------|
| D-01 | Input valid? | Yes → continue | No → reject + notify submitter |
| D-02 | AI confidence ≥ threshold? | Yes → auto-publish | No → human review |
| D-03 | Schema valid? | Yes → continue | No → retry once, then DLQ |
| D-04 | Duplicate detected? | Merge | Flag for recruiter |
| D-05 | Compliance flag raised? | Hold | Legal review within 24h |

---

## 15. Approval Points

| Gate | Approver | SLA | Outcome |
|------|----------|-----|---------|
| AP-01 | TA Specialist | 4h | Accept AI output for non-decision artifacts |
| AP-02 | Hiring Manager | 24h | Shortlist and interview plan approval |
| AP-03 | HRBP | 48h | Offer/comp band approval |
| AP-04 | Legal | 72h | Non-standard offer terms |

**Never fully automated:** Final hire/reject decision, compensation exceptions, adverse impact overrides.

---

## 16. Exception Handling

| Exception | Detection | Response | Recovery |
|-----------|-----------|----------|----------|
| Invalid file | Magic byte check | Reject + email template | Candidate re-upload |
| OCR failure | Empty text layer | Route to manual transcription | Recruiter entry |
| AI timeout | 120s limit | Exponential backoff retry ×3 | DLQ + alert |
| Invalid JSON | Schema validator | Repair prompt or human fix | Versioned re-run |
| ATS sync failure | HTTP 5xx | Queue retry job | Manual ATS update task |

All exceptions logged with correlation ID linking to `workflow_run_id`.

---

## 17. Success Criteria

1. ≥ 90% of standard-priority items complete within SLA without manual intervention.
2. ≥ 95% of published artifacts pass schema validation on first attempt after review.
3. Zero PII leakage incidents attributable to this workflow.
4. Hiring manager satisfaction ≥ 4.0/5.0 on output usefulness survey.
5. Audit simulation: 100% of sample records traceable to source file and prompt version.

---

## 18. KPIs

| KPI | Definition | Target | Data Source |
|-----|------------|--------|-------------|
| Processing time (P50) | Trigger to published artifact | < 15 min | Orchestrator |
| Processing time (P95) | Same | < 2 hours | Orchestrator |
| Automation rate | Completed without human edit | ≥ 70% | Review console |
| First-pass validation rate | Schema valid post-AI | ≥ 85% | Validator |
| Human review rate | Items entering review queue | ≤ 30% | Review console |
| Error rate | Failed runs / total runs | < 2% | DLQ metrics |
| Rework rate | Re-runs after rejection | < 5% | Audit log |

---

## 19. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Model hallucination on skills | Medium | High | Evidence citations + human review |
| Bias in matching | Medium | Critical | DEI guardrails, regular bias audits |
| Data privacy breach | Low | Critical | Encryption, RBAC, retention policy |
| Over-automation perception | Medium | Medium | Clear RACI, reviewer training |
| Vendor API change | Medium | Medium | Abstraction layer, contract SLAs |
| Prompt drift after model update | High | Medium | Prompt testing SOP before rollout |

---

## 20. Future Improvements

1. **Multimodal parsing** — portfolio links, GitHub, LinkedIn enrichment with consent.
2. **Active learning** — reviewer corrections feed fine-tuning dataset with governance.
3. **Real-time collaboration** — HM and recruiter co-edit shortlist in shared console.
4. **Predictive analytics** — forecast time-to-fill based on funnel metrics.
5. **Cross-lingual support** — parse resumes in Hindi, Spanish, French with locale-specific schemas.
6. **Integration expansion** — native Workday Recruiting bi-directional sync.

---

## Appendix A — Glossary

| Term | Definition |
|------|------------|
| DLQ | Dead-letter queue for failed automation runs |
| HM | Hiring Manager |
| TA | Talent Acquisition |
| JD | Job Description |
| SLA | Service Level Agreement |

## Appendix B — Related Documents

- `02_Incoming_Resumes/Prompt.md`
- `02_Incoming_Resumes/Execution_Flow.md`
- `02_Incoming_Resumes/Automation.md`
- `09_Prompt_Library/` — reusable prompts
- `10_SOPs/` — operational procedures
- `schemas/` — JSON schema definitions

---

*End of Workflow Specification — WF-02*
