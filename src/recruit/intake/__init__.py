"""Intake — how applications get in without anyone pasting a file.

Phase 6. See `docs/intake_playbook.md`.

Split deliberately in two:

- `mail` — structure. MIME parsing, attachments, filenames, provenance from the
  delivery address. Standards-based, so it was buildable before any real
  job-board message had been seen.
- per-source parsers — meaning. Which part of *this* platform's layout holds the
  applicant's name. Written against captured fixtures, never guessed.
"""

from .mail import Attachment, IncomingMail, MailError, MailTooLarge, parse, sanitise_filename

__all__ = [
    "Attachment",
    "IncomingMail",
    "MailError",
    "MailTooLarge",
    "parse",
    "sanitise_filename",
]
