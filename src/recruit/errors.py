"""Typed errors with the reason codes from Error_Handling.md.

Every failure carries a machine-readable `code` so the orchestrator can branch on
it, route to the right recovery path, and put it in the audit log. A bare
traceback is not an acceptable failure mode — it tells a recruiter nothing and
gives the retry logic nothing to decide on.
"""

from __future__ import annotations


class RecruitError(Exception):
    """Base class. `code` is the reason code; `recovery` is what a human can do."""

    code = "ERR_UNKNOWN"
    recovery = "Contact support with the correlation ID."
    retryable = False

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def as_dict(self) -> dict[str, object]:
        return {
            "error_code": self.code,
            "message": self.message,
            "detail": self.detail,
            "recovery": self.recovery,
            "retryable": self.retryable,
        }

    def __str__(self) -> str:
        base = f"[{self.code}] {self.message}"
        return f"{base}\n  detail: {self.detail}" if self.detail else base


# -- intake failures ----------------------------------------------------------
class UnsupportedFormat(RecruitError):
    code = "ERR_UNSUPPORTED_FORMAT"
    recovery = "Convert to PDF, DOCX, or TXT and re-upload."


class InvalidDocument(RecruitError):
    """Extension and magic bytes disagree, or the parser rejected the file."""

    code = "ERR_INVALID_DOCUMENT"
    recovery = "Re-export the document and upload again."


class CorruptDocument(RecruitError):
    code = "ERR_CORRUPT_DOCUMENT"
    recovery = "Request a fresh copy from the candidate."


class FileTooLarge(RecruitError):
    code = "ERR_FILE_TOO_LARGE"
    recovery = "Reduce the file size or split the document."


class EncryptedDocument(RecruitError):
    code = "ERR_FILE_ENCRYPTED"
    recovery = "Ask the candidate for an unprotected copy."


class EmptySource(RecruitError):
    """Readable file, but no usable text — and OCR could not rescue it."""

    code = "EMPTY_SOURCE"
    recovery = "Route to manual transcription in the review console."


class OCRUnavailable(RecruitError):
    """The document needs OCR and no OCR engine is installed.

    Distinct from EmptySource on purpose: this is an operator configuration
    problem, not a bad document. Conflating them would send a perfectly good
    scanned resume to manual transcription and hide a fixable install issue.
    """

    code = "ERR_OCR_UNAVAILABLE"
    recovery = "Install Tesseract and pytesseract, or route to manual transcription."
