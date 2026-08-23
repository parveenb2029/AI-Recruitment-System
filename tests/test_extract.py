"""Extraction tests. All run with FakeLLM — no API key, no network, no cost."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from recruit import extract as extract_mod
from recruit.adapters.llm import FakeLLM
from recruit.prompts import PromptError, WorkflowPrompt, dereference, load_results_schema

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "wf03_fake_results.json"
RESUME = ROOT / "samples" / "Rahul_Sharma_Resume.pdf"

pytestmark = pytest.mark.skipif(
    not RESUME.is_file() or not FIXTURE.is_file(), reason="fixtures not present"
)


def make_llm() -> FakeLLM:
    return FakeLLM(FIXTURE)


# -- prompt loading -----------------------------------------------------------
def test_prompt_loads_from_markdown_not_python():
    prompt = WorkflowPrompt.load("WF-03", ROOT)
    assert prompt.version == "1.0.0"
    assert "NEVER infer protected characteristics" in prompt.system
    assert "{{candidate_id}}" in prompt.user_template


def test_unfilled_runtime_variable_is_an_error():
    """An unfilled {{candidate_id}} would reach the model as literal text."""
    prompt = WorkflowPrompt.load("WF-03", ROOT)
    with pytest.raises(PromptError, match="candidate_id"):
        prompt.render_user(requisition_id="REQ-1")


def test_render_fills_every_variable():
    prompt = WorkflowPrompt.load("WF-03", ROOT)
    rendered = prompt.render_user(
        requisition_id="REQ-1", candidate_id="CAN-2", workflow_run_id="RUN-3",
        source_channel="cli", priority="standard",
        document_text_or_structured_input="RESUME BODY",
        schema_version="1.0.0", additional_context="none",
    )
    assert "{{" not in rendered
    assert "RESUME BODY" in rendered


# -- schema dereferencing -----------------------------------------------------
def _file_refs(node, found=None):
    found = [] if found is None else found
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and not ref.startswith("#"):
            found.append(ref)
        for value in node.values():
            _file_refs(value, found)
    elif isinstance(node, list):
        for value in node:
            _file_refs(value, found)
    return found


@pytest.mark.parametrize("workflow", ["WF-03", "WF-04"])
def test_schema_is_self_contained(workflow):
    """No provider resolves external $refs in a tool schema."""
    schema = load_results_schema(workflow, ROOT / "schemas")
    assert _file_refs(schema) == []


def test_dereference_inlines_real_properties():
    schema = load_results_schema("WF-03", ROOT / "schemas")
    profile = schema["properties"]["profile"]["properties"]
    assert "personal_info" in profile
    assert "experience" in profile


def test_missing_referenced_schema_is_reported(tmp_path):
    (tmp_path / "a.schema.json").write_text(json.dumps({"$ref": "ghost.schema.json"}))
    with pytest.raises(PromptError, match="not found"):
        dereference({"$ref": "a.schema.json"}, tmp_path)


def test_workflow_without_a_contract_fails_clearly():
    with pytest.raises(PromptError, match="out of v1 scope"):
        load_results_schema("WF-01", ROOT / "schemas")


# -- extraction ---------------------------------------------------------------
def test_end_to_end_produces_valid_envelope():
    envelope = extract_mod.extract(RESUME, llm=make_llm(), root=ROOT)
    assert envelope["workflow_id"] == "WF-03"
    assert envelope["prompt_version"] == "1.0.0"
    assert envelope["model_id"] == "fake-model-v0"
    assert envelope["results"]["profile"]["personal_info"]["full_name"] == "Rahul Sharma"


def test_confidence_is_the_minimum_not_the_mean():
    """Averaging would let nine good fields hide one fabricated employer."""
    assert extract_mod._aggregate_confidence({"/a": 0.99, "/b": 0.99, "/c": 0.20}) == 0.20


def test_low_confidence_forces_review_and_partial_status():
    envelope = extract_mod.extract(RESUME, llm=make_llm(), root=ROOT)
    assert envelope["human_review_required"] is True
    assert envelope["status"] == "PARTIAL"
    assert "LOW_CONFIDENCE_FIELDS" in envelope["review_reasons"]
    assert "/experience/1/end_date" in envelope["results"]["low_confidence_fields"]


def test_ingest_facts_override_whatever_the_model_claims():
    """The model must not be trusted to report the page count or the hash."""
    envelope = extract_mod.extract(RESUME, llm=make_llm(), root=ROOT)
    metadata = envelope["results"]["extraction_metadata"]
    assert metadata["content_sha256"] != "0" * 64      # fixture's bogus value
    assert metadata["pages_processed"] == 1
    assert metadata["source_char_count"] > 100


def test_run_id_is_deterministic_for_the_same_document():
    a = extract_mod.extract(RESUME, llm=make_llm(), root=ROOT)
    b = extract_mod.extract(RESUME, llm=make_llm(), root=ROOT)
    assert a["workflow_run_id"] == b["workflow_run_id"]


def test_model_receives_a_self_contained_schema_and_the_resume_text():
    llm = make_llm()
    extract_mod.extract(RESUME, llm=llm, root=ROOT)
    call = llm.calls[0]
    assert _file_refs(call["schema"]) == []
    assert "RAHUL SHARMA" in call["user"]
    assert "{{" not in call["user"]


def test_evidence_is_lifted_into_the_envelope():
    envelope = extract_mod.extract(RESUME, llm=make_llm(), root=ROOT)
    assert len(envelope["evidence"]) == 3
    assert "evidence" not in envelope["results"]
