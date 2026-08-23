"""Review console — the screen a recruiter actually uses.

A recruiter clears 100 candidates in a sitting. Every second of friction per
candidate is two minutes of their afternoon, so this is built for speed and for
trust, in that order:

- **Speed** — keyboard-first. Approve, reject, next, all without the mouse.
- **Trust** — every extracted field links to the exact span of the source
  document it came from. Without that, a reviewer is guessing, and the whole
  evidence-citation design is wasted effort.
"""

from .app import create_app

__all__ = ["create_app"]
