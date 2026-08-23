"""Packaging guard.

A dependency that the code imports but pyproject.toml does not declare works
fine on a developer machine that happens to have it, and fails on a fresh
install with `ModuleNotFoundError`. That is exactly what happened between
Phase 3.4 and 3.5: sqlalchemy was silently dropped from the manifest and the
console would not start on a clean checkout.

This test walks every import in src/ and asserts it is either stdlib, first
party, or declared as a dependency (core or optional).
"""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "recruit"
PYPROJECT = ROOT / "pyproject.toml"

# Import name -> distribution name, where they differ.
IMPORT_TO_DISTRIBUTION = {
    "yaml": "pyyaml",
    "docx": "python-docx",
    "dotenv": "python-dotenv",
    "pdf2image": "pdf2image",
    "multipart": "python-multipart",
    "psycopg": "psycopg",
    "jose": "python-jose",
}


def declared_distributions() -> set[str]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = data["project"]
    names: set[str] = set()
    groups = [project.get("dependencies", [])]
    groups.extend(project.get("optional-dependencies", {}).values())
    for group in groups:
        for requirement in group:
            name = requirement.split(";")[0].strip()
            for separator in (">=", "==", "<=", "~=", ">", "<", "["):
                name = name.split(separator)[0]
            names.add(name.strip().lower().replace("_", "-"))
    return names


def third_party_imports() -> dict[str, set[str]]:
    """Top-level imported module -> the files that import it."""
    found: dict[str, set[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:          # relative import — first party
                    continue
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                top = module.split(".")[0]
                if not top or top == "recruit":
                    continue
                if top in sys.stdlib_module_names:
                    continue
                found.setdefault(top, set()).add(
                    str(path.relative_to(ROOT).as_posix())
                )
    return found


def test_every_import_is_declared():
    declared = declared_distributions()
    missing: dict[str, set[str]] = {}
    for module, files in third_party_imports().items():
        distribution = IMPORT_TO_DISTRIBUTION.get(module, module)
        if distribution.lower().replace("_", "-") not in declared:
            missing[f"{module} (-> {distribution})"] = files

    assert not missing, (
        "Imported but not declared in pyproject.toml:\n"
        + "\n".join(f"  {name}: imported by {', '.join(sorted(files))}"
                    for name, files in sorted(missing.items()))
        + "\n\nA fresh `pip install -e .` would fail with ModuleNotFoundError."
    )


def test_console_scripts_point_at_real_callables():
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    scripts = data["project"].get("scripts", {})
    assert scripts, "No console scripts declared"
    for name, target in scripts.items():
        module_path, _, attribute = target.partition(":")
        relative = module_path.replace("recruit.", "", 1).replace(".", "/")
        candidates = [SRC / f"{relative}.py", SRC / relative / "__init__.py"]
        assert any(c.is_file() for c in candidates), f"{name}: no module {module_path}"
        source = next(c for c in candidates if c.is_file()).read_text(encoding="utf-8")
        assert f"def {attribute}(" in source, f"{name}: {module_path} has no {attribute}()"


def test_core_dependencies_cover_the_default_pipeline():
    """ingest -> extract -> validate -> persist must work from `pip install -e .`
    alone, with no extras. Only the web console and Postgres are optional."""
    declared = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["dependencies"]
    core = {r.split(">=")[0].split("[")[0].strip().lower() for r in declared}
    for required in ("pyyaml", "jsonschema", "pypdf", "python-docx",
                     "rapidfuzz", "sqlalchemy"):
        assert required in core, f"{required} must be a core dependency"


# -- zero-infrastructure default ----------------------------------------------
def test_default_database_url_needs_no_server_or_driver():
    """`pip install -e .` -> seed -> web must work with nothing else installed.

    Postgres is the production target, but making it the DEFAULT means a fresh
    install dies on `ModuleNotFoundError: psycopg` before it shows anything.
    """
    from recruit.db.session import DEFAULT_URL
    assert DEFAULT_URL.startswith("sqlite:"), DEFAULT_URL

    import yaml
    example = yaml.safe_load(
        (ROOT / "config" / "organization.example.yaml").read_text(encoding="utf-8"))
    configured = example["adapters"]["database"]["url"]
    assert configured.startswith("sqlite:"), (
        f"The shipped config defaults to {configured!r}, which needs a driver "
        "that core dependencies do not install."
    )


def test_missing_driver_explains_how_to_fix_it():
    """A bare ModuleNotFoundError tells an operator nothing actionable."""
    import pytest

    from recruit.db.session import DatabaseDriverMissing, create_engine_from_config

    try:
        import psycopg  # noqa: F401
        pytest.skip("psycopg is installed; the failure path cannot be exercised")
    except ImportError:
        pass

    with pytest.raises(DatabaseDriverMissing) as error:
        create_engine_from_config(url="postgresql+psycopg://u:p@localhost:5432/db")
    message = str(error.value)
    assert "postgres" in message.lower()
    assert "pip install" in message
    assert "sqlite" in message.lower()

