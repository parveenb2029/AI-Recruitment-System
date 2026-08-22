# Prompt Library — Email Generator

**Prompt ID:** LIB-EMAIL_GENERATOR  
**Version:** 1.0.0  
**Owner:** Prompt Engineering Lead  
**Last Reviewed:** 2026-08-03  

---

## Overview

Production prompt for **Email Generator** in the AI Recruitment Operations platform. Used across one or more workflows; see cross-references below.

---

## Why Each Section Exists

| Section | Rationale |
|---------|-----------|
| System Prompt | Immutable guardrails for compliance, format, and behavior |
| User Prompt | Variable injection point for runtime data |
| Expected Output | Contract for validators and integrations |
| JSON Schema | Machine-readable validation |
| Validation Rules | Business logic beyond schema |
| Examples | Few-shot quality anchors |
| Edge Cases | Documented test scenarios |
| Version/Owner/Notes | Governance and audit trail |

---

## System Prompt

```
You are an enterprise recruitment AI performing email generator for {{org.legal_name}}.

RULES:
- Base all outputs strictly on provided source documents.
- Never infer protected characteristics or use them in decisions.
- Output valid JSON unless prose template explicitly requested.
- Include evidence snippets (max 25 words) for material claims.
- Set human_review_required=true when confidence < 0.85.
- Include prompt_version and prompt_id in every response.

COMPLIANCE: GDPR/CCPA minimization. EEO-neutral language. No discriminatory questions.
```

---

## User Prompt Template

```
Execute Email Generator for the following inputs.

requisition_id: {{requisition_id}}
candidate_id: {{candidate_id}}
workflow_run_id: {{workflow_run_id}}

=== PRIMARY SOURCE ===
{{source_content}}

=== OPTIONAL CONTEXT ===
{{context}}

Return output conforming to email_generator_output schema.
```

---

## Expected Output

Structured JSON with: `status`, `prompt_id`, `prompt_version`, `confidence_aggregate`, `results`, `evidence[]`, `human_review_required`, `flags[]`.

---

## JSON Schema Reference

Canonical schema: `schemas/prompt_metadata.json` (envelope) + workflow-specific extensions in `schemas/`.

---

## Validation Rules

- VR-01: confidence ≥ 0.85 for auto-publish
- VR-02: evidence fuzzy-match against source ≥ 0.8
- VR-03: no protected-class language in decision fields
- VR-04: required fields per schema

---

## Examples

See `samples/` and workflow `Example_Output.md` files for full worked examples.

---

## Edge Cases

- Empty source → FAILED
- Encrypted PDF → FAILED with ERR_FILE_ENCRYPTED
- Multi-language → process with locale tag, reduce confidence if uncertain
- Conflicting sources → flag, do not merge silently

---

## Cross-References

| Workflow | Usage |
|----------|-------|
| 01 Job Descriptions | JD Parser |
| 03 Extracted Data | Resume Parser |
| 04 Match Results | JD Matcher |
| 05 Shortlisted | Candidate Summary |
| 06 Interview Questions | Interview Generator |
| 07 Interview Feedback | Interview Evaluation |
| 08 Final Decision | Offer Letter, Email, Rejection |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-08-03 | Initial production release |

---

*End of Prompt Library Entry — Email Generator*
