# Incoming Resume Intake — Metrics & KPIs

**Workflow ID:** WF-02  
**Version:** 1.0.0  

---

## 1. Metrics Framework

Metrics align to **efficiency**, **quality**, **compliance**, and **experience** dimensions. All metrics emitted as structured events to the analytics warehouse with dimensions: `workflow_id`, `requisition_id`, `prompt_version`, `region`, `priority`.

---

## 2. Primary KPIs

| KPI | Definition | Formula | Target | Alert Threshold |
|-----|------------|---------|--------|-----------------|
| **Processing time (P50)** | Trigger → published artifact | `percentile(latency, 50)` | < 15 min | > 30 min |
| **Processing time (P95)** | Same | `percentile(latency, 95)` | < 2 hours | > 4 hours |
| **Extraction accuracy** | Fields matching human gold set | `correct_fields / total_fields` | ≥ 92% | < 88% |
| **Matching accuracy** | HM agrees with top-quartile match | Survey + outcome | ≥ 85% | < 80% |
| **Human review rate** | Items requiring review | `review_count / total` | ≤ 30% | > 45% |
| **Automation success rate** | Completed without human edit | `auto_publish / total` | ≥ 70% | < 60% |
| **Interview generation time** | Request → published guide | `percentile(latency, 50)` | < 5 min | > 15 min |
| **False positive rate** | Shortlisted but rejected later | `fp / shortlisted` | < 15% | > 20% |
| **False negative rate** | Rejected but HM wanted interview | `fn / rejected` | < 10% | > 15% |
| **Error rate** | Failed runs | `errors / total` | < 2% | > 5% |
| **Override rate** | Human overrides of AI | `overrides / total` | < 8% | > 12% |

---

## 3. Operational Metrics

| Metric | Purpose |
|--------|---------|
| Queue depth | Capacity planning |
| DLQ count | Reliability |
| LLM token usage | Cost management |
| OCR invocation rate | Document quality feedback to sourcing |
| Retry count | Infrastructure health |
| ATS sync failure rate | Integration health |

---

## 4. Dashboards

1. **Executive:** Time-to-fill impact, automation rate, cost per hire delta
2. **TA Operations:** Real-time queue, SLA breaches, review backlog
3. **AI Operations:** Prompt version performance, confidence distributions, error codes
4. **Compliance:** Override audit, PII access logs, bias metric trends

---

## 5. Reporting Cadence

| Report | Audience | Frequency |
|--------|----------|-----------|
| Daily ops snapshot | TA Lead | Daily |
| Weekly KPI review | HR Technology | Weekly |
| Monthly quality report | HRBP + Legal | Monthly |
| Quarterly business review | CHRO | Quarterly |

---

## 6. Baseline & Measurement Method

- **Baseline period:** 90 days pre-automation (manual process timings from ATS timestamps).
- **Gold set:** 200 annotated documents per workflow for accuracy evals.
- **HM agreement surveys:** Embedded in review console, 1-click on 20% sample.

---

*End of Metrics — WF-02*
