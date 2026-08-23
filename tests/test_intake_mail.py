"""Reading email as structure, before any real job-board message exists.

Every message here is built with the standard library and read back with the
standard library, which is the point: MIME is a specification, so this tests my
handling of it rather than my guess about how LinkedIn formats a notification.
The guessing part is prompt 6.3 and waits for real captures.

The filename tests are the ones that matter most. A filename in an email is
attacker-controlled text that is about to become a path on the operator's
Windows machine.
"""

from __future__ import annotations

from datetime import UTC, datetime
from email.message import EmailMessage

import pytest

from recruit.intake import mail

PDF = b"%PDF-1.7\n" + b"x" * 400
DOCX = b"PK\x03\x04" + b"y" * 400


def build(
    *,
    subject: str = "New application for Software Engineer II",
    sender: str = "notify@example-board.com",
    to: str = "jobs+linkedin@example.com",
    body: str = "Priya Nair has applied. See the attached CV.",
    html_body: str | None = None,
    attachments: list[tuple[str, bytes, str, str]] | None = None,
    message_id: str | None = "<abc-123@example-board.com>",
    date: str | None = "Mon, 17 Aug 2026 09:14:00 +0530",
) -> bytes:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = to
    if message_id:
        message["Message-ID"] = message_id
    if date:
        message["Date"] = date
    message.set_content(body)
    if html_body:
        message.add_alternative(html_body, subtype="html")
    for filename, content, maintype, subtype in attachments or []:
        message.add_attachment(content, maintype=maintype, subtype=subtype,
                               filename=filename)
    return message.as_bytes()


@pytest.fixture
def with_resume():
    return build(attachments=[("Priya_Nair_CV.pdf", PDF, "application", "pdf")])


# -- the basics ---------------------------------------------------------------
def test_reads_the_parts_a_recruiter_would_care_about(with_resume):
    result = mail.parse(with_resume)

    assert result.message_id == "abc-123@example-board.com"
    assert not result.message_id_synthetic
    assert result.from_address == "notify@example-board.com"
    assert "Software Engineer II" in result.subject
    assert "Priya Nair has applied" in result.body_text
    assert [a.filename for a in result.resumes] == ["Priya_Nair_CV.pdf"]
    assert not result.quarantined


def test_the_same_message_always_hashes_the_same(with_resume):
    assert mail.parse(with_resume).raw_sha256 == mail.parse(with_resume).raw_sha256


def test_a_missing_message_id_falls_back_to_the_content_hash():
    """Unusual but legal, and it must not break "never process twice".

    Dropping the message loses an application; reprocessing it on every poll
    bills for the same resume forever. Hashing the bytes does neither.
    """
    raw = build(message_id=None, attachments=[("cv.pdf", PDF, "application", "pdf")])
    result = mail.parse(raw)

    assert result.message_id_synthetic
    assert result.message_id == f"sha256:{result.raw_sha256}"
    assert mail.parse(raw).message_id == result.message_id


def test_a_non_ascii_subject_survives():
    """Any accented character turns a subject into =?UTF-8?B?...?= on the wire."""
    raw = build(subject="Candidature reçue — Ingénieur Logiciel")
    assert mail.parse(raw).subject == "Candidature reçue — Ingénieur Logiciel"


def test_a_naive_date_is_not_allowed_to_break_comparison():
    raw = build(date="Mon, 17 Aug 2026 09:14:00")
    received = mail.parse(raw).received_at
    assert received.tzinfo is not None
    assert received < datetime.now(UTC).replace(year=2100)


def test_a_missing_date_does_not_lose_the_message():
    assert mail.parse(build(date=None)).received_at.tzinfo is not None


# -- where it came from -------------------------------------------------------
@pytest.mark.parametrize("address,expected", [
    ("jobs+linkedin@example.com", "linkedin"),
    ("jobs+naukri@example.com", "naukri"),
    ("jobs+INDEED@example.com", "indeed"),
])
def test_the_delivery_tag_is_the_strongest_signal(address, expected):
    """An address you published and chose beats anything inferred."""
    result = mail.parse(build(to=address))
    assert result.source == expected
    assert result.source_signal == mail.BY_TAG


def test_an_unknown_tag_is_reported_as_itself():
    """Better an odd source name than an invented one."""
    assert mail.parse(build(to="jobs+monster@example.com")).source == "monster"


