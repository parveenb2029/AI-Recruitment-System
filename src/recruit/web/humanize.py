"""Turn the system's internal vocabulary into sentences a recruiter can read.

The console was written by someone who already knew what `workflow_run_id`,
`prompt_version`, `auth.login_failed` and `VR-03` meant. Almost nobody who uses
it will. A hiring manager looking at a screen of identifiers cannot tell a
routine event from a serious one, which defeats the point of showing them.

**This is a presentation layer, not a schema change.** Every technical value
stays exactly where it was and is still rendered — behind a "Show technical
details" toggle. That is deliberate: NYC Local Law 144 and GDPR Article 22 both
turn on being able to say *which model, running which prompt version, in which
run* produced a decision. Translating those away would make the console
friendlier and the evidence useless.

Three rules for everything in this module:

1. **Never invent certainty.** An unknown code is shown as itself, tidied up,
   not guessed at. A wrong plain-English label is worse than a raw code, because
   the raw code at least looks like something to ask about.
2. **Say what happened, not what fired.** "Sign-in failed — wrong email or
   password" beats "auth.login_failed".
3. **Never soften a warning.** The plain wording of a hallucination flag has to
   land harder than the code did, not softer.
"""

from __future__ import annotations

from typing import Any

# -- audit events -------------------------------------------------------------
# (short label for a column, sentence template for the description).
# `{actor}` is filled with the person's name; `{detail}` clauses are added by
# `describe_event` where the stored detail carries something worth saying.
EVENTS: dict[str, tuple[str, str]] = {
    "auth.login": ("Signed in", "{actor} signed in."),
    "auth.logout": ("Signed out", "{actor} signed out."),
    "auth.login_failed": (
        "Sign-in failed",
        # The address is shown EXACTLY as it was typed, not tidied into a name.
        # A mistyped address and a wrong password are deliberately
        # indistinguishable at the sign-in screen, so this line is the only
        # place the difference can be seen — and a typo is the likelier cause.
        # This is not hypothetical: three of these rows, all reading
        # `parveenbajaj2029@` against an account of `parveenb2029@`, are what
        # finally explained a "wrong password" that was not one.
        'Someone tried to sign in as "{raw_actor}" and it did not match an '
        "account. If that address looks slightly wrong, that is the usual "
        "cause. Repeated failures for one address are worth a look.",
    ),
    "review.approved": ("Approved", "{actor} approved this candidate's extracted details."),
    "review.rejected": ("Rejected", "{actor} rejected this extraction."),
    "review.escalated": (
        "Escalated",
        "{actor} passed this to someone with more authority instead of deciding.",
    ),
    "extraction.completed": (
        "Resume read",
        "The system read a resume and pulled out the candidate's details.",
    ),
    "extraction.failed": (
        "Resume could not be read",
        "The system could not read a document. Nobody was assessed on it.",
    ),
    "match.completed": (
        "Scored against a job",
        "The system compared a candidate against a job's requirements.",
    ),
    "retention.purged": (
        "Old records deleted",
        "Records past their retention period were deleted, as the retention "
        "policy requires.",
    ),
}

# What the reviewer is being asked to look at, from `review_reasons`.
REVIEW_REASONS: dict[str, str] = {
    "LOW_CONFIDENCE_AGGREGATE": "The system is unsure about this resume overall",
    "LOW_CONFIDENCE_FIELDS": "Some individual details are uncertain",
    "SOURCE_CONFLICTS": "The document contradicts itself",
    "OCR_USED": "The document was scanned, so the text was read from an image",
    "POTENTIAL_HALLUCINATION": "Some details could not be found in the document",
    "UNRESOLVED_REQUIREMENTS": "Some job requirements could not be judged either way",
    "BELOW_AUTO_ARCHIVE_THRESHOLD": "Scored low against this job",
}

# Rejection reasons, as the reviewer picks them.
REJECT_REASONS: dict[str, str] = {
    "FABRICATED_CONTENT": "Details that are not in the document",
    "WRONG_EXTRACTION": "Details read incorrectly",
    "WRONG_DOCUMENT": "Not this candidate's document",
    "UNREADABLE_SOURCE": "Document unusable",
    "DUPLICATE": "Already have this candidate",
    "OTHER": "Other",
}

