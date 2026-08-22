# Resume Data Extraction — AI Prompt Specification

**Prompt ID:** PROMPT-WF-03  
**Prompt Version:** 1.0.0  
**Prompt Owner:** AI Operations — Prompt Engineering Lead  
**Last Reviewed:** 2026-08-03  
**Model Compatibility:** GPT-4.1+, Claude 3.5+, Azure OpenAI gpt-4o  

---

## Document Purpose

This document defines the production prompt used in **Resume Data Extraction**. Every section exists to ensure repeatability, auditability, and safe deployment across environments. Prompts are treated as **infrastructure-as-code**: versioned, tested, and owned.

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
You are an enterprise recruitment AI assistant specialized in resume extractor for a global technology employer.

ROLE AND BOUNDARIES:
- You process hiring-related documents and data with precision, neutrality, and compliance awareness.
- You NEVER invent credentials, employment dates, scores, or interview outcomes not supported by source material.
- You NEVER infer protected characteristics (age, race, gender, religion, disability, national origin) or use them in recommendations.
- You flag uncertainty explicitly using confidence scores between 0.0 and 1.0 per extracted field or judgment.

OUTPUT REQUIREMENTS:
- Respond ONLY with valid JSON matching the schema provided in the user message unless explicitly asked for prose.
- Include an "evidence" array citing verbatim snippets (max 25 words each) supporting key conclusions.
- Include "prompt_version": "1.0.0" and "workflow_id": "WF-03" in every response.
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
Process the following input for workflow WF-03 (Resume Data Extraction).

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

Return JSON conforming to the RESUME_EXTRACTOR_OUTPUT schema.
Include field-level confidence scores for all extracted or inferred fields.
```

**Why:** Separating metadata from content allows the orchestrator to inject variables safely and redact PII in logs while keeping full content in the model call.

---

## Expected Output

```json
{
  "status": "SUCCESS",
  "workflow_id": "WF-03",
  "prompt_version": "1.0.0",
  "model_id": "gpt-4o-2026-05-01",
  "requisition_id": "REQ-2026-0142",
  "candidate_id": "CAN-88421",
  "processed_at": "2026-08-03T10:30:00Z",
  "confidence_aggregate": 0.93,
  "human_review_required": false,
  "review_reasons": [],
  "flags": [],
  "evidence": [
    {"field": "experience[0].title", "pointer": "/profile/experience/0/title",
     "snippet": "Senior Software Engineer", "source_location": "page 1",
     "char_start": 412, "char_end": 436}
  ],
  "results": {
    "profile": { "...": "candidate profile, shape per schemas/resume.schema.json" },
    "field_confidence": {
      "/personal_info/email": 0.98,
      "/experience/0/start_date": 0.91,
      "/experience/1/end_date": 0.58
    },
    "low_confidence_fields": ["/experience/1/end_date"],
    "conflicts": [],
    "extraction_metadata": {
      "ocr_used": false,
      "pages_processed": 2,
      "content_sha256": "9f2b7c1e...59e0",
      "locale_detected": "en-IN",
      "truncated": false
    },
    "excluded_signals": ["photograph", "date_of_birth", "marital_status", "gender"]
  }
}
```

**Why:** Downstream automation branches on `status`, `human_review_required`, and
`confidence_aggregate`. `PARTIAL` is first-class so partial extractions are never
silently discarded.

`field_confidence` is keyed by **JSON Pointer** into `results.profile` rather than by
field name. That lets the review console flag every field below the 0.60 threshold
(`Validation.md` §6) generically, without hardcoding the profile shape.

`excluded_signals` records attributes that were present in the source and
deliberately not extracted. The bias harness (Phase 4.2) checks that this exclusion
actually happened rather than taking it on trust.

---

## JSON Schema

Canonical schemas live in `schemas/`. WF-03 validates against
**`schemas/WF-03_output.schema.json`**, which composes:

| Schema | Role |
|--------|------|
| `envelope.schema.json` | Shared response envelope — status, versions, evidence, review flags. Defined once, reused by every workflow. |
| `WF-03_results.schema.json` | The WF-03 payload — extracted profile, per-field confidence, conflicts, extraction metadata. |
| `resume.schema.json` | Referenced by the payload for `results.profile`. Reused, not duplicated. |

Validate any output with:

```
python tools/validate_output.py samples/WF-03_output_example.json
```

The script loads `schemas/` into a reference registry so the bare-filename `$ref`s
resolve without the schemas being published anywhere.

**Rules the schema cannot express** — enforce these in the validator:

| Rule | Check |
|------|-------|
| VR-03 | Every `evidence[].snippet` must fuzzy-match the source text at ≥ 0.8, else flag `POTENTIAL_HALLUCINATION`. |
| VR-04 | Employment dates chronologically consistent; `start_date` ≤ `end_date`. |
| — | Every pointer in `field_confidence` must resolve to a real path in `results.profile`. |
| — | `low_confidence_fields` must agree with `field_confidence` and the configured threshold. |

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

*End of Prompt Specification — PROMPT-WF-03*
