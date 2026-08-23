#!/usr/bin/env python3
"""Fail if any organization-specific value is hardcoded outside config/.

Prevents the defect this project started with: a fictional company's name and
email addresses baked into 27 files, so adopting the project meant a
find-and-replace with no config to change.

    python tools/check_branding.py

Run it in CI. Exit code 0 = clean, 1 = hardcoded values found.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Directories that legitimately contain concrete values.
SKIP_DIRS = {".git", "build", "node_modules", ".venv", "venv", "data"}
SKIP_PATHS = {
    "config/organization.yaml",
    "config/organization.example.yaml",
    "tools/check_branding.py",
    "tools/legacy/generate.py",
    "tools/legacy/_create_docx_samples.py",
    # Root stubs whose docstrings *describe* the hardcoded path as the reason
    # the originals were retired. They do not use it.
    "generate.py",
    "_create_docx_samples.py",
    "CHANGELOG.md",
    "CLAUDE.md",
    "LICENSE",
}

SCAN_SUFFIXES = {".md", ".json", ".py", ".yaml", ".yml", ".html", ".jinja"}

BANNED = [
    (re.compile(r"\bContoso\b", re.I), "Fictional company name — use {{org.legal_name}}"),
    (re.compile(r"\bcontoso\.com\b", re.I), "Fictional domain — use {{org.email_domain}}"),
    (re.compile(r"recruitment\.example\.com"),
     "Hardcoded schema host — use {{org.schema_base_url}}"),
    (re.compile(r"@company\.com\b"), "Placeholder domain — use {{org.email_domain}}"),
]

# Values that must come from config rather than being written inline.
SUSPICIOUS = [
    (re.compile(r"C:\\\\?AI-Recruitment-System"), "Hardcoded absolute path"),
]


def should_scan(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in SKIP_DIRS for part in relative.parts):
        return False
    if relative.as_posix() in SKIP_PATHS:
        return False
    return path.suffix in SCAN_SUFFIXES


def main() -> int:
    findings: list[tuple[str, int, str, str]] = []

    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or not should_scan(path):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        relative = path.relative_to(ROOT).as_posix()
        for number, line in enumerate(lines, start=1):
            for pattern, reason in BANNED + SUSPICIOUS:
                if pattern.search(line):
                    findings.append((relative, number, line.strip()[:96], reason))

    if not findings:
        print("Branding check passed — no organization-specific values outside config/.")
        return 0

    print(f"Branding check FAILED — {len(findings)} hardcoded value(s):\n")
    current = ""
    for filename, number, snippet, reason in findings:
        if filename != current:
            print(f"  {filename}")
            current = filename
        print(f"      line {number}: {snippet}")
        print(f"      -> {reason}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