# Validation rules. The identifiers are referenced by name across the specs and
# the compliance pack, so they stay visible in the technical view — but a
# reviewer needs to know what went wrong, not which rule number caught it.
RULES: dict[str, str] = {
    "VR-01": "Needs a human to check it, but was not marked for review",
    "VR-02": "The result did not have the expected shape",
    "VR-03": "A quoted detail could not be found in the document",
    "VR-04": "Dates or numbers do not add up",
    "BV-LOWCONF": "The system is not confident enough in this",
    "BV-CONFLICT": "Two parts of the document disagree",
    "BV-STATUS": "The run's status does not match what was found",
    "BR-05": "Missing the record of which model and prompt produced this",
}

SEVERITY: dict[str, str] = {
    "CRITICAL": "Must be fixed",
    "ERROR": "Problem",
    "WARNING": "Worth checking",
    "INFO": "Note",
}

STATES: dict[str, str] = {
    "PENDING": "Waiting for review",
    "APPROVED": "Approved",
    "REJECTED": "Rejected",
    "ESCALATED": "Passed upwards",
    "SUCCESS": "Read cleanly",
    "PARTIAL": "Read, with things to check",
    "FAILED": "Could not be read",
}

ROLES: dict[str, str] = {
    "admin": "Administrator",
    "hiring_manager": "Hiring manager",
    "recruiter": "Recruiter",
    "auditor": "Auditor",
    "service": "The system",
}

# Labels for the keys that turn up inside a stored `detail` blob.
# Some detail keys mean different things depending on the event, and some are
# already covered by the sentence above the list. Repeating them there is noise,
# and noise is what made the old screen unreadable.
HIDE_BY_EVENT: dict[str, set[str]] = {
    # The sentence already names the address and says what went wrong.
    "auth.login_failed": {"reason", "email"},
    # "Seeded: Yes" tells a reviewer nothing they can act on.
    "extraction.completed": {"seeded"},
}

LABELS_BY_EVENT: dict[str, dict[str, str]] = {
    "extraction.completed": {"email": "Candidate's email (partly hidden)"},
}

# Values that are themselves codes.
VALUE_MAPS: dict[str, dict[str, str]] = {
    "reason": {
        "invalid_credentials": "The email and password did not match",
    },
}

DETAIL_LABELS: dict[str, str] = {
    "reason_code": "Reason",
    "note": "Note",
    "edited_fields": "Fields corrected",
    "email": "Email tried",
    "filename": "File",
    "document_id": "Document",
    "candidate_id": "Candidate",
    "requisition_id": "Job",
    "confidence": "Confidence",
    "outcome": "Outcome",
    "count": "How many",
}


def _tidy(code: str) -> str:
    """Last resort for an unrecognised code: readable, but visibly a code.

    `SOME_NEW_THING` -> `Some new thing`. Deliberately not a guess at meaning.
    """
    return code.replace("_", " ").replace(".", " — ").strip().capitalize()


def role_name(role: str | None) -> str:
    if not role:
        return "—"
    return ROLES.get(role, _tidy(role))


def state_name(state: str | None) -> str:
    if not state:
        return "—"
    return STATES.get(state, _tidy(state))


def review_reason(code: str) -> str:
    return REVIEW_REASONS.get(code, _tidy(code))


def reject_reason(code: str | None) -> str:
    if not code:
        return "—"
    return REJECT_REASONS.get(code, _tidy(code))


def rule_name(rule: str | None) -> str:
    if not rule:
        return ""
    return RULES.get(rule, _tidy(rule))


def severity_name(severity: str | None) -> str:
    if not severity:
        return ""
    return SEVERITY.get(severity, _tidy(severity))


def event_title(event: str | None) -> str:
    if not event:
        return "—"
    known = EVENTS.get(event)
    return known[0] if known else _tidy(event)


def actor_name(actor: str | None) -> str:
    """A person, not a login.

    `parveenb2029@gmail.com` reads as an identifier; `Parveenb2029` reads as a
    person. The full address stays in the technical view, where an auditor
    needs it to be exact.
    """
    if not actor:
        return "Someone"
    if actor == "seed":
        return "The set-up script"
    if actor == "(blank)":
        return "someone who left the email blank"
    local = actor.split("@")[0]
    return local.replace(".", " ").replace("_", " ").title() if "@" in actor else actor


