"""Per-field confidence, and why its shape changed.

`results.field_confidence` used to be an object keyed by JSON Pointer:

    {"/personal_info/email": 0.98}

It is now a list of pairs:

    [{"pointer": "/personal_info/email", "confidence": 0.98}]

**The reason is enforceability, not taste.** Structured output — Ollama's
`format`, Anthropic's forced tool use — compiles the schema into a grammar the
model has to decode within. A grammar can constrain the shape and type of a
*value*. It cannot constrain an arbitrary object *key* to a regular expression.
So `propertyNames: {pattern: ...}` was a request the model was free to ignore,
and the first extraction by a real model ignored it: plain `full_name` instead
of `/personal_info/full_name`, thirty-one validation errors on an extraction
whose name, email, roles and skills were all correct.

Moving the pointer into a property makes it something the grammar constrains.
The bug stops being possible rather than being discouraged — the same move made
in Phase 3.6, where the fit-score fields were stripped from the model-facing
schema so the model could not return one.
"""

from __future__ import annotations

import json
from pathlib import Path

from recruit import confidence

ROOT = Path(__file__).resolve().parent.parent


def test_the_shape_models_are_asked_for_is_read():
    results = {"field_confidence": [
        {"pointer": "/personal_info/email", "confidence": 0.98},
        {"pointer": "/experience/0/title", "confidence": 0.91},
    ]}
    assert confidence.read(results) == {
        "/personal_info/email": 0.98, "/experience/0/title": 0.91,
    }


def test_runs_recorded_before_the_change_still_open():
    """The archive is evidence, not a file to migrate.

    The audit log is append-only and extraction envelopes are kept as the
    record of what happened. A console that could not read a run from last
    month would make the older half of that record unreadable, which is the
    opposite of what an evidence trail is for. So the old shape is read
    forever, even though nothing writes it any more.
    """
    old = {"field_confidence": {"/personal_info/email": 0.98}}
    assert confidence.read(old) == {"/personal_info/email": 0.98}


def test_a_malformed_entry_is_skipped_rather_than_raising():
    """This is model output on its way to a reviewer.

    One bad row must not take down the screen that exists to catch bad rows.
    """
    results = {"field_confidence": [
        {"pointer": "/a", "confidence": 0.9},
        {"pointer": "/b"},                      # no confidence
        {"confidence": 0.5},                    # no pointer
        "not an object",
        {"pointer": "/c", "confidence": "high"},  # not a number
    ]}
    assert confidence.read(results) == {"/a": 0.9}


def test_nothing_at_all_is_an_empty_answer_not_an_error():
    for value in (None, {}, {"field_confidence": None}, {"field_confidence": 7}):
        assert confidence.read(value) == {}


def test_the_round_trip_is_stable_and_sorted():
    """Sorted so two runs of the same document produce identical bytes."""
    mapping = {"/b": 0.5, "/a": 0.9}
    pairs = confidence.as_pairs(mapping)

    assert [p["pointer"] for p in pairs] == ["/a", "/b"]
    assert confidence.read({"field_confidence": pairs}) == mapping


# -- the contract the model is actually handed --------------------------------
def test_the_schema_constrains_the_pointer_as_a_value():
    """The whole point, asserted against the schema itself.

    If a future edit moves this back to an object keyed by pointer, every model
    becomes free to invent its own key format again — silently, because the
    output still looks structurally fine.
    """
    schema = json.loads(
        (ROOT / "schemas" / "WF-03_results.schema.json").read_text(encoding="utf-8")
    )
    field_confidence = schema["properties"]["field_confidence"]

    assert field_confidence["type"] == "array", (
        "field_confidence must stay a list: a grammar cannot constrain object keys"
    )
    item = field_confidence["items"]
    assert item["required"] == ["pointer", "confidence"]
    assert item["properties"]["pointer"]["pattern"] == "^(/[^/]*)+$"
    assert item["additionalProperties"] is False


