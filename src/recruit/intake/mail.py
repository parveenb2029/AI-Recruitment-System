"""Read an email the way a standard says to, not the way a job board happens to.

This is the half of intake that can be built before anyone has seen a real
notification from LinkedIn or Naukri, because none of it depends on them. MIME
is a specification: how an attachment is encoded, how a non-ASCII subject is
wrapped, what a Message-ID is for. Those answers are the same for every sender
in the world.

What is deliberately **not** here: anything that reads meaning out of a
particular platform's layout — which paragraph holds the applicant's name, which
line names the job. That is a guess until a real message is in hand, and a
parser that half-understands a format silently invents a candidate. Those live
in per-source parsers written against captured fixtures (playbook 6.1, 6.3).

The line between the two is: **structure is standard, meaning is not.**
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime

from ..errors import RecruitError
from ..ingest import MAGIC

# Gmail refuses to send more than 25 MB, so a larger message is either a
# different transport or something wrong. Attachments match the ingest limit so
# a file cannot pass intake and then be rejected downstream.
MAX_MESSAGE_MB = 25
MAX_ATTACHMENT_MB = 10
MAX_ATTACHMENTS = 20
MAX_FILENAME_LENGTH = 180

RESUME_EXTENSIONS = frozenset({".pdf", ".docx", ".doc", ".txt"})

# Windows treats these as devices, not filenames, whatever the extension. A file
# called CON.pdf is not a file — writing it can hang or fail strangely, and the
# operator runs this on Windows.
WINDOWS_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{n}" for n in range(1, 10)}
    | {f"lpt{n}" for n in range(1, 10)}
)

_UNSAFE_CHARS = re.compile(r"[\x00-\x1f\x7f<>:\"/\\|?*]")
_TAG_RE = re.compile(r"<[^>]+>")
_ANCHOR_RE = re.compile(
    r"""(?is)<a\b[^>]*?\bhref\s*=\s*["']?([^"'\s>]+)["']?[^>]*>(.*?)</a>"""
)
_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.I)
_WS_RE = re.compile(r"[ \t]+")
_BLANKS_RE = re.compile(r"\n{3,}")


class MailError(RecruitError):
    code = "ERR_MAIL_UNREADABLE"
    recovery = "The raw message is kept. Inspect it in quarantine."
    retryable = False


class MailTooLarge(MailError):
    code = "ERR_MAIL_TOO_LARGE"
    recovery = f"Messages above {MAX_MESSAGE_MB} MB are not processed automatically."


# -- quarantine reasons -------------------------------------------------------
# Stated as facts about the message, never as a diagnosis of the sender.
NO_ATTACHMENTS = "NO_ATTACHMENTS"
LIKELY_LINK_ONLY = "LIKELY_LINK_ONLY"
TOO_MANY_ATTACHMENTS = "TOO_MANY_ATTACHMENTS"
NO_RESUME_ATTACHMENT = "NO_RESUME_ATTACHMENT"
UNPARSEABLE = "UNPARSEABLE"


@dataclass(frozen=True)
class Attachment:
    """One file that arrived with a message.

    `filename` is safe to write to disk; `original_filename` is what the sender
    actually claimed and is kept as evidence — if a filename ever turns out to
    be an attack, the sanitised version is not what you want in the report.
    """

    filename: str
    original_filename: str
    content: bytes
    declared_type: str
    extension: str
    size_bytes: int
    content_sha256: str
    magic_ok: bool
    rejection: str | None = None

    @property
    def accepted(self) -> bool:
        return self.rejection is None

    @property
    def looks_like_a_resume(self) -> bool:
        return self.accepted and self.extension in RESUME_EXTENSIONS


@dataclass(frozen=True)
class IncomingMail:
    """A message, read as structure only."""

    message_id: str
    message_id_synthetic: bool
    source: str
    source_signal: str
    from_address: str
    from_name: str
    to_addresses: list[str]
    subject: str
    received_at: datetime
    body_text: str
    attachments: list[Attachment] = field(default_factory=list)
    raw_size_bytes: int = 0
    raw_sha256: str = ""
    quarantine_reasons: list[str] = field(default_factory=list)

    @property
    def quarantined(self) -> bool:
        return bool(self.quarantine_reasons)

    @property
    def resumes(self) -> list[Attachment]:
        return [a for a in self.attachments if a.looks_like_a_resume]

    @property
    def links(self) -> list[str]:
        return _URL_RE.findall(self.body_text)


# -- filenames ----------------------------------------------------------------
def sanitise_filename(name: str | None, *, fallback: str = "attachment") -> str:
    """Make a sender-supplied filename safe to write.

    A filename in an email is attacker-controlled text. `../../.ssh/authorized_keys`
    is a valid MIME filename, and so is `CON.pdf`, and so is one with a newline in
    it. Everything here defends against a specific, real trick:

    - path separators and `..` — writing outside the intended directory
    - control characters and nulls — truncating a path mid-string
    - Windows device names — `CON`, `LPT1`; not files, and this runs on Windows
    - trailing dots and spaces — Windows silently strips them, so `evil.pdf.`
      and `evil.pdf` become the same file
    - absurd length — filesystem limits, and hiding the real extension far off
      the end of a log line
    """
    if not name:
        return fallback

    # Take the last path segment under either separator before anything else.
    candidate = name.replace("\\", "/").split("/")[-1]
    candidate = _UNSAFE_CHARS.sub("_", candidate).strip()

    # Windows strips these, so two different names would collide on disk.
    candidate = candidate.rstrip(". ")

    while candidate.startswith("."):
        candidate = candidate[1:]

    if not candidate or set(candidate) <= {"_", "."}:
        return fallback

    stem, dot, extension = candidate.rpartition(".")
    if dot and stem.lower() in WINDOWS_DEVICE_NAMES:
        stem = f"{stem}_file"
    elif not dot and candidate.lower() in WINDOWS_DEVICE_NAMES:
        return f"{candidate}_file"

    rebuilt = f"{stem}.{extension}" if dot else candidate
    if len(rebuilt) > MAX_FILENAME_LENGTH:
        stem, dot, extension = rebuilt.rpartition(".")
        keep = MAX_FILENAME_LENGTH - (len(extension) + 1 if dot else 0)
        rebuilt = f"{stem[:keep]}.{extension}" if dot else rebuilt[:MAX_FILENAME_LENGTH]
    return rebuilt or fallback


def _extension_of(filename: str) -> str:
    _, dot, extension = filename.rpartition(".")
    return f".{extension.lower()}" if dot else ""


# -- headers ------------------------------------------------------------------
def _header(message: EmailMessage, name: str, default: str = "") -> str:
    """Decoded header text.

    Subjects arrive as `=?UTF-8?B?...?=` more often than people expect — any
    non-ASCII character does it. The stdlib's `default` policy already decodes
    these; this exists to flatten the result to a plain string and to survive a
    malformed header rather than raising in the middle of a batch.
    """
    try:
        value = message.get(name)
    except Exception:  # noqa: BLE001 - a broken header must not stop the batch
        return default
    if value is None:
        return default
    return _WS_RE.sub(" ", str(value)).strip() or default


def _addresses(message: EmailMessage, *names: str) -> list[str]:
    raw = []
    for name in names:
        try:
            raw.extend(message.get_all(name, []))
        except Exception:  # noqa: BLE001
            continue
    seen: list[str] = []
    for _, address in getaddresses([str(value) for value in raw]):
        address = address.strip().lower()
        if address and address not in seen:
            seen.append(address)
    return seen


# Domains that identify a job board when the delivery tag is missing. Weaker
# evidence than a tag you chose yourself — a domain says who sent the mail, not
# which posting it belongs to — but far better than giving up.
SENDER_DOMAINS: dict[str, str] = {
    "linkedin.com": "linkedin",
    "naukri.com": "naukri",
    "indeed.com": "indeed",
    "indeedemail.com": "indeed",
    "monster.com": "monster",
    "glassdoor.com": "glassdoor",
    "ziprecruiter.com": "ziprecruiter",
}

BY_TAG = "delivery_tag"
BY_DOMAIN = "sender_domain"
BY_NOTHING = "none"


def detect_source(
    addresses: list[str],
    aliases: dict[str, str] | None = None,
    sender: str | None = None,
    domains: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Which job board this came through, and how we know.

    Returns `(source, signal)` — the second half matters. "This is a LinkedIn
    application" is a different claim depending on whether it was addressed to a
    tag you published or merely sent from a linkedin.com machine, and a reviewer
    asking why a candidate was routed a certain way deserves to know which.

    Two signals, strongest first:

    1. **Delivery tag** (RFC 5233 sub-addressing) — mail to
       `jobs+linkedin@example.com` lands in `jobs@example.com` carrying the tag.
       Strongest, because you chose the address and published it yourself.
    2. **Sender domain** — mail from `@linkedin.com` is from LinkedIn. Weaker: it
       identifies the sender, not which posting the application belongs to, and
       it is a fact about the world rather than a decision you made.

    Two signals rather than one because the first is easy to lose. A forwarding
    rule, a mail client that rewrites recipients, an address-book autocomplete
    quietly replacing what was typed — any of these strips the tag, and a system
    that then reports "unknown" for every application is useless in exactly the
    situation where it matters. An unrecognised tag is still returned as itself:
    inventing a source is worse than reporting an odd one.
    """
    aliases = aliases or {}
    for address in addresses:
        local, _, _ = address.partition("@")
        _, plus, tag = local.partition("+")
        if plus and tag:
            return aliases.get(tag.lower(), tag.lower()), BY_TAG

    domains = domains or SENDER_DOMAINS
    if sender:
        _, _, host = sender.rpartition("@")
        host = host.lower().strip()
        for known, name in domains.items():
            # Suffix match so `jobs-noreply@e.indeed.com` is still Indeed.
            if host == known or host.endswith(f".{known}"):
                return name, BY_DOMAIN

    return "unknown", BY_NOTHING


