"""Review console tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from recruit import extract as extract_mod
from recruit import ingest
from recruit.adapters.llm import FakeLLM
from recruit.db.migrations import create_all, drop_all
from recruit.db.models import AuditLog, ReviewTask
from recruit.db.repository import Repository
from recruit.db.session import create_engine_from_config, make_session_factory, session_scope
from recruit.validate import validate as run_validation
from recruit.web.app import _flatten_profile, _segment_source, create_app

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "wf03_fake_results.json"
RESUME = ROOT / "samples" / "Rahul_Sharma_Resume.pdf"

pytestmark = pytest.mark.skipif(
    not RESUME.is_file() or not FIXTURE.is_file(), reason="fixtures not present"
)


@pytest.fixture
def factory(tmp_path):
    engine = create_engine_from_config(url=f"sqlite:///{tmp_path / 'web.db'}")
    drop_all(engine)
    create_all(engine)
    yield make_session_factory(engine)
    drop_all(engine)


@pytest.fixture
def seeded(factory):
    envelope = extract_mod.extract(RESUME, llm=FakeLLM(FIXTURE), root=ROOT)
    document = ingest.load(RESUME)
    report = run_validation(envelope, source_text=document.text, schema_dir=ROOT / "schemas")
    with session_scope(factory) as session:
        repo = Repository(session)
        repo.ensure_requisition("REQ-2026-0142", title="Software Engineer II")
        repo.ensure_candidate("CAN-88421", requisition_id="REQ-2026-0142")
        stored, _ = repo.upsert_document(
            content_sha256=document.content_sha256, storage_uri="file:///x.pdf",
            filename="Rahul_Sharma_Resume.pdf", extension=".pdf",
            size_bytes=document.size_bytes, pages=document.pages)
        run, _ = repo.save_run(envelope, document_id=stored.id,
                               validation=report.summary())
        task = repo.create_review_task(run)
        return {"task_id": task.id, "run_id": run.id}


@pytest.fixture
def client(factory):
    return TestClient(create_app(session_factory=factory))


# -- queue --------------------------------------------------------------------
def test_empty_queue_says_so_rather_than_showing_a_blank_table(client):
    body = client.get("/").text
    assert "Queue is empty" in body


def test_queue_lists_the_candidate(client, seeded):
    body = client.get("/").text
    assert "Rahul Sharma" in body
    assert "0.57" in body
    assert "low confidence" in body.lower()


def test_queue_orders_riskiest_first(client, factory, seeded):
    envelope = extract_mod.extract(RESUME, llm=FakeLLM(FIXTURE), root=ROOT)
    with session_scope(factory) as session:
        repo = Repository(session)
        for run_id, confidence in [("RUN-hi", 0.95), ("RUN-lo", 0.11)]:
            run, _ = repo.save_run(
                dict(envelope, workflow_run_id=run_id, confidence_aggregate=confidence),
                document_id=None)
            repo.create_review_task(run)
    body = client.get("/").text
    assert body.index("0.11") < body.index("0.57") < body.index("0.95")


# -- detail -------------------------------------------------------------------
def test_detail_renders_fields_and_source(client, seeded):
    body = client.get(f"/review/{seeded['task_id']}").text
    assert "Rahul Sharma" in body
    assert "rahul.sharma@email.com" in body
    assert "Infosys Limited" in body


def test_evidence_is_highlighted_in_the_source(client, seeded):
    """The trust mechanism: a reviewer must see WHERE a field came from."""
    body = client.get(f"/review/{seeded['task_id']}").text
    assert '<mark id="ev-0"' in body
    assert "Senior Software Engineer</mark>" in body


def test_low_confidence_field_is_visually_flagged(client, seeded):
    body = client.get(f"/review/{seeded['task_id']}").text
    assert 'class="f  low"' in body or "low" in body


def test_unknown_task_is_404(client):
    assert client.get("/review/9999").status_code == 404


# -- resolving ----------------------------------------------------------------
def test_approve_records_the_decision_and_the_actor(client, factory, seeded):
    response = client.post(f"/review/{seeded['task_id']}/resolve",
                           data={"decision": "approve"}, follow_redirects=False)
    assert response.status_code == 303
    with session_scope(factory) as session:
        task = session.get(ReviewTask, seeded["task_id"])
        assert task.state == "APPROVED"
        assert task.reviewer
        assert task.resolved_at is not None
        entries = session.query(AuditLog).filter(
            AuditLog.workflow_run_id == seeded["run_id"]).all()
        assert any(e.event == "review.approved" for e in entries)
        approved = next(e for e in entries if e.event == "review.approved")
        assert approved.prompt_version and approved.model_id


def test_rejection_requires_a_reason_code(client, seeded):
    """Free-text-only rejections cannot be aggregated, so the code is mandatory."""
    response = client.post(f"/review/{seeded['task_id']}/resolve",
                           data={"decision": "reject"}, follow_redirects=False)
    assert response.status_code == 400


def test_rejection_with_a_reason_is_recorded(client, factory, seeded):
    client.post(f"/review/{seeded['task_id']}/resolve",
                data={"decision": "reject", "reason_code": "FABRICATED_CONTENT",
                      "note": "DeepMind role is not in the PDF"},
                follow_redirects=False)
    with session_scope(factory) as session:
        task = session.get(ReviewTask, seeded["task_id"])
        assert task.state == "REJECTED"
        assert task.reason_code == "FABRICATED_CONTENT"


def test_a_task_cannot_be_resolved_twice(client, seeded):
    client.post(f"/review/{seeded['task_id']}/resolve", data={"decision": "approve"},
                follow_redirects=False)
    second = client.post(f"/review/{seeded['task_id']}/resolve",
                         data={"decision": "approve"}, follow_redirects=False)
    assert second.status_code == 409


def test_unknown_decision_is_rejected(client, seeded):
    response = client.post(f"/review/{seeded['task_id']}/resolve",
                           data={"decision": "shipit"}, follow_redirects=False)
    assert response.status_code == 400


def test_malformed_edits_do_not_500(client, seeded):
    response = client.post(f"/review/{seeded['task_id']}/resolve",
                           data={"decision": "approve", "edits": "{not json"},
                           follow_redirects=False)
    assert response.status_code == 400


# -- helpers ------------------------------------------------------------------
def test_segments_use_offsets_not_text_search():
    """A phrase that appears twice must highlight the cited occurrence only."""
    source = "Python here. And Python there."
    evidence = [{"snippet": "Python", "char_start": 17, "char_end": 23, "field": "skill"}]
    segments = _segment_source(source, evidence)
    highlighted = [s for s in segments if s["index"] is not None]
    assert len(highlighted) == 1
    assert segments[0]["text"] == "Python here. And "


def test_segments_survive_overlapping_citations():
    source = "abcdefghij"
    evidence = [
        {"snippet": "bcd", "char_start": 1, "char_end": 4},
        {"snippet": "cde", "char_start": 2, "char_end": 5},   # overlaps
    ]
    rebuilt = "".join(s["text"] for s in _segment_source(source, evidence))
    assert rebuilt == source


def test_flatten_profile_keys_rows_by_json_pointer():
    profile = {"personal_info": {"full_name": "A B"}, "skills": ["x", "y"]}
    rows = _flatten_profile(profile, {"/personal_info/full_name": 0.9}, [])
    by_pointer = {r["pointer"]: r for r in rows}
    assert by_pointer["/personal_info/full_name"]["confidence"] == 0.9
    assert by_pointer["/skills"]["value"] == "x, y"


def test_health():
    from recruit.web.app import create_app as build
    client = TestClient(build(session_factory=lambda: None))
    assert client.get("/health").json() == {"status": "ok"}