def test_the_prompt_shows_the_model_the_shape_it_must_produce():
    """A schema the model must obey and an example it copies must agree.

    Models imitate the worked example at least as strongly as they obey the
    schema. An example still showing the old shape would actively teach the
    mistake the schema change exists to prevent.
    """
    prompt = (ROOT / "03_Extracted_Data" / "Prompt.md").read_text(encoding="utf-8")

    assert '"field_confidence": [' in prompt
    assert '{"pointer": "/personal_info/email", "confidence": 0.98}' in prompt
    # The old shape must not survive anywhere in the example.
    assert '"/personal_info/email": 0.98' not in prompt


def test_the_fake_model_answers_in_the_shape_a_real_one_is_asked_for():
    """`FakeLLM` is the whole test suite's stand-in for a model.

    If its fixture drifts from the contract, every test passes against a shape
    no real model will ever send, which is how a suite ends up green while the
    product is broken.
    """
    fixture = json.loads(
        (ROOT / "tests" / "fixtures" / "wf03_fake_results.json").read_text(encoding="utf-8")
    )
    assert isinstance(fixture["field_confidence"], list)
    assert all({"pointer", "confidence"} == set(entry)
               for entry in fixture["field_confidence"])


# -- the pointer the model is allowed to write --------------------------------
def test_the_model_is_offered_real_pointers_rather_than_a_blank_line():
    """Free-text pointers came back as field names, twice.

    First with the schema keyed by pointer, then again with the pointer as a
    plain string property: a real model returned `email` and `company` rather
    than `/personal_info/email`. `company` is ambiguous anyway — it appears once
    per job — so no amount of cleaning up afterwards recovers what was meant.

    An enum makes the wrong answer unreachable. That is the third time this
    project has chosen "structurally impossible" over "asked nicely", after the
    stripped fit-score fields and the list-shaped field_confidence.
    """
    from recruit.prompts import load_results_schema, with_pointer_enum

    schema = load_results_schema("WF-03", ROOT / "schemas")
    offered = with_pointer_enum(schema)
    pointer = offered["properties"]["field_confidence"]["items"]["properties"]["pointer"]

    assert "enum" in pointer
    assert "/personal_info/email" in pointer["enum"]
    assert "/experience/0/company" in pointer["enum"]
    # The shapes a model actually produced, now unreachable.
    assert "email" not in pointer["enum"]
    assert "company" not in pointer["enum"]
    # The enum is stricter than the regex, so the regex is dead weight.
    assert "pattern" not in pointer


def test_the_menu_is_derived_from_the_profile_schema_not_hand_listed():
    """A hand-maintained list would be wrong within a month."""
    from recruit.prompts import pointer_enum

    invented = {"type": "object", "properties": {
        "nickname": {"type": "string"},
        "pets": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}}}},
    }}
    choices = pointer_enum(invented, array_bound=2)

    assert "/nickname" in choices
    assert "/pets/0/name" in choices and "/pets/1/name" in choices
    assert "/pets/2/name" not in choices        # the bound is honoured
    assert choices == sorted(choices)           # stable between runs


def test_a_schema_without_the_expected_shape_is_left_alone():
    """A convenience over the contract must not become part of it."""
    from recruit.prompts import with_pointer_enum

    odd = {"properties": {"something_else": {"type": "string"}}}
    assert with_pointer_enum(odd) == odd


def test_the_validation_schema_keeps_the_regex():
    """Two audiences, two schemas.

    The model gets a menu it cannot escape. Validation keeps the pattern, so an
    envelope that arrived from anywhere else - an older run, a different
    adapter, a hand-edited file - is still checked properly.
    """
    schema = json.loads(
        (ROOT / "schemas" / "WF-03_results.schema.json").read_text(encoding="utf-8")
    )
    pointer = schema["properties"]["field_confidence"]["items"]["properties"]["pointer"]
    assert pointer["pattern"] == "^(/[^/]*)+$"
    assert "enum" not in pointer


