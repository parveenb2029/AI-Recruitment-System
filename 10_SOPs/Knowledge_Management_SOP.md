# Knowledge Management — Standard Operating Procedure

**SOP ID:** SOP-KNOWLEDGE_MANAGEMENT  
**Version:** 1.0.0  
**Effective Date:** 2026-08-03  
**Classification:** Internal  

---

## 1. Purpose

This Standard Operating Procedure (SOP) defines the repeatable process, roles, and controls for **knowledge management** within the AI Recruitment Operations platform. It ensures consistent execution, regulatory compliance, and alignment with enterprise talent acquisition policies.

---

## 2. Scope

**In scope:**
- All full-time employee requisitions processed through the AI Recruitment Operations pipeline
- TA Specialists, Recruiters, Hiring Managers, HRBPs, and Interviewers using automated workflows 01–08
- Prompt library assets and automation integrations supporting knowledge management

**Out of scope:**
- Contractor/contingent workforce (see Contingent Workforce SOP)
- Executive search retained firms
- Pre-offer background check vendor operations (referenced only)

---

## 3. Owner

| Role | Name/Title | Contact |
|------|------------|---------|
| **Process Owner** | Director, Talent Acquisition Operations | ta-ops@contoso.com |
| **Document Owner** | AI Operations Lead | ai-ops@contoso.com |
| **Compliance Owner** | HR Compliance Manager | hr-compliance@contoso.com |

---

## 4. Frequency

| Activity | Frequency |
|----------|-----------|
| Execute process | Per requisition / per candidate event |
| SOP compliance audit | Quarterly |
| SOP document review | Semi-annual |
| Training refresh | Annual + on role change |

---

## 5. Procedure

### 5.1 Initiation
1. Verify requisition is approved in ATS with valid headcount.
2. Confirm AI workflows enabled for department (check `docs/rollout_matrix.md`).
3. Assign TA Specialist as primary operator for requisition.

### 5.2 Execution — Knowledge Management
1. Follow workflow-specific documentation in folders `01_Job_Descriptions/` through `08_Final_Decision/`.
2. Monitor Review Console for items exceeding SLA.
3. Document manual overrides with reason codes in ATS notes.
4. Escalate compliance flags within prescribed timeframes (see Section 9).

### 5.3 Quality Checks
1. Verify AI outputs against source documents before HM presentation.
2. Confirm prompt version logged in artifact metadata.
3. Complete spot-check per AI Quality Review SOP (10% sample weekly).

### 5.4 Closure
1. Update ATS stage to reflect completed process step.
2. Archive artifacts in designated SharePoint library.
3. Emit metrics event for reporting dashboard.

---

## 6. Roles and Responsibilities

| Role | Responsibilities |
|------|------------------|
| **TA Specialist** | Operate workflows, first-line review, candidate communication coordination |
| **Recruiter** | Source candidates, manage pipeline, schedule interviews |
| **Hiring Manager** | Approve shortlists, interview guides, final hire decision |
| **HRBP** | Offer approval, policy exceptions, org alignment |
| **Interviewer** | Conduct interviews, submit timely feedback |
| **AI Operations** | Maintain prompts, automation, incident response |
| **Legal/Compliance** | Review non-standard templates, adverse impact concerns |
| **Privacy Officer** | Data subject requests, retention, cross-border transfers |

---

## 7. Approvals

| Step | Approver | Evidence Required |
|------|----------|-------------------|
| Workflow output publication (standard) | TA Specialist | Validation pass log |
| Shortlist approval | Hiring Manager | Match report + summaries |
| Interview guide | Hiring Manager | Generated question set |
| Offer release | HRBP + HM | Decision dossier |
| Rejection at final stage | HRBP | Rejection template approval |
| Prompt production deploy | AI Ops Lead + HR Compliance | Eval results |

---

## 8. Risks

| Risk | Impact | Control |
|------|--------|---------|
| Biased screening | Legal, reputational | DEI audits, blind review options |
| PII mishandling | Regulatory fines | Data Privacy SOP, encryption |
| Over-reliance on AI | Poor hires | Mandatory human gates |
| Process bypass | Audit failure | ATS-enforced stage gates |
| Stale documentation | Operational errors | Semi-annual SOP review |

---

## 9. Escalation

| Level | Trigger | Escalate To | Timeframe |
|-------|---------|-------------|-----------|
| L1 | SLA breach, single error | TA Team Lead | 4 hours |
| L2 | Compliance flag, bias concern | HR Compliance | 24 hours |
| L3 | PII incident, system outage | CISO + HR Director | Immediate |
| L4 | Legal hold, litigation | Legal Counsel | Immediate |

**Escalation channel:** `#talent-tech-incidents` Teams channel + ServiceNow ticket category `HR-AI-OPS`.

---

## 10. Related Documents

- `10_SOPs/` — all companion SOPs
- `01_Job_Descriptions/` through `08_Final_Decision/` — workflow specs
- `09_Prompt_Library/` — governed prompts
- `docs/governance_framework.md`

---

## 11. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2026-08-03 | AI Operations | Initial release |

---

*End of SOP — Knowledge Management*