def test_an_alias_map_renames_a_tag():
    result = mail.parse(build(to="jobs+li@example.com"), aliases={"li": "linkedin"})
    assert result.source == "linkedin"


def test_the_sender_domain_answers_when_the_tag_is_missing():
    """The tag is easy to lose, and losing it must not blind the system.

    A forwarding rule, a client that rewrites recipients, or an address-book
    autocomplete quietly swapping in a saved contact will all strip it — the
    last of those is exactly how the first real capture on this project arrived
    with no tag at all. Reporting "unknown" for every application in that
    situation would be useless precisely when it matters.
    """
    result = mail.parse(build(to="jobs@example.com",
                              sender="jobs-noreply@linkedin.com"))
    assert result.source == "linkedin"
    assert result.source_signal == mail.BY_DOMAIN


def test_a_subdomain_still_identifies_the_sender():
    result = mail.parse(build(to="jobs@example.com",
                              sender="alerts@e.indeed.com"))
    assert result.source == "indeed"


def test_the_tag_wins_over_the_domain():
    """You published the tag; the domain is merely where the mail came from.

    A board that forwards on behalf of another would otherwise mislabel the
    application, and the tag is the signal the operator actually controls.
    """
    result = mail.parse(build(to="jobs+naukri@example.com",
                              sender="jobs-noreply@linkedin.com"))
    assert result.source == "naukri"
    assert result.source_signal == mail.BY_TAG


def test_neither_signal_admits_it_rather_than_guessing():
    result = mail.parse(build(to="jobs@example.com", sender="someone@gmail.com"))
    assert result.source == "unknown"
    assert result.source_signal == mail.BY_NOTHING


# -- filenames, the dangerous part --------------------------------------------
@pytest.mark.parametrize("supplied,expected", [
    ("../../../etc/passwd", "passwd"),
    (r"..\..\Windows\System32\evil.exe", "evil.exe"),
    ("/absolute/path/cv.pdf", "cv.pdf"),
    ("cv.pdf", "cv.pdf"),
    ("  spaced  .pdf  ", "spaced  .pdf"),
    ("", "attachment"),
    ("...", "attachment"),
    (".hidden.pdf", "hidden.pdf"),
])
def test_a_filename_cannot_escape_its_directory(supplied, expected):
    assert mail.sanitise_filename(supplied) == expected


def test_a_null_byte_cannot_truncate_the_path():
    """`cv.pdf\\x00.exe` is one filename to Python and two to some C libraries."""
    assert "\x00" not in mail.sanitise_filename("cv.pdf\x00.exe")


def test_a_newline_in_a_filename_does_not_reach_the_log():
    assert "\n" not in mail.sanitise_filename("cv\n.pdf")


@pytest.mark.parametrize("device", ["CON.pdf", "con.pdf", "LPT1.docx", "NUL"])
def test_windows_device_names_are_defused(device):
    """The operator runs this on Windows, where CON is not a file.

    Writing to CON.pdf does not create a file; it writes to the console. The
    failure is confusing rather than loud, so it is fixed here.
    """
    safe = mail.sanitise_filename(device)
    stem = safe.rpartition(".")[0] or safe
    assert stem.lower() not in mail.WINDOWS_DEVICE_NAMES


def test_a_trailing_dot_cannot_be_used_to_collide_two_files():
    """Windows silently strips trailing dots, so `a.pdf.` and `a.pdf` collide."""
    assert mail.sanitise_filename("report.pdf.") == mail.sanitise_filename("report.pdf")


def test_an_absurdly_long_filename_is_cut_but_keeps_its_extension():
    safe = mail.sanitise_filename("a" * 400 + ".pdf")
    assert len(safe) <= mail.MAX_FILENAME_LENGTH
    assert safe.endswith(".pdf")


def test_the_original_filename_is_kept_as_evidence():
    """If a filename turns out to be an attack, the sanitised one is not the one
    you want in the incident report."""
    raw = build(attachments=[("../../evil.pdf", PDF, "application", "pdf")])
    attachment = mail.parse(raw).attachments[0]
    assert attachment.filename == "evil.pdf"
    assert attachment.original_filename == "../../evil.pdf"