def _received_at(message: EmailMessage) -> datetime:
    try:
        parsed = parsedate_to_datetime(_header(message, "Date"))
    except (TypeError, ValueError):
        parsed = None
    if parsed is None:
        return datetime.now(UTC)
    # A naive Date header is legal and useless for ordering. Treat it as UTC
    # rather than letting a comparison blow up later.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# -- body ---------------------------------------------------------------------
def _html_to_text(markup: str) -> str:
    """Enough HTML stripping to read a notification email.

    Not a renderer, and not trying to be. Job-board mail is table-heavy marketing
    HTML; what matters is that a link survives as text so the link-only case can
    be spotted, and that tags do not end up quoted as content.
    """
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", markup)
    # Pull the destination out of every link BEFORE tags are stripped. In a
    # job-board notification the URL exists only inside the href — the visible
    # text is "View application" — so stripping tags first deletes the one thing
    # that identifies a link-only message. A test caught this; it is the exact
    # case this module was written to detect.
    text = _ANCHOR_RE.sub(lambda m: f"{m.group(2)} ({m.group(1)})", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|li|h[1-6])>", "\n", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text)
    return _BLANKS_RE.sub("\n\n", text).strip()


def _body_text(message: EmailMessage) -> str:
    """Prefer the plain-text part; fall back to flattened HTML.

    Multipart/alternative exists so a reader can choose, and the plain part is
    what the sender intended a machine to read.
    """
    try:
        plain = message.get_body(preferencelist=("plain",))
        if plain is not None:
            content = plain.get_content()
            if isinstance(content, str) and content.strip():
                return content.strip()
    except Exception:  # noqa: BLE001
        pass
    try:
        rich = message.get_body(preferencelist=("html",))
        if rich is not None:
            content = rich.get_content()
            if isinstance(content, str):
                return _html_to_text(content)
    except Exception:  # noqa: BLE001
        pass
    return ""


