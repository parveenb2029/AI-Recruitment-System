# Incoming Resume Intake — Example Output

**Workflow ID:** WF-02  

---

## 1. Successful Output Example

```json
{
  "status": "SUCCESS",
  "workflow_id": "WF-02",
  "prompt_version": "1.0.0",
  "model_id": "gpt-4o-2026-05-01",
  "requisition_id": "REQ-2026-0142",
  "candidate_id": "CAN-88421",
  "processed_at": "2026-08-03T09:18:42Z",
  "confidence_aggregate": 0.93,
  "human_review_required": false,
  "results": {
    "summary": "Strong match for Software Engineer II — 4.5 years Python/Azure experience aligns with core requirements.",
    "key_findings": [
      "Python and Kubernetes experience confirmed in current role",
      "Azure AKS deployment experience matches preferred qualifications",
      "Education requirement met — B.Tech CS 2020"
    ]
  },
  "evidence": [
    {"field": "python_experience", "snippet": "Designed REST microservices in Python", "source_location": "page 1"},
    {"field": "kubernetes", "snippet": "Deployed services on Azure AKS with Docker/Kubernetes", "source_location": "page 1"}
  ],
  "flags": [],
  "artifact_path": "02_Incoming_Resumes/REQ-2026-0142_CAN-88421_output_20260803.json"
}
```

---

## 2. Partial Output Example

```json
{
  "status": "PARTIAL",
  "confidence_aggregate": 0.74,
  "human_review_required": true,
  "review_reasons": ["LOW_CONFIDENCE_EMPLOYMENT_DATES"],
  "flags": ["DATE_AMBIGUITY_TCS_END"]
}
```

---

## 3. Failed Output Example

```json
{
  "status": "FAILED",
  "confidence_aggregate": 0.0,
  "human_review_required": true,
  "review_reasons": ["ENCRYPTED_DOCUMENT"],
  "error_code": "ERR_FILE_ENCRYPTED"
}
```

---

## 4. Downstream Consumption

| Consumer | Uses Field |
|----------|------------|
| Next workflow | Full `results` object |
| ATS | `status`, summary, artifact link |
| Review Console | `flags`, `review_reasons`, evidence |
| Analytics | `confidence_aggregate`, latency metadata |

---

*End of Example Output — WF-02*
