#!/usr/bin/env python3
"""Validate a workflow output JSON file against its schema.

Usage:
    python tools/validate_output.py samples/WF-03_output_example.json
    python tools/validate_output.py <file.json> --schema WF-04_output.schema.json

The schema files in schemas/ reference each other by bare filename
(e.g. "resume.schema.json"). This script loads the whole directory into a
referencing Registry so those relative refs resolve without needing the
schemas to be published at a URL.

Exit code 0 = valid, 1 = invalid, 2 = usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012
except ImportError:
    sys.exit(
        "Missing dependency. Install with:\n"
        "    pip install jsonschema\n"
    )

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"


def build_registry(schema_dir: Path) -> Registry:
    """Load every *.schema.json into a registry keyed by bare filename."""
    registry = Registry()
    for path in sorted(schema_dir.glob("*.schema.json")):
        contents = json.loads(path.read_text(encoding="utf-8"))
        resource = Resource.from_contents(
            contents, default_specification=DRAFT202012
        )
        # Register under the bare filename, which is how our schemas cross-reference
        # each other. Also register under $id when one is present, so the older
        # schemas that carry absolute $id URLs still resolve.
        registry = registry.with_resource(uri=path.name, resource=resource)
        if "$id" in contents:
            registry = resource @ registry
    return registry


def infer_schema_name(document: dict) -> str | None:
    workflow_id = document.get("workflow_id")
    if isinstance(workflow_id, str) and workflow_id.startswith("WF-"):
        return f"{workflow_id}_output.schema.json"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path, help="JSON file to validate")
    parser.add_argument(
        "--schema",
        help="Schema filename in schemas/. Inferred from workflow_id if omitted.",
    )
    parser.add_argument(
        "--schema-dir", type=Path, default=SCHEMA_DIR, help="Defaults to ./schemas"
    )
    args = parser.parse_args()

    if not args.document.is_file():
        print(f"No such file: {args.document}", file=sys.stderr)
        return 2

    document = json.loads(args.document.read_text(encoding="utf-8"))
    schema_name = args.schema or infer_schema_name(document)
    if schema_name is None:
        print(
            "Could not infer schema: document has no recognisable workflow_id. "
            "Pass --schema explicitly.",
            file=sys.stderr,
        )
        return 2

    schema_path = args.schema_dir / schema_name
    if not schema_path.is_file():
        print(f"No such schema: {schema_path}", file=sys.stderr)
        return 2

    registry = build_registry(args.schema_dir)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, registry=registry)

    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.path))
    if not errors:
        print(f"VALID   {args.document.name}  against  {schema_name}")
        return 0

    print(f"INVALID {args.document.name}  against  {schema_name}")
    print(f"        {len(errors)} error(s):\n")
    for error in errors:
        location = "/".join(str(p) for p in error.absolute_path) or "(root)"
        print(f"  at {location}")
        print(f"     {error.message}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
