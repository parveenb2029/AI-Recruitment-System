"""The one page a stranger reaches without an account.

Most of this console is written for somebody who already knows what a review
queue is. `/demo` assumes nothing, and exists to produce one moment of
comprehension: click a detail, watch the line of the CV it came from light up.

**What makes these tests unusual is that the page makes claims**, in prose, to
people who cannot check them. It says the system caught a misread email. If
that ever stops being true, the page becomes a lie told to strangers — a worse
failure than a broken route, because a broken route is visible. So most of what
follows checks the claims rather than the rendering.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from recruit.db.auth_repository import LocalAuth
from recruit.db.migrations import create_all
from recruit.db.session import make_session_factory
from recruit.web.app import DEMO_DIR, _demo_fields, create_app

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'demo.db'}")
    create_all(engine)
    factory = make_session_factory(engine)
    app = create_app(session_factory=factory, auth_adapter=LocalAuth(factory))
    return TestClient(app, follow_redirects=False, headers={"accept": "text/html"})


# -- reachable by a stranger --------------------------------------------------
def test_the_demo_needs_no_account(client):
    """The entire point. A login screen is where a curious visitor leaves."""
    response = client.get("/demo")

    assert response.status_code == 200
    assert "A computer read this CV" in response.text


def test_both_recordings_render(client):
    for case in ("clean", "misread"):
        response = client.get(f"/demo?case={case}")
        assert response.status_code == 200, case


def test_an_unknown_case_falls_back_rather_than_erroring(client):
    """A mistyped or stale link must still land on something useful."""
    response = client.get("/demo?case=../../etc/passwd")

    assert response.status_code == 200
    assert "It read the CV" in response.text


def test_the_demo_reads_nothing_from_the_database(client, tmp_path):
    """It must work on an instance whose database is empty.

    A freshly deployed copy has no candidates in it. If the demo needed a
    seeded queue, the first visitor to a new deployment would get an empty
    page — which is the one moment it has to work.
    """
    response = client.get("/demo")
    assert response.status_code == 200
    assert "Rahul Sharma" in response.text


# -- the claims the page makes to strangers -----------------------------------
def test_the_misread_recording_still_shows_the_system_catching_it():
    """The page's central claim, checked against the baked file.

    If validation ever stops producing this finding and the recording is
    rebaked, the page would show a wrong answer wearing a green tick — the
    exact failure it exists to dramatise.
    """
    envelope = json.loads((DEMO_DIR / "misread.json").read_text(encoding="utf-8"))

    rules = [f["rule"] for f in envelope["validation"]["findings"]]
    assert "VR-05" in rules, f"expected VR-05, got {rules}"
    assert envelope["status"] == "PARTIAL"
    assert envelope["human_review_required"] is True


def test_the_misread_recording_actually_contains_the_misread_address():
    """The prose says a character is missing. It must actually be missing."""
    envelope = json.loads((DEMO_DIR / "misread.json").read_text(encoding="utf-8"))
    personal = envelope["results"]["profile"]["personal_info"]

    assert personal["email"] == "rahl.sharma@email.com"
    # And the citation must still quote the CORRECT address — that gap between
    # an honest quote and a wrong value is the whole lesson.
    quoted = " ".join(e.get("snippet", "") for e in envelope["evidence"])
    assert "rahul.sharma@email.com" in quoted


def test_the_clean_recording_got_the_address_right():
    envelope = json.loads((DEMO_DIR / "clean.json").read_text(encoding="utf-8"))
    personal = envelope["results"]["profile"]["personal_info"]

    assert personal["email"] == "rahul.sharma@email.com"
    assert not envelope["validation"]["findings"]


def test_the_page_says_it_is_a_recording(client):
    """A demo implying live inference when there is none is a lie.

    It is a small one, and it is the kind this project spends its README
    refusing to tell.
    """
    response = client.get("/demo")
    assert "recordings, not live runs" in response.text


def test_the_page_says_a_person_decides(client):
    """The human-in-the-loop promise has to survive contact with marketing."""
    import re

    for case in ("clean", "misread"):
        # Collapsed, because the phrases are wrapped in the template and a test
        # that breaks on reflowing a paragraph teaches people to delete tests.
        text = re.sub(r"\s+", " ", client.get(f"/demo?case={case}").text)
        assert "A person does, every time" in text
        assert "never rejects anybody on its own" in text


# -- what a visitor is shown ---------------------------------------------------
def test_the_name_leads_rather_than_whatever_sorted_first():
    """Stored alphabetically, `email` came above `full_name`.

    A CV summary that opens on an email address reads as machine output. The
    order is a presentation decision, made in the route rather than by
    reordering the evidence.
    """
    rows = _demo_fields([
        {"pointer": "/skills", "label": "Skills", "value": "x",
         "confidence": None, "evidence_index": None},
        {"pointer": "/personal_info/email", "label": "Email", "value": "x",
         "confidence": None, "evidence_index": None},
        {"pointer": "/personal_info/full_name", "label": "Name", "value": "x",
         "confidence": None, "evidence_index": None},
        {"pointer": "/experience/0/company", "label": "Company", "value": "x",
         "confidence": None, "evidence_index": None},
    ])

    assert [r["pointer"] for r in rows] == [
        "/personal_info/full_name", "/personal_info/email",
        "/experience/0/company", "/skills",
    ]


def test_values_this_system_supplied_are_not_shown_as_things_it_read():
    """`candidate_id` appears in no resume ever written.

    The page says "here is what it pulled out of the CV". Showing a reference
    this system generated, beside details genuinely quoted from the document,
    invites a visitor to believe the document contained it. The review console
    is right to show it — a reviewer needs the identifier — but the review
    console is not making this page's claim.
    """
    rows = _demo_fields([
        {"pointer": "/candidate_id", "label": "Candidate reference",
         "value": "CAN-88421", "confidence": None, "evidence_index": None},
        {"pointer": "/extraction_metadata/pages", "label": "Pages",
         "value": "1", "confidence": None, "evidence_index": None},
        {"pointer": "/personal_info/full_name", "label": "Name",
         "value": "Rahul Sharma", "confidence": None, "evidence_index": None},
    ])

    assert [r["pointer"] for r in rows] == ["/personal_info/full_name"]


def test_the_evidence_link_survives_the_reordering(client):
    """Reordering rows must not break the click-to-highlight pairing.

    The pairing is by evidence index, not by position, so this is a check that
    the sort did not drop the attribute rather than that it could not.
    """
    text = client.get("/demo?case=misread").text

    assert 'class="f ' in text
    assert "data-index=" in text
    assert 'id="ev-' in text


def test_the_email_row_is_the_one_highlighted_on_the_misread_page(client):
    """The prose says "look at the email". It has to be what is lit up.

    A screenshot caught the opposite: the opening highlight scrolled the list
    past the candidate's name and email and settled on an employer, on the page
    whose entire text is about the email address.
    """
    text = client.get("/demo?case=misread").text
    email_row = [line for line in text.splitlines() if "opening" in line]

    assert email_row, "no opening row marked"
    assert "wrong opening" in text


def test_a_missing_recording_explains_how_to_make_one(client, monkeypatch):
    """A 404 with no reason looks like a broken deployment."""
    monkeypatch.setattr("recruit.web.app.DEMO_DIR", ROOT / "does-not-exist")
    response = client.get("/demo")

    assert response.status_code == 404
    assert "bake_demo" in response.text


# -- it must ship ---------------------------------------------------------------
def test_the_recordings_are_not_excluded_from_the_docker_image():
    """The demo is the first thing a deployed copy shows a stranger.

    Excluding the numbered workflow folders once produced an image whose
    console worked and whose extraction raised. This is the same shape: an
    image that builds, starts, serves every other page, and 404s on the one
    page anyone was linked to.
    """
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    for line in ignore.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            assert not stripped.startswith("samples"), (
                f".dockerignore excludes {stripped!r}; the demo reads samples/demo/"
            )
