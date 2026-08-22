# Interview Feedback Processing — Example Input

**Workflow ID:** WF-07  

---

## 1. Overview

This document provides a realistic example input for **Interview Feedback Processing** as would be received in production.

---

## 2. Metadata Envelope

```json
{
  "workflow_id": "WF-07",
  "requisition_id": "REQ-2026-0142",
  "candidate_id": "CAN-88421",
  "workflow_run_id": "RUN-7f3a2b1c-2026-0803-001",
  "source_channel": "careers_portal",
  "priority": "standard",
  "submitted_at": "2026-08-03T09:15:00+05:30",
  "submitter_email": "talent.acquisition@contoso.com",
  "schema_version": "1.0.0",
  "source_file": {
    "name": "Rahul_Sharma_Resume.pdf",
    "mime_type": "application/pdf",
    "size_bytes": 245760,
    "sha256": "a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456"
  }
}
```

---

## 3. Primary Content

See `samples/` for full files. Excerpt for **Feedback Processor**:

---

### Job Description Example (WF-01)

```
Software Engineer II — Cloud Platform
Department: Engineering | Location: Bangalore (Hybrid)
Experience: 3–5 years

We are seeking a Software Engineer II to build scalable microservices on Azure...

Required Skills: Python, REST APIs, Docker, Kubernetes, SQL
Preferred: Azure, CI/CD, system design
Education: BS Computer Science or equivalent
```

---

### Resume Excerpt (WF-02/03)

```
RAHUL SHARMA
Email: rahul.sharma@email.com | Phone: +91-98765-43210 | Bangalore, India

SUMMARY
Software engineer with 4.5 years building backend services and cloud-native applications.

EXPERIENCE
Senior Software Engineer | Infosys | Jan 2022 – Present
- Designed REST microservices in Python serving 2M daily requests
- Deployed services on Azure AKS with Docker/Kubernetes
- Reduced API latency 35% via query optimization and caching

Software Engineer | TCS | Jun 2020 – Dec 2021
- Built CI/CD pipelines using Azure DevOps
- Developed SQL reporting modules for enterprise clients

EDUCATION
B.Tech Computer Science, VTU, 2020 — CGPA 8.4/10

SKILLS
Python, Java, REST, Docker, Kubernetes, Azure, PostgreSQL, Git
```

---

## 4. Input Validation Checklist

- [x] Valid file format
- [x] Required metadata present
- [x] Requisition exists and is OPEN
- [x] Consent flag true
- [x] File size within limits

---

*End of Example Input — WF-07*