# -- the citation the model was never allowed to make -------------------------
def test_the_model_is_able_to_return_evidence_at_all():
    """The defect that made VR-03 decorative from Phase 1 until 2026-09-14.

    `results` sets `additionalProperties: false` and `evidence` was not one of
    its properties — so the grammar would not let a model emit the key, while
    `extract` popped `evidence` off the results and got `[]` every single time.
    The hallucination defence, called the most important code in this project,
    had never once been handed real model output to check.

    Nothing caught it because `FakeLLM` returns its fixture object directly,
    never passing it through the schema, and that fixture has always carried
    three citations. A fake that is not bound by the contract will tell you the
    contract works.
    """
    from jsonschema import Draft202012Validator

    from recruit.prompts import load_results_schema

    schema = load_results_schema("WF-03", ROOT / "schemas")
    assert "evidence" in schema["properties"], (
        "additionalProperties is false, so an undeclared key is a forbidden key"
    )

    # The fixture the entire suite leans on must be legal under the real
    # contract. It was not, and that is precisely how this hid.
    fixture = json.loads(
        (ROOT / "tests" / "fixtures" / "wf03_fake_results.json").read_text(encoding="utf-8")
    )
    errors = [e.message for e in Draft202012Validator(schema).iter_errors(fixture)]
    assert not errors, errors


def test_a_model_must_cite_at_least_once():
    """An empty array was legal, and the prose asking for citations was ignorable.

    Same shape as the pointer format one layer up: the system prompt said
    "include an evidence array", the schema permitted `[]`, and a real model
    took the schema at its word. `minItems` makes citing the only way to answer.
    """
    from recruit.prompts import load_results_schema, with_required_evidence

    model_facing = with_required_evidence(load_results_schema("WF-03", ROOT / "schemas"))

    assert model_facing["properties"]["evidence"]["minItems"] == 1
    assert "evidence" in model_facing["required"]


def test_the_model_is_not_asked_to_count_characters():
    """`char_start`, `char_end` and `match_score` are the validator's job.

    `locate_snippet` finds the offsets while it is already searching for the
    snippet, and `match_score` is that search's result. Asking a model for a
    character offset asks it to count — the one thing it is reliably bad at —
    and a wrong offset highlights the wrong words in the review console, which
    is worse than highlighting none.
    """
    from recruit.prompts import (
        COMPUTED_EVIDENCE_FIELDS,
        load_results_schema,
        with_required_evidence,
    )

    schema = load_results_schema("WF-03", ROOT / "schemas")
    asked_for = (with_required_evidence(schema)["properties"]["evidence"]
                 ["items"]["properties"])

    for name in COMPUTED_EVIDENCE_FIELDS:
        assert name not in asked_for
    # What is left is what the model genuinely knows.
    assert "snippet" in asked_for and "field" in asked_for
    # And the stored schema still describes them, for the validator that writes them.
    assert "char_start" in schema["properties"]["evidence"]["items"]["properties"]


def test_the_stored_schema_does_not_require_what_extract_moves_away():
    """Evidence lives on the envelope once `extract` has lifted it.

    Requiring it inside `results` would fail every real run at validation time,
    which is how a correct-looking constraint becomes a permanent red light.
    """
    schema = json.loads(
        (ROOT / "schemas" / "WF-03_results.schema.json").read_text(encoding="utf-8")
    )
    assert "evidence" in schema["properties"]
    assert "evidence" not in schema["required"]


def test_an_inlined_definition_brings_its_own_references_with_it():
    """A dangling `$ref` is the quiet kind of broken.

    `envelope.schema.json#/$defs/evidence_ref` refers to its neighbours —
    `#/$defs/json_pointer`, `#/$defs/confidence`. Lifted into a schema with no
    `$defs` of its own, those pointed at nothing. A validator raises on that,
    which is the loud half. The dangerous half is silent: a provider building a
    decoding grammar just leaves the unresolvable fields unconstrained, so the
    schema keeps working and quietly stops constraining.
    """
    import re

    from recruit.prompts import load_results_schema

    schema = load_results_schema("WF-03", ROOT / "schemas")
    blob = json.dumps(schema)

    for ref in set(re.findall(r'"\$ref":\s*"#/\$defs/([^"]+)"', blob)):
        assert ref in (schema.get("$defs") or {}), f"{ref} points at nothing"

    # No file refs survive either — the schema has to stand alone in a request.
    assert not [r for r in re.findall(r'"\$ref":\s*"([^"]+)"', blob)
                if not r.startswith("#")]
