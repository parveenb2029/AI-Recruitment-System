"""Load prompts from the markdown specs, and prepare schemas for the model.

Two jobs:

1. **Prompt loading.** The system and user prompts live in the workflow's
   `Prompt.md`, not in Python string literals. That is deliberate: the markdown
   is the governed, reviewed artifact (see `10_SOPs/Prompt_Governance_SOP.md`),
   and duplicating it in code would guarantee the two drift apart. Code reads
   the spec; the spec is the source of truth.

2. **Schema dereferencing.** Our schemas cross-reference each other by filename
   (`{"$ref": "resume.schema.json"}`). No LLM provider resolves external `$ref`s
   in a tool schema — they need one self-contained document. `dereference()`
   inlines them.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_DIR = ROOT / "schemas"

# Runtime prompt variables, filled per workflow run. Distinct from the
# build-time {{org.*}} placeholders that tools/render_docs.py resolves.
RUNTIME_VAR = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


class PromptError(RuntimeError):
    pass


# -- prompt loading -----------------------------------------------------------
def _fenced_block_after(text: str, heading: str) -> str:
    """Return the first fenced code block following a markdown heading."""
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*$.*?^```[a-zA-Z]*\s*$(.*?)^```\s*$",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        raise PromptError(f"No fenced block found under heading '## {heading}'")
    return match.group(1).strip("\n")


class WorkflowPrompt:
    """The system prompt, user template, and version for one workflow."""

    def __init__(self, workflow_id: str, folder: Path) -> None:
        self.workflow_id = workflow_id
        self.path = folder / "Prompt.md"
        if not self.path.is_file():
            raise PromptError(f"No Prompt.md at {self.path}")
        text = self.path.read_text(encoding="utf-8")

        self.system = _fenced_block_after(text, "System Prompt")
        self.user_template = _fenced_block_after(text, "User Prompt Template")

        version = re.search(r"^\*\*Prompt Version:\*\*\s*([0-9]+\.[0-9]+\.[0-9]+)",
                            text, re.MULTILINE)
        if not version:
            raise PromptError(f"No '**Prompt Version:**' line in {self.path}")
        self.version = version.group(1)

    @classmethod
    def load(cls, workflow_id: str, root: Path | None = None) -> WorkflowPrompt:
        base = root or ROOT
        folders = {
            "WF-01": "01_Job_Descriptions",
            "WF-02": "02_Incoming_Resumes",
            "WF-03": "03_Extracted_Data",
            "WF-04": "04_Match_Results",
            "WF-05": "05_Shortlisted",
            "WF-06": "06_Interview_Questions",
            "WF-07": "07_Interview_Feedback",
            "WF-08": "08_Final_Decision",
        }
        if workflow_id not in folders:
            raise PromptError(f"Unknown workflow: {workflow_id}")
        return cls(workflow_id, base / folders[workflow_id])

    def render_user(self, **variables: Any) -> str:
        """Fill the runtime variables. Every one must be supplied.

        An unfilled `{{candidate_id}}` reaching the model is a silent data bug —
        it would be read as literal text. Fail loudly instead.
        """
        required = set(RUNTIME_VAR.findall(self.user_template))
        supplied = {k for k, v in variables.items() if v is not None}
        missing = required - supplied
        if missing:
            raise PromptError(
                f"{self.workflow_id} user template needs variables that were not "
                f"supplied: {', '.join(sorted(missing))}"
            )
        out = self.user_template
        for key, value in variables.items():
            out = RUNTIME_VAR.sub(
                lambda m, k=key, v=value: str(v) if m.group(1) == k else m.group(0),
                out,
            )
        return out


# -- schema dereferencing -----------------------------------------------------
def dereference(
    schema: dict[str, Any],
    schema_dir: Path | None = None,
    _seen: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Inline every file-based `$ref` so the schema stands alone.

    Recursive file refs raise rather than looping forever.

    **A fragment ref drags its home document's `$defs` along with it.** Pulling
    `envelope.schema.json#/$defs/evidence_ref` into a schema that has no `$defs`
    of its own leaves the definition's *own* internal refs —
    `#/$defs/json_pointer`, `#/$defs/confidence` — pointing at nothing. The
    result looks fine and is quietly broken: a validator raises on the dangling
    pointer, and a provider compiling a grammar simply leaves those fields
    unconstrained, which is the silent half and the dangerous one. So the
    fragment's source `$defs` are merged into the top-level schema, which is
    where a local ref resolves from.
    """
    directory = schema_dir or SCHEMA_DIR

    borrowed: dict[str, Any] = {}

    def walk(node: Any, seen: frozenset[str]) -> Any:
        if isinstance(node, list):
            return [walk(item, seen) for item in node]
        if not isinstance(node, dict):
            return node

        ref = node.get("$ref")
        if isinstance(ref, str) and not ref.startswith("#"):
            filename, _, fragment = ref.partition("#")
            if filename in seen:
                raise PromptError(f"Recursive schema reference: {filename}")
            target = directory / filename
            if not target.is_file():
                raise PromptError(f"Referenced schema not found: {target}")
            loaded = json.loads(target.read_text(encoding="utf-8"))

            if fragment:
                # Keep the home document's definitions: the fragment we are
                # about to lift may refer to its siblings by local pointer.
                for name, block in (loaded.get("$defs") or {}).items():
                    borrowed.setdefault(name, block)
                for part in fragment.strip("/").split("/"):
                    if part not in loaded:
                        raise PromptError(f"Bad ref fragment {ref}: no '{part}'")
                    loaded = loaded[part]

            inlined = walk(copy.deepcopy(loaded), seen | {filename})
            if isinstance(inlined, dict):
                # $schema/$id are meaningless once inlined into a parent.
                inlined.pop("$schema", None)
                inlined.pop("$id", None)
                # Sibling keys alongside $ref (title, description) win.
                siblings = {k: v for k, v in node.items() if k != "$ref"}
                inlined.update(walk(siblings, seen))
            return inlined

        return {key: walk(value, seen) for key, value in node.items()}

    result = walk(copy.deepcopy(schema), _seen)
    if not isinstance(result, dict):
        raise PromptError("Dereferenced schema is not an object")

    # Only the definitions something still points at. Copying the whole block
    # would bulk out every request with dead weight, and the schema is sent on
    # every call.
    if borrowed:
        wanted = {name: block for name, block in borrowed.items()
                  if f'"#/$defs/{name}"' in json.dumps(result)}
        if wanted:
            defs = dict(result.get("$defs") or {})
            for name, block in wanted.items():
                defs.setdefault(name, block)
            result["$defs"] = defs
    return result