# -- attachments --------------------------------------------------------------
def _attachments(message: EmailMessage) -> list[Attachment]:
    found: list[Attachment] = []
    for part in message.iter_attachments():
        original = part.get_filename() or ""
        try:
            content = part.get_payload(decode=True) or b""
        except Exception as exc:  # noqa: BLE001 - a broken part is not fatal
            found.append(Attachment(
                filename=sanitise_filename(original), original_filename=original,
                content=b"", declared_type=part.get_content_type(),
                extension=_extension_of(sanitise_filename(original)),
                size_bytes=0, content_sha256="", magic_ok=False,
                rejection=f"Could not be decoded: {exc}",
            ))
            continue

        safe = sanitise_filename(original, fallback=f"attachment-{len(found) + 1}")
        extension = _extension_of(safe)
        size = len(content)

        # Magic bytes over the declared content type: the Content-Type header is
        # written by the sender and an executable renamed to .pdf declares
        # whatever it likes. This reuses the same table the ingest step trusts.
        signatures = MAGIC.get(extension, [])
        magic_ok = not signatures or any(content.startswith(sig) for sig in signatures)

        rejection: str | None = None
        if size == 0:
            rejection = "Empty file."
        elif size > MAX_ATTACHMENT_MB * 1024 * 1024:
            rejection = (f"{size / 1024 / 1024:.1f} MB exceeds the "
                         f"{MAX_ATTACHMENT_MB} MB limit.")
        elif extension in RESUME_EXTENSIONS and not magic_ok:
            rejection = (f"Contents do not match the {extension} extension "
                         f"(starts with {content[:8]!r}).")

        found.append(Attachment(
            filename=safe, original_filename=original, content=content,
            declared_type=part.get_content_type(), extension=extension,
            size_bytes=size,
            content_sha256=hashlib.sha256(content).hexdigest(),
            magic_ok=magic_ok, rejection=rejection,
        ))
    return found


