"""The console has to be readable by someone who has never seen a JSON key.

The operator's words, on seeing the audit screen: the people using this "wud be
layman 99 eprcent time". That is the requirement these tests encode.

Two halves, and the second matters as much as the first:

1. Nothing a reviewer reads by default is an identifier, an event constant, or
   a rule number.
2. Every one of those identifiers is **still in the page**, behind the
   technical-details toggle. NYC Local Law 144 and GDPR Article 22 both turn on
   being able to name the run, the prompt version and the model behind a
   decision. A console that translated those away would read beautifully and be
   worthless in an audit.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from recruit import extract as extract_mod
from recruit.adapters.llm import FakeLLM
from recruit.auth import Principal
from recruit.db.migrations import create_all, drop_all
from recruit.db.repository import Repository
from recruit.db.session import create_engine_from_config, make_session_factory, session_scope
from recruit.web import humanize
from recruit.web.app import create_app

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "wf03_fake_results.json"
RESUME = ROOT / "samples" / "Rahul_Sharma_Resume.pdf"


# -- reading the page the way a person does -----------------------------------
class _VisibleText(HTMLParser):
    """The text a reviewer actually sees.

    Skips `<script>`, `<style>`, and any element whose class starts with
    `tech` — those are the blocks the toggle reveals. What is left is the
    default reading experience.
    """

    SKIP_TAGS = {"script", "style"}
    VOID = {"br", "hr", "img", "input", "meta", "link", "source"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.VOID:
            return
        classes = (dict(attrs).get("class") or "").split()
        hidden = tag in self.SKIP_TAGS or any(c.startswith("tech") for c in classes)
        if self._skip_depth or hidden:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self.VOID:
            return
        if self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)

    @property
    def text(self) -> str:
        return " ".join(" ".join(self.parts).split())


def visible(html: str) -> str:
    parser = _VisibleText()
    parser.feed(html)
    return parser.text


# Vocabulary that must never reach a reviewer without them asking for it.
JARGON = [
    "workflow_run_id", "prompt_version", "model_id", "content_sha256",
    "confidence_aggregate", "auth.login", "auth.login_failed", "auth.logout",
    "review.approved", "review.rejected", "review.escalated",
    "extraction.completed", "LOW_CONFIDENCE_AGGREGATE", "LOW_CONFIDENCE_FIELDS",
    "POTENTIAL_HALLUCINATION", "OCR_USED", "SOURCE_CONFLICTS",
    "FABRICATED_CONTENT", "WRONG_EXTRACTION", "UNREADABLE_SOURCE",
    "VR-01", "VR-03", "BV-LOWCONF", "BR-05",
]


# -- fixtures -----------------------------------------------------------------
@pytest.fixture
def factory(tmp_path):
    engine = create_engine_from_config(url=f"sqlite:///{tmp_path / 'humanize.db'}")
    drop_all(engine)
    create_all(engine)
    return make_session_factory(engine)


@pytest.fixture
def admin():
    return Principal(email="boss@example.com", display_name="Priya Nair",
                     role="admin", user_id=1)


@pytest.fixture
def client(factory, admin):
    return TestClient(create_app(session_factory=factory, current_user=admin))


@pytest.fixture
def task_id(factory):
    envelope = extract_mod.extract(RESUME, llm=FakeLLM(FIXTURE), root=ROOT)
    with session_scope(factory) as session:
        repo = Repository(session)
        run, _ = repo.save_run(envelope, document_id=None)
        task = repo.create_review_task(run, reasons=["LOW_CONFIDENCE_AGGREGATE"])
        repo.append_audit(event="extraction.completed", actor="seed",
                          actor_role="service", workflow_run_id=run.id,
                          workflow_id=run.workflow_id,
                          prompt_version=run.prompt_version, model_id=run.model_id)
        repo.append_audit(event="auth.login_failed", actor="typo@example.com",
                          detail={"email": "typo@example.com"})
        return task.id


# -- the plain-language layer itself ------------------------------------------
@dataclass
class FakeEntry:
    event: str
    actor: str = "priya.nair@example.com"
    actor_role: str | None = "recruiter"
    detail: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def test_every_known_event_reads_as_a_sentence():
    for event in humanize.EVENTS:
        sentence = humanize.describe_event(FakeEntry(event))
        assert event not in sentence, f"{event} leaked into its own description"
        assert sentence.endswith((".", '"')), f"{event} description is not a sentence"
        assert sentence[0].isupper(), f"{event} description does not start a sentence"


def test_an_unknown_code_is_tidied_not_guessed_at():
    """A wrong plain-English label is worse than a visible code.

    Someone reading "Some future event" can ask what it means. Someone reading
    a confident mistranslation cannot tell there is anything to ask about.
    """
    assert humanize.event_title("some.future_event") == "Some — future event"
    assert humanize.review_reason("BRAND_NEW_REASON") == "Brand new reason"


def test_a_rejection_carries_its_reason_and_note():
    sentence = humanize.describe_event(FakeEntry(
        "review.rejected",
        detail={"reason_code": "DUPLICATE", "note": "Applied in March too."},
    ))
    assert "rejected" in sentence
    assert "already have this candidate" in sentence.lower()
    assert "Applied in March too." in sentence
    assert "DUPLICATE" not in sentence


def test_detail_pairs_drop_empties_rather_than_printing_none():
    pairs = humanize.detail_pairs(
        {"reason_code": "OTHER", "note": None, "edited_fields": []}
    )
    assert pairs == [("Reason", "Other")]
    assert humanize.detail_pairs({}) == []
    assert humanize.detail_pairs(None) == []


def test_confidence_becomes_words_a_person_can_act_on():
    assert humanize.confidence_phrase(0.95) == "Confident"
    assert "check" in humanize.confidence_phrase(0.42).lower()
    assert "check" in humanize.confidence_phrase(0.10).lower()
    assert humanize.confidence_phrase(None) == "Not measured"


def test_a_failed_sign_in_is_flagged_and_a_successful_one_is_not():
    """The operator's own mistyped address produced three of these in a row.

    Buried in a wall of identifiers, that was invisible. It is the one event on
    this screen that a non-technical reader should slow down at.
    """
    assert humanize.is_concerning("auth.login_failed")
    assert not humanize.is_concerning("auth.login")


def test_an_email_login_is_shown_as_a_person():
    assert humanize.actor_name("priya.nair@example.com") == "Priya Nair"
    assert humanize.actor_name("seed") == "The set-up script"
    assert humanize.actor_name(None) == "Someone"


# -- the rendered screens -----------------------------------------------------
@pytest.mark.parametrize("path", ["/", "/audit"])
def test_no_jargon_reaches_a_reviewer(client, task_id, path):
    seen = visible(client.get(path).text)
    leaked = [word for word in JARGON if word in seen]
    assert not leaked, f"{path} shows {leaked} to someone who did not ask for it"


def test_the_review_screen_is_free_of_jargon_too(client, task_id):
    seen = visible(client.get(f"/review/{task_id}").text)
    leaked = [word for word in JARGON if word in seen]
    assert not leaked, f"the review screen shows {leaked}"


def test_the_audit_trail_still_names_the_model_and_the_run(client, task_id):
    """The half that is easy to lose while making things friendly.

    If this fails, the console reads well and cannot answer "which model
    decided this?" — which is the question LL144 and GDPR Art. 22 exist to make
    answerable.
    """
    body = client.get("/audit").text
    assert "workflow_run_id" in body
    assert "prompt_version" in body
    assert "model_id" in body
    # And on the screen where a decision is actually made.
    detail = client.get(f"/review/{task_id}").text
    assert "workflow_run_id" in detail
    assert "model_id" in detail


def test_a_failed_sign_in_names_the_address_exactly_as_typed(client, task_id):
    """The one fact that resolves a "wrong password" that is not one.

    A mistyped address and a wrong password are deliberately indistinguishable
    at the sign-in screen — that is a security property worth keeping. This row
    is therefore the only place the difference can be recovered, so the address
    must appear character for character, not tidied into a display name.
    """
    seen = html.unescape(visible(client.get("/audit").text))
    assert "Sign-in failed" in seen
    assert "typo@example.com" in seen
    assert "did not match an account" in seen
    # Not "Typo" — a prettified name would hide the very typo being diagnosed.
    assert "as \"Typo\"" not in seen


def test_the_review_reason_is_a_sentence_on_the_queue(client, task_id):
    seen = visible(client.get("/").text)
    assert "The system is unsure about this resume overall" in seen
    assert "Rahul Sharma" in seen


def test_every_screen_offers_the_technical_view(client, task_id):
    """Hidden, not removed — and reachable without editing anything."""
    for path in ["/", "/audit", f"/review/{task_id}"]:
        assert 'id="tech"' in client.get(path).text, f"{path} has no toggle"


def test_the_reject_reasons_have_one_wording(client, task_id):
    """The dropdown, the audit sentence and the summary must agree.

    Three hand-maintained copies of "duplicate candidate" is how a screen ends
    up saying three different things about one decision.
    """
    from recruit.web.app import REJECT_REASONS

    assert dict(REJECT_REASONS) == humanize.REJECT_REASONS
    # Unescaped, because Jinja turns the apostrophe in "candidate's" into &#39;
    # — a rendering detail, not a wording difference.
    body = html.unescape(client.get(f"/review/{task_id}").text)
    for label in humanize.REJECT_REASONS.values():
        assert label in body
