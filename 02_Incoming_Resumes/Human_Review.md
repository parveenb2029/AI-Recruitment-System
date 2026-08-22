# Incoming Resume Intake — Human Review Guide

**Workflow ID:** WF-02  
**Version:** 1.0.0  

---

## 1. Automation vs Human Boundaries

| Step | Automation Level | Human Role | Never Fully Automate Because |
|------|------------------|------------|------------------------------|
| File intake & virus scan | Fully automated | Monitor exceptions | — |
| Text extraction / OCR | Automated with fallback | Manual transcription | Quality for scanned docs |
| AI Resume Intake | Automated | Review low-confidence | Accuracy & liability |
| Schema validation | Fully automated | Override with reason | — |
| Publish to artifact store | Automated post-approval | Approve/reject gate | Accountability |
| ATS status update | Automated | Verify on failure | Candidate experience |
| Candidate rejection comms | Draft automated | **HR must approve** | Legal/compliance |
| Final hire decision | AI compiles dossier | **HM + HRBP decide** | Employment law |

---

## 2. Approval Matrix

| Action | TA Specialist | Hiring Manager | HRBP | Legal |
|--------|:-------------:|:--------------:|:----:|:-----:|
| Accept AI extraction | ✓ Approve | Inform | — | — |
| Edit extracted fields | ✓ | — | — | — |
| Approve match for interview | Recommend | ✓ Approve | Inform | — |
| Approve interview guide | Recommend | ✓ Approve | — | Consult |
| Approve offer | Prepare | Recommend | ✓ Approve | Consult |
| Send rejection | Draft | — | ✓ Approve | — |

---

## 3. When Human Review Is Mandatory

1. `confidence_aggregate` < 0.85
2. Any compliance flag present
3. First 50 runs after prompt version change
4. Candidate is internal employee or referral executive
5. HM explicitly enables "always review" on requisition
6. Discrepancy between AI output and prior ATS data

---

## 4. Review SLA

| Priority | Review SLA | Escalation |
|----------|------------|------------|
| Critical role | 2 hours | TA Lead |
| Standard | 4 hours | TA Specialist backup |
| Batch/low | 24 hours | Weekly cleanup |

---

## 5. Reviewer Instructions

1. Open Review Console task linked from email/Teams notification.
2. Compare source document (left pane) with AI output (right pane).
3. Verify evidence snippets support extracted fields.
4. Edit incorrect fields inline; system re-validates on save.
5. Select **Approve**, **Reject**, or **Escalate to Compliance**.
6. Provide reason code for any material override.

---

## 6. Why Humans Must Retain Authority

- **Legal:** Employment decisions require human accountability in most jurisdictions.
- **Ethical:** AI may encode bias; humans apply context and fairness.
- **Quality:** Edge cases (career gaps, non-linear paths) need judgment.
- **Trust:** Hiring managers must own team composition decisions.
- **Compliance:** EEOC and GDPR require explainable, auditable processes.

---

*End of Human Review Guide — WF-02*
