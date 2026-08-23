"""Populate the database with sample data so a new install shows a working queue.

    python -m recruit.seed

An empty first screen makes a tool look broken. This runs the real pipeline —
ingest, extract with the fake model, validate, persist — over the sample
documents, so what you see in the console is genuine output, not fixtures pasted
into tables.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .adapters.llm import FakeLLM
from .db.migrations import create_all
from .db.repository import Repository
from .db.session import create_engine_from_config, make_session_factory, session_scope
from .errors import RecruitError
from .extract import extract
from .ingest import load as load_document
from .validate import validate as run_validation

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "wf03_fake_results.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m recruit.seed", description=__doc__)
    parser.add_argument("--url", help="Override DATABASE_URL.")
    parser.add_argument("files", nargs="*", type=Path,
                        help="Documents to seed. Defaults to samples/*.pdf")
    args = parser.parse_args(argv)

    files = args.files or sorted((ROOT / "samples").glob("*.pdf"))
    if not files:
        print("No sample documents found.", file=sys.stderr)
        return 1
    if not FIXTURE.is_file():
        print(f"Missing fixture: {FIXTURE}", file=sys.stderr)
        return 1

    config = None
    try:
        from .config import OrganizationConfig
        config = OrganizationConfig.load()
    except Exception:
        pass

    engine = create_engine_from_config(config, url=args.url)
    create_all(engine)
    factory = make_session_factory(engine)

    seeded = skipped = 0
    for index, path in enumerate(files):
        candidate_id = f"CAN-{88421 + index}"
        requisition_id = "REQ-2026-0142"
        try:
            envelope = extract(
                path, llm=FakeLLM(FIXTURE), config=config,
                requisition_id=requisition_id, candidate_id=candidate_id, root=ROOT,
            )
            document = load_document(path)
        except RecruitError as error:
            print(f"  skipped  {path.name}: {error.code}")
            skipped += 1
            continue

        report = run_validation(envelope, source_text=document.text, config=config)
        if not report.is_valid:
            envelope["status"] = "PARTIAL"
            envelope["human_review_required"] = True
        envelope["flags"] = sorted(set(envelope.get("flags", []) + report.flags))

        with session_scope(factory) as session:
            repo = Repository(session)
            repo.ensure_requisition(requisition_id, title="Software Engineer II",
                                    department="Engineering", jurisdiction="EU")
            profile = (envelope.get("results") or {}).get("profile") or {}
            personal = profile.get("personal_info") or {}
            repo.ensure_candidate(candidate_id, requisition_id=requisition_id,
                                  full_name=personal.get("full_name"),
                                  email=personal.get("email"), jurisdiction="EU")
            stored, _ = repo.upsert_document(
                content_sha256=document.content_sha256,
                storage_uri=path.resolve().as_uri(), filename=path.name,
                extension=document.extension, size_bytes=document.size_bytes,
                pages=document.pages, char_count=document.char_count,
                ocr_used=document.ocr_used, candidate_id=candidate_id,
            )
            run, created = repo.save_run(envelope, document_id=stored.id,
                                         validation=report.summary())
            if not created:
                print(f"  exists   {path.name} -> {run.id}")
                skipped += 1
                continue
            if envelope.get("human_review_required"):
                repo.create_review_task(run)
            repo.append_audit(
                event="extraction.completed", actor="seed", actor_role="service",
                workflow_run_id=run.id, workflow_id=run.workflow_id,
                candidate_id=candidate_id, requisition_id=requisition_id,
                prompt_version=envelope["prompt_version"], model_id=envelope["model_id"],
                content_sha256=document.content_sha256,
                detail={"seeded": True, "email": personal.get("email")},
            )
            print(f"  seeded   {path.name} -> {run.id}  "
                  f"confidence {envelope['confidence_aggregate']}")
            seeded += 1

    print(f"\n  {seeded} seeded, {skipped} skipped")
    if seeded:
        print("  Start the console with:  python -m recruit.web")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
