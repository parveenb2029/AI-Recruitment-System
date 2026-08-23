"""Bias audit harness.

Measures whether the matcher's score moves when a candidate's *substance* is
held constant and only a demographic proxy changes. If it does, the pipeline is
reading a signal it must not.

The method is the resume-audit design from Bertrand & Mullainathan (2004),
adapted: instead of sending resumes to employers, we send perturbed variants
through our own matcher and compare.

**This is an internal quality gate, not a compliance certificate.** NYC Local
Law 144 requires an *independent* bias audit by a third party. Running this and
publishing the result is evidence of diligence and a useful input to that audit;
it is not a substitute for it. See `docs/compliance/`.
"""

from .audit import AuditResult, run_audit
from .perturb import PERTURBATIONS, Variant, generate_variants
from .report import render_markdown

__all__ = [
    "AuditResult", "run_audit",
    "PERTURBATIONS", "Variant", "generate_variants",
    "render_markdown",
]
