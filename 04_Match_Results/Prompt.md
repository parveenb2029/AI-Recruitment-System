# JD-Candidate Matching — AI Prompt Specification

**Prompt ID:** PROMPT-WF-04  
**Prompt Version:** 1.0.0  
**Prompt Owner:** AI Operations — Prompt Engineering Lead  
**Last Reviewed:** 2026-08-03  
**Model Compatibility:** GPT-4.1+, Claude 3.5+, Azure OpenAI gpt-4o  

---

## Document Purpose

This document defines the production prompt used in **JD-Candidate Matching**. Every section exists to ensure repeatability, auditability, and safe deployment across environments. Prompts are treated as **infrastructure-as-code**: versioned, tested, and owned.

---

## Why Each Section Exists

| Section | Why It Exists |
|---------|---------------|
| System Prompt | Sets immutable behavioral guardrails, tone, compliance constraints, and output format the model must never violate. |
| User Prompt | Carries task-specific variables and the actual document/data to process for this workflow run. |
| Expected Output | Defines the contract downstream validators and humans rely on; prevents ambiguous free-text when structure is required. |
| JSON Schema | Enables automated validation, ATS mapping, and type-safe integrations. |
| Validation Rules | Business logic beyond JSON Schema (cross-field checks, confidence thresholds). |
| Examples | Few-shot anchors reduce format drift and establish quality bar for evals. |
| Edge Cases | Documents known failure modes so operators and evaluators test them explicitly. |
| Prompt Version | Supports rollback, A/B testing, and audit ("which prompt produced this artifact?"). |
| Prompt Owner | Accountability for changes, incidents, and approval workflow per Prompt Governance SOP. |
| Prompt Notes | Operational context: known limitations, tuning history, deployment caveats. |

---

## System Prompt

```
You are an enterprise recruitment AI assistant specialized in matcher for a global technology employer.

ROLE AND BOUNDARIES:
- You process hiring-related documents and data with precision, neutrality, and compliance awareness.
- You NEVER invent credentials, employment dates, scores, or interview outcomes not supported by source material.
- You NEVER infer protected characteristics (age, race, gender, religion, disability, national origin) or use them in recommendations.
- You flag uncertainty explicitly using confidence scores between 0.0 and 1.0 per extracted field or judgment.

OUTPUT REQUIREMENTS:
- Respond ONLY with valid JSON matching the schema provided in the user message unless explicitly asked for prose.
- Include an "evidence" array citing verbatim snippets (max 25 words each) supporting key conclusions.
- Include "prompt_version": "1.0.0" and "workflow_id": "WF-04" in every response.
- Use ISO 8601 dates. Use canonical skill names from the provided skills ontology when available.

COMPLIANCE:
- Apply GDPR/CCPA minimization: do not repeat full government IDs, full DOB, or unnecessary PII in summaries.
- If source document is unreadable or empty, return status "FAILED" with reason code — do not guess.

TONE:
- Professional, concise, audit-ready language suitable for HR systems and hiring manager review.
```

**Why:** The system prompt is the security and compliance kernel. It applies to every invocation regardless of input variation.

---

## User Prompt Template

```
Process the following input for workflow WF-04 (JD-Candidate Matching).

=== METADATA ===
requisition_id: {{requisition_id}}
candidate_id: {{candidate_id}}
workflow_run_id: {{workflow_run_id}}
source_channel: {{source_channel}}
priority: {{priority}}

=== PRIMARY CONTENT ===
{{document_text_or_structured_input}}

=== REFERENCE SCHEMA VERSION ===
{{schema_version}}

=== OPTIONAL CONTEXT ===
{{additional_context}}

Return JSON conforming to the MATCHER_OUTPUT schema.
Include field-level confidence scores for all extracted or inferred fields.
```

**Why:** Separating metadata from content allows the orchestrator to inject variables safely and redact PII in logs while keeping full content in the model call.

---

## Expected Output

```json
{
  "status": "SUCCESS",
  "workflow_id": "WF-04",
  "prompt_version": "1.0.0",
  "model_id": "gpt-4o-2026-05-01",
  "requisition_id": "REQ-2026-0142",
  "candidate_id": "CAN-88421",
  "processed_at": "2026-08-03T10:30:00Z",
  "confidence_aggregate": 0.90,
  "human_review_required": false,
  "review_reasons": [],
  "flags": [],
  "results": {
    "overall_score": 0.82,
    "recommendation": "STRONG_MATCH",
    "components": [
      {
        "component_id": "must_have_coverage",
        "raw_score": 0.86, "weight": 0.5, "weighted_score": 0.43, "confidence": 0.93,
        "rationale": "Six of seven must-have skills evidenced; Terraform absent.",
        "evidence": [{"field": "python", "snippet": "Designed REST microservices in Python"}]
      },
      {
        "component_id": "experience_band",
        "raw_score": 0.80, "weight": 0.3, "weighted_score": 0.24, "confidence": 0.88,
        "rationale": "4.5 years against a 4-7 year band; lower end.",
        "evidence": [{"field": "tenure", "snippet": "4.5 years of experience"}]
      },
      {
        "component_id": "domain_match",
        "raw_score": 0.75, "weight": 0.2, "weighted_score": 0.15, "confidence": 0.81,
        "rationale": "Cloud-native backend matches; no fintech exposure.",
        "evidence": [{"field": "domain", "snippet": "backend services and cloud-native applications"}]
      }
    ],
    "weighting": {
      "scheme_id": "swe-ic-default",
      "scheme_version": "1.0.0",
      "weights": {"must_have_coverage": 0.5, "experience_band": 0.3, "domain_match": 0.2}
    },
    "must_have_requirements": [
      {"requirement_id": "MH-01", "requirement": "Python", "status": "MET"},
      {"requirement_id": "MH-03", "requirement": "Terraform", "status": "NOT_MET"},
      {"requirement_id": "MH-04", "requirement": "On-call experience", "status": "UNKNOWN"}
    ],
    "gaps": [
      {"requirement": "Terraform", "severity": "SIGNIFICANT", "note": "No IaC tooling evidenced."}
    ],
    "auto_archive_eligible": false,
    "excluded_signals": ["name", "gender", "age", "nationality", "university_prestige", "address"]
  }
}
```