# How many entries of a repeated section (jobs, degrees) get pointers offered.
# Ten covers a long career; beyond it, confidence for the extra entries simply
# cannot be reported, which is a stated limit rather than a silent truncation.
POINTER_ARRAY_BOUND = 10


def pointer_enum(profile_schema: Any, array_bound: int = POINTER_ARRAY_BOUND) -> list[str]:
    """Every JSON Pointer a model is allowed to report confidence for.

    Derived from the profile schema, never hand-listed: a field added to
    `resume.schema.json` becomes reportable the same day, and one removed stops
    being offered. A hand-maintained copy would be wrong within a month.

    This exists because of a real failure. Asked for a pointer as a free string,
    a model returns `email` and `company` — field names, not paths — and
    `company` is ambiguous anyway, appearing once per job. Constraining the
    format with a regex works but is ruinously slow inside a decoding grammar.
    An enum is neither: it is a flat alternation, cheap to evaluate, and it
    makes the wrong answer **unreachable** rather than discouraged. Third time
    this project has taken that route, after the stripped fit-score fields and
    the list-shaped `field_confidence`.
    """
    out: list[str] = []

    def walk(node: Any, prefix: str, depth: int) -> None:
        if depth > 6 or not isinstance(node, dict):
            return
        if node.get("type") == "object" or "properties" in node:
            for name, child in (node.get("properties") or {}).items():
                here = f"{prefix}/{name}"
                out.append(here)
                walk(child, here, depth + 1)
        elif node.get("type") == "array":
            items = node.get("items") or {}
            if isinstance(items, dict) and (items.get("properties")
                                            or items.get("type") == "object"):
                for index in range(array_bound):
                    walk(items, f"{prefix}/{index}", depth + 1)

    walk(profile_schema, "", 0)
    return sorted(set(out))