# -- the whole message --------------------------------------------------------
def parse(raw: bytes, *, aliases: dict[str, str] | None = None) -> IncomingMail:
    """Read a raw RFC 5322 message into structure.

    Never raises on content — a message that cannot be understood comes back
    quarantined, with the reason attached and the raw bytes preserved. The only
    exception is size, checked before parsing, because the defence has to happen
    before the work.
    """
    size = len(raw)
    if size > MAX_MESSAGE_MB * 1024 * 1024:
        raise MailTooLarge(
            f"Message is {size / 1024 / 1024:.1f} MB, limit is {MAX_MESSAGE_MB} MB."
        )

    digest = hashlib.sha256(raw).hexdigest()

    try:
        message = message_from_bytes(raw, policy=policy.default)
    except Exception:  # noqa: BLE001
        return IncomingMail(
            message_id=f"sha256:{digest}", message_id_synthetic=True,
            source="unknown", source_signal=BY_NOTHING,
            from_address="", from_name="", to_addresses=[],
            subject="", received_at=datetime.now(UTC), body_text="",
            raw_size_bytes=size, raw_sha256=digest,
            quarantine_reasons=[UNPARSEABLE],
        )

    raw_id = _header(message, "Message-ID").strip("<> ")
    synthetic = not raw_id
    # A missing Message-ID is unusual but legal. Falling back to the content
    # hash keeps "never process the same message twice" true rather than
    # dropping the message or, worse, reprocessing it on every poll.
    message_id = raw_id or f"sha256:{digest}"

    senders = getaddresses([_header(message, "From")])
    from_name, from_address = senders[0] if senders else ("", "")

    # Delivered-To and X-Original-To survive forwarding; To does not always.
    recipients = _addresses(message, "Delivered-To", "X-Original-To", "To", "Cc")

    source, signal = detect_source(recipients, aliases, sender=from_address)

    attachments = _attachments(message)
    body = _body_text(message)

    reasons: list[str] = []
    if len(attachments) > MAX_ATTACHMENTS:
        reasons.append(TOO_MANY_ATTACHMENTS)
        attachments = attachments[:MAX_ATTACHMENTS]

    if not attachments:
        reasons.append(NO_ATTACHMENTS)
        # The case the playbook warns about: the platform sent a notification
        # with a link behind a login rather than the resume itself. Worth naming
        # separately, because it is a settings problem on the job board, not a
        # broken message — and no amount of parsing will fix it.
        if _URL_RE.search(body):
            reasons.append(LIKELY_LINK_ONLY)
    elif not any(a.looks_like_a_resume for a in attachments):
        reasons.append(NO_RESUME_ATTACHMENT)

    return IncomingMail(
        message_id=message_id,
        message_id_synthetic=synthetic,
        source=source,
        source_signal=signal,
        from_address=from_address.lower(),
        from_name=from_name,
        to_addresses=recipients,
        subject=_header(message, "Subject"),
        received_at=_received_at(message),
        body_text=body,
        attachments=attachments,
        raw_size_bytes=size,
        raw_sha256=digest,
        quarantine_reasons=reasons,
    )
