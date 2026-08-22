# Incoming Resume Intake — Execution Flow

**Workflow ID:** WF-02  
**Version:** 1.0.0  

---

## 1. Overview

This document describes the runtime execution path for **Incoming Resume Intake**, including automation entry points, AI invocation boundaries, human review gates, storage locations, and failure handling.

---

## 2. Trigger Sources

| Source | Mechanism | Priority |
|--------|-----------|----------|
| ATS webhook | REST POST `/hooks/02_Incoming_Resumes` | Standard |
| Email intake | Parser → object storage | Standard |
| Manual upload | SharePoint drop folder | High |
| Upstream workflow | Event bus `workflow.completed` | Standard |
| Scheduled retry | Cron every 15 min (DLQ) | Low |

---

## 3. Primary Execution Flow

```mermaid
flowchart TD
    A[Trigger Received] --> B{Input Validation}
    B -->|Invalid| C[Reject + Notify Submitter]
    B -->|Valid| D[Create workflow_run_id]
    D --> E[Load Prompt v1.0.0]
    E --> F[Extract Text / OCR]
    F --> G[AI Processing]
    G --> H{JSON Valid?}
    H -->|No| I[Retry / Repair Prompt]
    I --> G
    H -->|Yes| J{Confidence >= 0.85?}
    J -->|Yes| K[Auto-Publish Artifact]
    J -->|No| L[Human Review Queue]
    L --> M{Approved?}
    M -->|Yes| K
    M -->|No| N[Reject + Reason Code]
    K --> O[Write to 02_Incoming_Resumes/]
    O --> P[Emit workflow.completed]
    P --> Q[Update ATS Status]
    C --> R[Log + Metrics]
    N --> R
    Q --> R
```

---

## 4. Sequence Diagram — AI Invocation

```mermaid
sequenceDiagram
    participant T as Trigger
    participant O as Orchestrator
    participant S as Storage
    participant AI as LLM API
    participant V as Validator
    participant H as Human Reviewer
    participant ATS as ATS

    T->>O: New work item
    O->>S: Fetch source document
    O->>AI: System + User prompt
    AI-->>O: JSON response
    O->>V: Schema + business rules
    alt Validation pass, high confidence
        O->>S: Save artifact
        O->>ATS: Status update
    else Low confidence
        O->>H: Review task
        H-->>O: Approve / Edit / Reject
        O->>S: Save approved artifact
    end
```

---

## 5. Storage Map

| Stage | Location | Retention |
|-------|----------|-----------|
| Raw intake | `02_Incoming_Resumes/` (if applicable) | 7 years |
| Processed output | `02_Incoming_Resumes/` | 7 years |
| Failed items | `DLQ/02_Incoming_Resumes/` | 90 days |
| Audit logs | SIEM / Log Analytics | 7 years |
| Review decisions | Review Console DB | 7 years |

---

## 6. Failure Paths

```mermaid
flowchart LR
    F1[AI Timeout] --> R1[Retry x3]
    R1 --> DLQ[Dead Letter Queue]
    F2[Invalid JSON] --> R2[Repair Prompt]
    R2 --> DLQ
    F3[OCR Failure] --> HR[Manual Transcription Task]
    F4[Duplicate] --> MERGE[Merge Workflow]
    DLQ --> OPS[On-call Alert]
```

---

## 7. Latency Budget

| Step | Target P50 | Target P95 |
|------|------------|------------|
| Validation | 2s | 5s |
| Text extraction | 5s | 30s |
| AI call | 15s | 90s |
| Schema validation | 1s | 3s |
| Human review | 4h SLA | 24h SLA |
| **Total automated path** | **< 2 min** | **< 5 min** |

---

## 8. Idempotency

- All runs keyed by `workflow_run_id` + `content_hash`.
- Re-trigger with same hash returns existing artifact unless `force=true`.
- Prevents duplicate ATS updates and double-charging API usage.

---

*End of Execution Flow — WF-02*
