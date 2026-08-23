#!/usr/bin/env python3
"""Render documentation and schema templates using config/organization.yaml.

Source files under the project tree carry placeholders like {{org.legal_name}}.
This script resolves them and writes the result to build/, leaving the sources
untouched so a later config change re-renders cleanly.

    python tools/render_docs.py                 # render to build/
    python tools/render_docs.py --check         # report unresolved placeholders
    python tools/render_docs.py --in-place      # overwrite sources (rarely wanted)

Exit code 0 = success, 1 = unresolved placeholders, 2 = usage/config error.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency. Install with:\n    pip install pyyaml\n")

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "organization.yaml"
EXAMPLE_CONFIG = ROOT / "config" / "organization.example.yaml"
BUILD = ROOT / "build"

PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")

# Two different kinds of placeholder share the {{...}} syntax:
#
#   BUILD-TIME  {{org.legal_name}}   resolved here, from organization.yaml
#   RUNTIME     {{candidate_id}}     left alone; the orchestrator fills these
#                                    per workflow run when building the prompt
#
# Only keys under a known config namespace are resolved. Everything else is a
# runtime variable and must survive rendering untouched.
CONFIG_NAMESPACES = (
    "org.",
    "organization.",
    "contact.",
    "contacts.",
    "confidence.",
    "matching.",
    "slas.",
    "limits.",
    "locales.",
    "currency.",
    "adapters.",
    "jurisdictions.",
)
CONFIG_KEYS = ("eeo_statement", "default_jurisdiction")


def is_config_key(key: str) -> bool:
    return key.startswith(CONFIG_NAMESPACES) or key in CONFIG_KEYS

RENDER_GLOBS = [
    "*.md",
    "0*/*.md",
    "10_SOPs/*.md",
    "docs/**/*.md",
    "schemas/*.json",
]

SKIP_DIRS = {".git", "build", "node_modules", ".venv", "venv", "tools"}


def load_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        if EXAMPLE_CONFIG.is_file():
            sys.exit(
                f"No {path.relative_to(ROOT)} found.\n"
                f"Create one with:\n"
                f"    cp config/organization.example.yaml config/organization.yaml\n"
                f"then edit it with your details.\n"
            )
        sys.exit(f"No config found at {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def flatten(data: Any, prefix: str = "") -> dict[str, str]:
    """Flatten nested config to dotted keys: org.legal_name -> 'Example Ltd'."""
    flat: dict[str, str] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            flat.update(flatten(value, f"{prefix}{key}."))
    elif isinstance(data, list):
        for index, value in enumerate(data):
            flat.update(flatten(value, f"{prefix}{index}."))
    else:
        key = prefix.rstrip(".")
        if key:
            flat[key] = "" if data is None else str(data).strip()
    return flat


def build_context(config: dict[str, Any]) -> dict[str, str]:
    context = flatten(config)
    # Convenience aliases so templates read naturally.
    aliases = {
        "org.legal_name": "organization.legal_name",
        "org.display_name": "organization.display_name",
        "org.schema_base_url": "organization.schema_base_url",
        "org.email_domain": "organization.email_domain",
        "org.copyright": "organization.copyright_notice",
        "contact.ai_ops": "contacts.ai_ops.email",
        "contact.ai_ops_role": "contacts.ai_ops.role",
        "contact.ta_ops": "contacts.ta_ops.email",
        "contact.ta_ops_role": "contacts.ta_ops.role",
        "contact.hr_compliance": "contacts.hr_compliance.email",
        "contact.hr_compliance_role": "contacts.hr_compliance.role",
        "contact.dpo": "contacts.data_protection_officer.email",
        "contact.dpo_role": "contacts.data_protection_officer.role",
    }
    for alias, source in aliases.items():
        if source in context:
            context[alias] = context[source]
    return context


def iter_source_files() -> list[Path]:
    seen: set[Path] = set()
    for pattern in RENDER_GLOBS:
        for path in ROOT.glob(pattern):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
                continue
            seen.add(path)
    return sorted(seen)


def render(text: str, context: dict[str, str]) -> tuple[str, list[str]]:
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if not is_config_key(key):
            return match.group(0)      # runtime variable — leave for the orchestrator
        if key in context:
            return context[key]
        missing.append(key)
        return match.group(0)

    return PLACEHOLDER.sub(replace, text), missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="Report unresolved placeholders without writing.")
    parser.add_argument("--in-place", action="store_true",
                        help="Overwrite sources instead of writing to build/.")
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args()

    config_path = args.config
    if args.check and not config_path.is_file():
        config_path = EXAMPLE_CONFIG

    context = build_context(load_config(config_path))

    if not args.check and not args.in_place and BUILD.exists():
        shutil.rmtree(BUILD)

    rendered_count = 0
    unresolved: dict[str, list[str]] = {}

    for source in iter_source_files():
        text = source.read_text(encoding="utf-8")
        if "{{" not in text:
            continue
        output, missing = render(text, context)
        if missing:
            unresolved[str(source.relative_to(ROOT))] = sorted(set(missing))
        if args.check:
            continue
        target = source if args.in_place else BUILD / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(output, encoding="utf-8")
        rendered_count += 1

    if unresolved:
        print("Unresolved placeholders:\n")
        for filename, keys in sorted(unresolved.items()):
            print(f"  {filename}")
            for key in keys:
                print(f"      {{{{{key}}}}}")
        print("\nAdd these keys to your organization config.")
        return 1

    if args.check:
        print(f"All placeholders resolve against {config_path.name}.")
    else:
        destination = "sources (in place)" if args.in_place else "build/"
        print(f"Rendered {rendered_count} file(s) to {destination}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