def confidence_phrase(value: float | None) -> str:
    """Words, not a decimal.

    A recruiter cannot act on "0.57". They can act on "not sure — check it".
    The number itself stays on screen beside this, because a number is what you
    compare across candidates.
    """
    if value is None:
        return "Not measured"
    if value >= 0.85:
        return "Confident"
    if value >= 0.60:
        return "Fairly sure"
    if value >= 0.40:
        return "Not sure — check it"
    return "Very unsure — check every line"


def detail_pairs(detail: Any, event: str | None = None) -> list[tuple[str, str]]:
    """Render a stored detail blob as labelled fields rather than a dict.

    `{'reason_code': 'DUPLICATE', 'note': None, 'edited_fields': []}` printed
    raw is three pieces of noise. Empty values are dropped rather than shown as
    `None` — an absent note is not information.
    """
    if not detail:
        return []
    if not isinstance(detail, dict):
        return [("Detail", str(detail))]

    hidden = HIDE_BY_EVENT.get(event or "", set())
    overrides = LABELS_BY_EVENT.get(event or "", {})

    pairs: list[tuple[str, str]] = []
    for key, value in detail.items():
        if key in hidden or value in (None, "", [], {}):
            continue
        label = overrides.get(key) or DETAIL_LABELS.get(key, _tidy(key))
        if key == "reason_code":
            rendered = reject_reason(str(value))
        elif key in VALUE_MAPS and str(value) in VALUE_MAPS[key]:
            rendered = VALUE_MAPS[key][str(value)]
        elif isinstance(value, list):
            rendered = ", ".join(str(v) for v in value)
        elif isinstance(value, bool):
            rendered = "Yes" if value else "No"
        elif isinstance(value, float):
            rendered = f"{value:.2f}"
        else:
            rendered = str(value)
        pairs.append((label, rendered))
    return pairs


def describe_event(entry: Any) -> str:
    """One sentence saying what happened, for an audit row.

    Takes the row rather than the event name so the sentence can name the person
    and fold in the part of the detail that matters — a rejection is only
    meaningful with its reason attached.
    """
    event = getattr(entry, "event", None) or ""
    actor = actor_name(getattr(entry, "actor", None))

    raw_actor = getattr(entry, "actor", None) or "(no address given)"

    known = EVENTS.get(event)
    sentence = (known[1].format(actor=actor, raw_actor=raw_actor) if known
                else f"{actor}: {_tidy(event)}.")

    detail = getattr(entry, "detail", None)
    if isinstance(detail, dict):
        code = detail.get("reason_code")
        if code and event == "review.rejected":
            sentence += f" Reason given: {reject_reason(str(code)).lower()}."
        note = detail.get("note")
        if note:
            sentence += f' Their note: "{note}"'
        edited = detail.get("edited_fields")
        if edited:
            sentence += f" They corrected: {', '.join(str(f) for f in edited)}."
    return sentence


def is_concerning(event: str | None) -> bool:
    """Should this audit row be visually flagged?

    Only for events a non-technical reader should slow down at. A failed
    sign-in is the one that matters here: it is how a shared or guessed password
    shows up, and it is exactly what got lost in a wall of identifiers before.
    """
    return event in {"auth.login_failed", "extraction.failed"}


# Field names whose mechanical capitalisation reads badly or misleads.
FIELD_LABELS: dict[str, str] = {
    "candidate_id": "Candidate reference",
    "requisition_id": "Job reference",
    "linkedin_url": "LinkedIn",
    "github_url": "GitHub",
    "is_current": "Currently working there",
    "full_name": "Name",
    "skills_used": "Skills used here",
    "cgpa": "Grade (CGPA)",
    "start_date": "Started",
    "end_date": "Ended",
    "employment_type": "Type of employment",
}


def field_label(key: str) -> str:
    """`personal_info.full_name` -> `Name`.

    Mechanical title-casing produces "Linkedin Url" and "Candidate Id", which
    read as a database schema rather than a resume. Anything not listed falls
    back to the mechanical version — visibly plain, never wrong.
    """
    leaf = key.replace(" ", "_").split(".")[-1].split("/")[-1].strip().lower()
    if leaf in FIELD_LABELS:
        return FIELD_LABELS[leaf]
    return leaf.replace("_", " ").capitalize()


def field_value(value: Any) -> str:
    """`True` is a Python literal, not an answer to a question on a form."""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if value is None:
        return "—"
    return str(value)