def with_pointer_enum(schema: dict[str, Any],
                      array_bound: int = POINTER_ARRAY_BOUND) -> dict[str, Any]:
    """Offer the model a menu of pointers instead of a blank line.

    Returns a copy; the original stays as validation received it. A schema
    without the expected `field_confidence` shape is returned untouched rather
    than raising — this is a convenience over the contract, not part of it.
    """
    profile = (schema.get("properties") or {}).get("profile")
    pointer = (((schema.get("properties") or {}).get("field_confidence") or {})
               .get("items", {}).get("properties", {}).get("pointer"))
    if not isinstance(profile, dict) or not isinstance(pointer, dict):
        return schema

    choices = pointer_enum(profile, array_bound)
    if not choices:
        return schema

    out = copy.deepcopy(schema)
    target = out["properties"]["field_confidence"]["items"]["properties"]["pointer"]
    target["enum"] = choices
    target.pop("pattern", None)      # the enum is stricter; the regex is dead weight
    return out


# Fields on an evidence citation that the VALIDATOR fills in, never the model.
# `char_start`/`char_end` are found by `validate.locate_snippet` while it is
# already searching for the snippet, and `match_score` is the result of that
# search. Asking a model for a character offset asks it to count, which is the
# one thing language models are reliably bad at — and a wrong offset would
# highlight the wrong words in the review console, which is worse than none.
COMPUTED_EVIDENCE_FIELDS = ("char_start", "char_end", "match_score")


def with_required_evidence(schema: dict[str, Any],
                          array_bound: int = POINTER_ARRAY_BOUND) -> dict[str, Any]:
    """Make a citation something the model must produce and can produce.

    Two separate failures met here, and the second one hid the first.

    **The model was forbidden to cite.** `results` sets
    `additionalProperties: false`, and `evidence` was not among its properties —
    so the grammar would not let a model emit the key at all, while
    `extract` did `results.pop("evidence", [])` and got an empty list every
    time. VR-03, described in this project's own notes as the most important
    code in it, had never once been handed real model output. The suite never
    noticed because `FakeLLM` returns its fixture directly, bypassing the
    schema, and that fixture has always carried three citations.

    **And an empty list was legal.** Even once the key was allowed, nothing
    required a single entry, and the prose in the system prompt asking for
    citations was exactly the kind of request a model is free to ignore — the
    same mistake as the pointer format, one layer up.

    So this adds `required` and `minItems: 1` **to the model-facing copy only**,
    and strips the fields the validator fills in, so the model is asked for
    exactly what it knows: which field, and the words it read. The stored
    schema cannot require them, because `extract` lifts the array onto the
    envelope and by validation time the key is legitimately gone.
    """
    evidence = (schema.get("properties") or {}).get("evidence")
    if not isinstance(evidence, dict) or not isinstance(evidence.get("items"), dict):
        return schema

    out = copy.deepcopy(schema)
    out["properties"]["evidence"]["minItems"] = 1
    required = list(out.get("required") or [])
    if "evidence" not in required:
        required.append("evidence")
    out["required"] = required

    item = out["properties"]["evidence"]["items"]
    for name in COMPUTED_EVIDENCE_FIELDS:
        (item.get("properties") or {}).pop(name, None)
    if isinstance(item.get("required"), list):
        item["required"] = [r for r in item["required"]
                            if r not in COMPUTED_EVIDENCE_FIELDS]

    # **A citation must say what it is a citation FOR.** `pointer` was optional,
    # so a model could quote a line of the resume and attach it to nothing —
    # which reads as evidence, counts as evidence, and cannot be checked against
    # any field. VR-05 silently skipped every such entry. Requiring the pointer,
    # and constraining it to the same menu of real paths, means every citation
    # lands on something and the check can always run.
    profile = (out.get("properties") or {}).get("profile")
    properties = item.get("properties") or {}
    if isinstance(profile, dict) and "pointer" in properties:
        choices = pointer_enum(profile, array_bound)
        if choices:
            # **Replaced outright, not amended.** `pointer` arrives here as
            # `{"$ref": "#/$defs/json_pointer"}`, and adding `enum` beside a
            # `$ref` produces a schema that reads correctly and does nothing:
            # grammar conversion follows the reference and ignores the sibling.
            # The first version of this did exactly that, the constraint was
            # decoration, and a real model answered `pointer: "RAHUL SHARMA"` —
            # the value, not a path to it. A test now asserts no `$ref` survives
            # on this property, because the broken version looks fine.
            properties["pointer"] = {
                "type": "string",
                "enum": choices,
                "description": (
                    "Which extracted field this snippet is evidence FOR. A path, "
                    "not the text: /personal_info/email, never the address itself."
                ),
            }
            item_required = list(item.get("required") or [])
            if "pointer" not in item_required:
                item_required.append("pointer")
            item["required"] = item_required
    return out