**Why the score is decomposed.** The model judges each component on its own merits and
cites evidence for each. `overall_score` and every `weighted_score` are then computed
**in application code** from weights held in `config/organization.yaml`. The model never
returns an overall fit score.

This matters for three reasons. It is **tunable** — change a weight in config and the
result moves predictably. It is **auditable** — a recruiter can see which dimension drove
the outcome. And it is **defensible** — if a rejection is ever challenged, "0.61 overall"
is not an answer, whereas "Terraform not evidenced, worth 15% of the must-have component"
is.

`UNKNOWN` is deliberately distinct from `NOT_MET`. Absence of evidence is not evidence of
absence, and collapsing the two silently rejects candidates for things nobody asked them.

---

## JSON Schema

Canonical schemas live in `schemas/`. WF-04 validates against
**`schemas/WF-04_output.schema.json`**, which composes:

| Schema | Role |
|--------|------|
| `envelope.schema.json` | Shared response envelope — status, versions, evidence, review flags. Defined once, reused by every workflow. |
| `WF-04_results.schema.json` | The WF-04 payload — decomposed component scores, weighting provenance, requirement resolution, gaps. |

Validate any output with:

```
python tools/validate_output.py samples/WF-04_output_example.json
```

`results` sets `additionalProperties: false` on purpose: it makes it impossible to
smuggle an undeclared overall score into the payload.

**Rules the schema cannot express** — enforce these in the validator:

| Rule | Check |
|------|-------|
| BV-04 | `weighting.weights` values must sum to 1.0 (± 0.001). JSON Schema cannot do arithmetic. |
| — | `overall_score` must equal the sum of `components[].weighted_score` (± 0.001). |
| — | Each `weighted_score` must equal `raw_score × weight` (± 0.001). |
| — | Every `component_id` must have a matching key in `weighting.weights`. |
| BR-04 | `auto_archive_eligible` must be true exactly when `overall_score < 0.40`. |
| VR-03 | Every `evidence[].snippet` must fuzzy-match the source at ≥ 0.8. |

---

## Validation Rules

| Rule ID | Rule | Action on Fail |
|---------|------|----------------|
| VR-01 | `confidence_aggregate` ≥ 0.85 for auto-publish | Route to human review |
| VR-02 | All required schema fields present | Retry with repair prompt once |
| VR-03 | Evidence snippets must appear in source text (fuzzy match ≥ 0.8) | Flag `POTENTIAL_HALLUCINATION` |
| VR-04 | Dates must be chronologically consistent | Flag for reviewer |
| VR-05 | No protected-class terms in recommendation fields | Block + compliance alert |
| VR-06 | `prompt_version` matches deployed version | Reject response |

---

## Examples

### Example 1 — Successful Processing

**Input excerpt:** Standard software engineer resume with clear employment history.  
**Output excerpt:**
```json
{"status": "SUCCESS", "confidence_aggregate": 0.94, "human_review_required": false}
```

### Example 2 — Partial Success (OCR noise)

**Input excerpt:** Scanned PDF with garbled dates in one role.  
**Output excerpt:**
```json
{"status": "PARTIAL", "confidence_aggregate": 0.71, "human_review_required": true, "review_reasons": ["LOW_CONFIDENCE_DATES"]}
```

### Example 3 — Failed (Empty document)

**Output excerpt:**
```json
{"status": "FAILED", "confidence_aggregate": 0.0, "human_review_required": true, "review_reasons": ["EMPTY_SOURCE"]}
```

**Why:** Examples anchor evaluation suites and onboarding for new prompt engineers.

---

## Edge Cases

| Edge Case | Expected Behavior |
|-----------|-------------------|
| Password-protected PDF | Return FAILED, reason `ENCRYPTED_DOCUMENT` |
| Non-English resume | Process if readable; set `locale_detected`; lower confidence if untranslated |
| 20+ page CV | Summarize oldest roles; retain last 10 years in detail |
| Candidate applies to multiple reqs | Include `requisition_id` in output; never merge profiles automatically |
| Conflicting dates | List conflict in `flags`; never silently resolve |
| Model returns markdown fences | Strip fences in post-processor before JSON parse |

---

## Prompt Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2026-08-03 | AI Ops Team | Initial production release |

---

## Prompt Owner

**Primary:** Prompt Engineering Lead — Talent Technology  
**Backup:** Senior AI Operations Specialist  
**Approval required from:** HR Compliance (material changes affecting candidate evaluation)

---

## Prompt Notes

- Temperature recommendation: **0.1** for extraction tasks; **0.3** for question generation.
- Max tokens: 4096 output; increase to 8192 for senior executive resumes.
- Known limitation: tables in multi-column PDFs may misalign skills — prefer DOCX intake when possible.
- Run regression eval (`Prompt Testing SOP`) before any version bump.
- Do not deploy prompt changes during active offer approval windows without change advisory.

---

*End of Prompt Specification — PROMPT-WF-04*
