"""Ingest tests.

Emphasis on failure modes. A parser that handles the happy path is easy; one
that fails informatively on a corrupt upload at 4pm on a Friday is the point.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pypdf
import pytest

from recruit import errors, ingest

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
RESUME = SAMPLES / "Rahul_Sharma_Resume.pdf"


# -- happy path ---------------------------------------------------------------
@pytest.mark.skipif(not RESUME.is_file(), reason="sample resume not present")
def test_extracts_text_from_real_pdf():
    document = ingest.load(RESUME)
    assert document.char_count > 100
    assert "Rahul Sharma".lower() in document.text.lower()
    assert document.pages == 1
    assert document.ocr_used is False


@pytest.mark.skipif(not RESUME.is_file(), reason="sample resume not present")
def test_hash_is_of_source_bytes_and_is_stable():
    """The idempotency key must not change when a parser library is upgraded."""
    document = ingest.load(RESUME)
    expected = hashlib.sha256(RESUME.read_bytes()).hexdigest()
    assert document.content_sha256 == expected
    assert ingest.load(RESUME).content_sha256 == expected


def test_txt_roundtrip(tmp_path):
    body = "Priya Natarajan\nData engineer with six years of pipeline experience.\n" * 4
    path = tmp_path / "cv.txt"
    path.write_text(body, encoding="utf-8")
    assert "Priya" in ingest.load(path).text


def test_txt_non_utf8_encoding(tmp_path):
    path = tmp_path / "cv.txt"
    path.write_bytes(("Café Society Recruitment. " * 12).encode("cp1252"))
    assert "Caf" in ingest.load(path).text


# -- failure modes ------------------------------------------------------------
def test_missing_file(tmp_path):
    with pytest.raises(errors.InvalidDocument):
        ingest.load(tmp_path / "nope.pdf")


def test_unsupported_extension(tmp_path):
    path = tmp_path / "cv.rtf"
    path.write_bytes(b"{\\rtf1}")
    with pytest.raises(errors.UnsupportedFormat) as exc:
        ingest.load(path)
    assert exc.value.code == "ERR_UNSUPPORTED_FORMAT"


def test_zero_byte_file(tmp_path):
    path = tmp_path / "cv.pdf"
    path.write_bytes(b"")
    with pytest.raises(errors.CorruptDocument):
        ingest.load(path)


def test_extension_does_not_match_content(tmp_path):
    """A .exe renamed to .pdf must never reach the parser."""
    path = tmp_path / "cv.pdf"
    path.write_bytes(b"MZ\x90\x00 this is a windows executable")
    with pytest.raises(errors.InvalidDocument) as exc:
        ingest.load(path)
    assert exc.value.code == "ERR_INVALID_DOCUMENT"


def test_file_too_large(tmp_path):
    path = tmp_path / "cv.pdf"
    path.write_bytes(b"%PDF-1.4" + b"\x00" * (2 * 1024 * 1024))
    with pytest.raises(errors.FileTooLarge):
        ingest.load(path, max_mb=1)


def test_encrypted_pdf(tmp_path):
    path = tmp_path / "locked.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.encrypt("hunter2")
    with path.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(errors.EncryptedDocument) as exc:
        ingest.load(path)
    assert exc.value.code == "ERR_FILE_ENCRYPTED"


def test_truncated_pdf(tmp_path):
    path = tmp_path / "cut.pdf"
    path.write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog")
    with pytest.raises(errors.CorruptDocument):
        ingest.load(path)


def test_blank_pdf_raises_empty_source(tmp_path):
    path = tmp_path / "blank.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with path.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(errors.EmptySource) as exc:
        ingest.load(path, allow_ocr=False)
    assert exc.value.code == "EMPTY_SOURCE"


def test_text_below_threshold(tmp_path):
    path = tmp_path / "cv.txt"
    path.write_text("Hi.", encoding="utf-8")
    with pytest.raises(errors.EmptySource):
        ingest.load(path)


# -- error contract -----------------------------------------------------------
def test_every_error_carries_a_code_and_recovery():
    """No failure may reach a recruiter as a bare traceback."""
    subclasses = [
        value
        for value in vars(errors).values()
        if isinstance(value, type)
        and issubclass(value, errors.RecruitError)
        and value is not errors.RecruitError
    ]
    assert len(subclasses) >= 7
    for cls in subclasses:
        instance = cls("boom")
        assert instance.code != "ERR_UNKNOWN", f"{cls.__name__} has no reason code"
        assert instance.recovery, f"{cls.__name__} has no recovery guidance"
        assert "error_code" in instance.as_dict()