def without_regex_constraints(schema: Any) -> Any:
    """Drop `pattern` from a schema before handing it to a model.

    **Not cosmetic — it is the difference between a run and a five-minute
    stall.** Structured output compiles the schema into a grammar the model has
    to decode within, and a regular expression becomes part of that grammar. A
    nested quantifier like `^(/[^/]*)+$` — a repeated group containing a
    repeated character class — expands into an enormous state machine that is
    re-evaluated at every single token. The first run with a pointer pattern on
    a string property did not finish in five minutes; the same schema with the
    pattern removed answers in the usual couple of minutes.

    The reason it appeared suddenly is worth recording: the same regex was in
    the schema before, under `propertyNames`, and cost nothing — because
    `propertyNames` is one of the keywords grammar conversion *ignores*. That is
    the same silence that let the pointer format go unenforced for the project's
    entire life. Moving the constraint somewhere it is honoured is what made it
    expensive, which is a fair price and a real trade.

    So: the model is constrained to the SHAPE — a list of objects, each with a
    `pointer` string and a `confidence` number — and the pointer's *format* is
    taught by the worked example in the prompt and enforced afterwards by
    validation (VR-02). A wrong format then arrives as a clear finding on the
    review screen instead of as a timeout with no explanation.

    Only `pattern` is stripped. `format` is left alone: date and email are
    cheap, well-supported hints rather than compiled expressions.
    """
    if isinstance(schema, dict):
        return {k: without_regex_constraints(v)
                for k, v in schema.items() if k != "pattern"}
    if isinstance(schema, list):
        return [without_regex_constraints(item) for item in schema]
    return schema


def load_results_schema(workflow_id: str, schema_dir: Path | None = None) -> dict[str, Any]:
    """The self-contained results schema for a workflow, ready to hand a model."""
    directory = schema_dir or SCHEMA_DIR
    path = directory / f"{workflow_id}_results.schema.json"
    if not path.is_file():
        raise PromptError(
            f"No results schema for {workflow_id} at {path}. "
            "Only WF-03 and WF-04 have contracts; the rest are out of v1 scope."
        )
    schema = json.loads(path.read_text(encoding="utf-8"))
    resolved = dereference(schema, directory)
    resolved.pop("$schema", None)
    resolved.pop("$id", None)
    return resolved
