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
    def load(cls, workflow_id: str, root: Path | None = None) -> "WorkflowPrompt":
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

    Local refs (`#/$defs/...`) are left in place — providers handle those.
    Recursive file refs raise rather than looping forever.
    """
    directory = schema_dir or SCHEMA_DIR

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
    return result


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
