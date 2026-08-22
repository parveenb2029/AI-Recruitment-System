# AI Recruitment Operations — Governance Framework

## 1. Purpose
Defines policies for prompt lifecycle, data handling, human oversight, and audit requirements.

## 2. Principles
- Human accountability for all employment decisions
- Schema-first AI outputs with validation gates
- Versioned prompts with eval-before-deploy
- PII minimization and 7-year retention
- Explainability via evidence citations

## 3. RACI Summary
See individual workflow Human_Review.md files and 10_SOPs/.

## 4. Change Management
All prompt changes require: eval run, HR Compliance sign-off, staged rollout (dev→staging→prod).

## 5. Audit Requirements
Every artifact logs: prompt_version, model_id, workflow_run_id, reviewer_id (if applicable).
