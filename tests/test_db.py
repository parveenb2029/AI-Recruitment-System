"""Persistence tests.

Run on SQLite by default so they need no server. Set DATABASE_URL to a Postgres
URL to run the same suite against Postgres — the append-only trigger and the
constraints exist in both, so both are genuinely covered.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from recruit import extract as extract_mod
from recruit import ingest
from recruit.adapters.llm import FakeLLM
from recruit.config import OrganizationConfig
from recruit.db.migrations import create_all, drop_all
from recruit.db.repository import Repository, mask_pii
from recruit.db.session import create_engine_from_config, make_session_factory, session_scope

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "wf03_fake_results.json"
RESUME = ROOT / "samples" / "Rahul_Sharma_Resume.pdf"


@pytest.fixture
def engine(tmp_path):
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.db'}"
    eng = create_engine_from_config(url=url)
    drop_all(eng)
    create_all(eng)
    yield eng
    drop_all(eng)


@pytest.fixture
def factory(engine):
    return make_session_factory(engine)


@pytest.fixture
def envelope():
    if not (RESUME.is_file() and FIXTURE.is_file()):
        pytest.skip("fixtures not present")
    return extract_mod.extract(RESUME, llm=FakeLLM(FIXTURE), root=ROOT)


def seed(repo: Repository) -> None:
    repo.ensure_requisition("REQ-2026-0142", title="Software Engineer II", jurisdiction="EU")
    repo.ensure_candidate("CAN-88421", requisition_id="REQ-2026-0142",
                          full_name="Rahul Sharma", email="rahul.sharma@email.com",
                          jurisdiction="EU", consent_on_file=False)


# -- the audit guarantee ------------------------------------------------------
def test_audit_log_rejects_update(engine, factory):
    with session_scope(factory) as session:
        Repository(session).append_audit(event="test", actor="a@b.com")
    with pytest.raises(DBAPIError, match="append-only"), engine.begin() as connection:
        connection.execute(text("UPDATE audit_log SET actor='attacker' WHERE id=1"))


def test_audit_log_rejects_delete(engine, factory):
    with session_scope(factory) as session:
        Repository(session).append_audit(event="test", actor="a@b.com")
    with pytest.raises(DBAPIError, match="append-only"), engine.begin() as connection:
        connection.execute(text("DELETE FROM audit_log WHERE id=1"))


def test_repository_exposes_no_way_to_mutate_audit():
    """The guardrail, not just the backstop."""
    names = [n for n in dir(Repository) if not n.startswith("_")]
    for name in names:
        lowered = name.lower()
        if "audit" in lowered:
            forbidden = ("update", "delete", "remove", "purge")
            assert not any(verb in lowered for verb in forbidden), name


def test_audit_masks_pii(factory):
    with session_scope(factory) as session:
        repo = Repository(session)
        entry = repo.append_audit(event="x", actor="s", workflow_run_id="RUN-1",
                                  detail={"email": "rahul.sharma@email.com", "roles": 2})
        assert entry.detail["email"] != "rahul.sharma@email.com"
        assert entry.detail["email"].startswith("r***")
        assert entry.detail["roles"] == 2       # non-PII survives intact


def test_mask_pii_recurses():
    masked = mask_pii({"a": [{"phone": "+91-98765-43210", "keep": 1}]})
    assert masked["a"][0]["phone"].startswith("+***")
    assert masked["a"][0]["keep"] == 1


# -- idempotency --------------------------------------------------------------
def test_same_bytes_are_not_stored_twice(factory, envelope):
    document = ingest.load(RESUME)
    with session_scope(factory) as session:
        repo = Repository(session)
        seed(repo)
        first, created_a = repo.upsert_document(
            content_sha256=document.content_sha256, storage_uri="file:///a",
            filename="a.pdf", extension=".pdf", size_bytes=1)
        second, created_b = repo.upsert_document(
            content_sha256=document.content_sha256, storage_uri="file:///b",
            filename="b.pdf", extension=".pdf", size_bytes=1)
    assert created_a is True and created_b is False
    assert first.id == second.id


def test_rerunning_the_same_document_does_not_duplicate_the_run(factory, envelope):
    document = ingest.load(RESUME)
    with session_scope(factory) as session:
        repo = Repository(session)
        seed(repo)
        stored, _ = repo.upsert_document(
            content_sha256=document.content_sha256, storage_uri="file:///a",
            filename="a.pdf", extension=".pdf", size_bytes=1)
        _, made_first = repo.save_run(envelope, document_id=stored.id)
        _, made_again = repo.save_run(envelope, document_id=stored.id)
    assert made_first is True
    assert made_again is False


def test_force_overwrites_rather_than_duplicating(factory, envelope):
    document = ingest.load(RESUME)
    with session_scope(factory) as session:
        repo = Repository(session)
        seed(repo)
        stored, _ = repo.upsert_document(
            content_sha256=document.content_sha256, storage_uri="file:///a",
            filename="a.pdf", extension=".pdf", size_bytes=1)
        repo.save_run(envelope, document_id=stored.id)
        changed = dict(envelope, status="SUCCESS", confidence_aggregate=0.99)
        run, made = repo.save_run(changed, document_id=stored.id, force=True)
    assert made is False
    assert run.confidence_aggregate == 0.99


# -- constraints --------------------------------------------------------------
def test_invalid_run_status_is_rejected(factory, envelope):
    with pytest.raises((IntegrityError, DBAPIError)), session_scope(factory) as session:
        repo = Repository(session)
        seed(repo)
        repo.save_run(dict(envelope, status="PROBABLY_FINE"), document_id=None)


def test_invalid_review_resolution_is_rejected(factory, envelope):
    with session_scope(factory) as session:
        repo = Repository(session)
        seed(repo)
        run, _ = repo.save_run(envelope, document_id=None)
        task = repo.create_review_task(run)
        with pytest.raises(ValueError):
            repo.resolve_review(task, reviewer="r@x.com", state="MAYBE")


# -- review queue -------------------------------------------------------------
def test_review_queue_puts_riskiest_first(factory, envelope):
    with session_scope(factory) as session:
        repo = Repository(session)
        seed(repo)
        for run_id, confidence in [("RUN-hi", 0.95), ("RUN-lo", 0.31), ("RUN-mid", 0.62)]:
            run, _ = repo.save_run(
                dict(envelope, workflow_run_id=run_id, confidence_aggregate=confidence),
                document_id=None)
            repo.create_review_task(run)
        queue = repo.review_queue()
        assert [t.workflow_run_id for t in queue] == ["RUN-lo", "RUN-mid", "RUN-hi"]


def test_resolving_a_review_records_who_and_why(factory, envelope):
    with session_scope(factory) as session:
        repo = Repository(session)
        seed(repo)
        run, _ = repo.save_run(envelope, document_id=None)
        task = repo.create_review_task(run)
        repo.resolve_review(task, reviewer="recruiter@x.com", state="APPROVED",
                            reason_code="VERIFIED_AGAINST_SOURCE")
        assert task.reviewer == "recruiter@x.com"
        assert task.resolved_at is not None


# -- retention ----------------------------------------------------------------
def test_retention_is_per_jurisdiction(factory):
    config = OrganizationConfig.load(ROOT / "config" / "organization.example.yaml")
    with session_scope(factory) as session:
        repo = Repository(session)
        repo.ensure_candidate("CAN-EU", jurisdiction="EU", consent_on_file=False)
        repo.ensure_candidate("CAN-US", jurisdiction="US-NY", consent_on_file=False)

        at_200_days = datetime.now(UTC) + timedelta(days=200)
        expired = {c.id for c in repo.candidates_past_retention(config, now=at_200_days)}
        # EU is 180 days; US-NY is 1095 for EEOC record-keeping.
        assert expired == {"CAN-EU"}


def test_consent_extends_but_does_not_remove_the_window(factory):
    config = OrganizationConfig.load(ROOT / "config" / "organization.example.yaml")
    with session_scope(factory) as session:
        repo = Repository(session)
        repo.ensure_candidate("CAN-C", jurisdiction="EU", consent_on_file=True)
        at_400 = datetime.now(UTC) + timedelta(days=400)
        at_800 = datetime.now(UTC) + timedelta(days=800)
        assert repo.candidates_past_retention(config, now=at_400) == []
        assert len(repo.candidates_past_retention(config, now=at_800)) == 1


def test_hired_candidates_are_kept_as_employment_records(factory):
    config = OrganizationConfig.load(ROOT / "config" / "organization.example.yaml")
    with session_scope(factory) as session:
        repo = Repository(session)
        candidate = repo.ensure_candidate("CAN-H", jurisdiction="EU")
        candidate.outcome = "HIRED"
        session.flush()
        at_400 = datetime.now(UTC) + timedelta(days=400)
        assert repo.candidates_past_retention(config, now=at_400) == []


# -- audit trail --------------------------------------------------------------
def test_audit_trail_is_chronological_and_carries_br05_fields(factory, envelope):
    with session_scope(factory) as session:
        repo = Repository(session)
        seed(repo)
        run, _ = repo.save_run(envelope, document_id=None)
        for event in ("extraction.started", "extraction.completed", "review.queued"):
            repo.append_audit(event=event, actor="system", workflow_run_id=run.id,
                              prompt_version=envelope["prompt_version"],
                              model_id=envelope["model_id"],
                              content_sha256="a" * 64)
        trail = repo.audit_trail(run.id)
        assert [e.event for e in trail] == [
            "extraction.started", "extraction.completed", "review.queued"]
        for entry in trail:
            assert entry.prompt_version and entry.model_id and entry.content_sha256