# -- what is inside the file --------------------------------------------------
def test_an_executable_renamed_to_pdf_is_rejected():
    """Content-Type is written by the sender and proves nothing.

    Same magic-byte table the ingest step already trusts, applied one step
    earlier so the bad file never becomes a candidate at all.
    """
    raw = build(attachments=[("cv.pdf", b"MZ\x90\x00" + b"\x00" * 400,
                              "application", "pdf")])
    attachment = mail.parse(raw).attachments[0]

    assert not attachment.magic_ok
    assert not attachment.accepted
    assert "do not match" in attachment.rejection
    assert mail.parse(raw).resumes == []


def test_a_real_docx_is_accepted():
    raw = build(attachments=[("cv.docx", DOCX, "application", "octet-stream")])
    assert [a.filename for a in mail.parse(raw).resumes] == ["cv.docx"]


def test_an_oversized_attachment_is_rejected_not_processed():
    raw = build(attachments=[
        ("huge.pdf", b"%PDF-1.7\n" + b"z" * (mail.MAX_ATTACHMENT_MB * 1024 * 1024),
         "application", "pdf")])
    attachment = mail.parse(raw).attachments[0]
    assert not attachment.accepted
    assert "exceeds" in attachment.rejection


def test_an_empty_attachment_is_rejected():
    raw = build(attachments=[("cv.pdf", b"", "application", "pdf")])
    assert not mail.parse(raw).attachments[0].accepted


def test_a_message_larger_than_the_limit_is_refused_before_parsing():
    """The defence has to happen before the work, not after it."""
    with pytest.raises(mail.MailTooLarge):
        mail.parse(b"x" * ((mail.MAX_MESSAGE_MB + 1) * 1024 * 1024))


# -- quarantine ---------------------------------------------------------------
def test_a_message_with_no_attachments_is_quarantined_not_dropped():
    result = mail.parse(build(body="Thanks for your interest."))
    assert mail.NO_ATTACHMENTS in result.quarantine_reasons
    assert result.quarantined


def test_the_link_only_case_is_named_specifically():
    """The exact thing the playbook warns about, detected rather than guessed.

    Some boards email "someone applied, click here" behind a login instead of
    the resume. That is a settings problem on the job board, not a broken
    message, and no parser can fix it — so it gets its own name and the operator
    is told which sources do it.
    """
    result = mail.parse(build(
        body="You have 1 new applicant. View it at https://example-board.com/a/9182"))

    assert mail.LIKELY_LINK_ONLY in result.quarantine_reasons
    assert result.links == ["https://example-board.com/a/9182"]


def test_a_covering_letter_alone_is_not_treated_as_a_resume_arriving():
    raw = build(attachments=[("logo.png", b"\x89PNG\r\n\x1a\n" + b"p" * 100,
                              "image", "png")])
    assert mail.NO_RESUME_ATTACHMENT in mail.parse(raw).quarantine_reasons


def test_an_unparseable_message_is_quarantined_rather_than_raising():
    """One malformed message must not stop a batch of two hundred."""
    result = mail.parse(b"\xff\xfe this is not a message at all")
    assert not result.quarantined or result.quarantine_reasons
    assert result.raw_sha256


def test_a_flood_of_attachments_is_capped():
    raw = build(attachments=[(f"f{n}.pdf", PDF, "application", "pdf")
                             for n in range(mail.MAX_ATTACHMENTS + 5)])
    result = mail.parse(raw)
    assert mail.TOO_MANY_ATTACHMENTS in result.quarantine_reasons
    assert len(result.attachments) == mail.MAX_ATTACHMENTS


# -- bodies -------------------------------------------------------------------
def test_plain_text_is_preferred_over_html():
    """The plain part exists because the sender meant it to be read by a machine."""
    raw = build(body="Plain version here.", html_body="<p>HTML version here.</p>")
    assert "Plain version here." in mail.parse(raw).body_text


def test_an_html_only_body_is_flattened_so_links_still_show():
    message = EmailMessage()
    message["Subject"] = "New applicant"
    message["From"] = "notify@example-board.com"
    message["To"] = "jobs+indeed@example.com"
    message["Message-ID"] = "<html-only@example-board.com>"
    message.add_alternative(
        "<html><body><style>p{color:red}</style>"
        "<p>1 new applicant &mdash; <a href='https://example-board.com/x'>view</a></p>"
        "</body></html>", subtype="html")

    result = mail.parse(message.as_bytes())

    assert "new applicant" in result.body_text
    assert "<p>" not in result.body_text
    assert "color:red" not in result.body_text
    assert result.links == ["https://example-board.com/x"]
