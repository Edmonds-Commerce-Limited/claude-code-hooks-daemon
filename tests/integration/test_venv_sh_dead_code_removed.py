"""Plan 00100 Task 1.2: venv.sh dead code removal.

venv.sh historically exported two functions — `create_venv()` and
`recreate_venv()` — that wrote to the legacy `untracked/venv/` path.
Task 0.1 identified both as dead (zero production callers). Task 1.1
confirmed the classification. This test guards the deletion so the
functions cannot be re-added by accident.

The live function is `create_venv_at_path()` — this test must not
fire on substring matches for that name.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_SH = REPO_ROOT / "scripts" / "install" / "venv.sh"
TEST_VENV_MANUAL_SH = REPO_ROOT / "scripts" / "install" / "test_venv_manual.sh"


def test_create_venv_function_definition_removed() -> None:
    """`create_venv()` (NOT `create_venv_at_path()`) must not be defined."""
    content = VENV_SH.read_text()
    # Match `create_venv()` or `create_venv ()` at the start of a function def.
    # Exclude `create_venv_at_path`.
    pattern = re.compile(r"^create_venv\s*\(\s*\)\s*\{", re.MULTILINE)
    matches = pattern.findall(content)
    assert not matches, (
        f"create_venv() function still defined in venv.sh. "
        f"Plan 00100 Task 1.2 requires its deletion. Found: {matches}"
    )


def test_recreate_venv_function_definition_removed() -> None:
    """`recreate_venv()` must not be defined in venv.sh."""
    content = VENV_SH.read_text()
    pattern = re.compile(r"^recreate_venv\s*\(\s*\)\s*\{", re.MULTILINE)
    matches = pattern.findall(content)
    assert not matches, (
        f"recreate_venv() function still defined in venv.sh. "
        f"Plan 00100 Task 1.2 requires its deletion. Found: {matches}"
    )


def test_manual_venv_test_script_removed() -> None:
    """`scripts/install/test_venv_manual.sh` tested the dead functions and
    must be deleted (Plan 00100 Task 1.2)."""
    assert not TEST_VENV_MANUAL_SH.exists(), (
        f"{TEST_VENV_MANUAL_SH} still exists. Plan 00100 Task 1.2 "
        f"requires its deletion — it exercised the removed "
        f"create_venv/recreate_venv functions."
    )


def test_create_venv_at_path_still_defined() -> None:
    """Guard: create_venv_at_path() is the LIVE function and must remain.

    This test ensures we didn't over-delete during Task 1.2.
    """
    content = VENV_SH.read_text()
    pattern = re.compile(r"^create_venv_at_path\s*\(\s*\)\s*\{", re.MULTILINE)
    assert pattern.search(content), (
        "create_venv_at_path() function definition is missing from venv.sh. "
        "This is the LIVE function — Task 1.2 must not delete it."
    )


def test_ensure_venv_still_defined() -> None:
    """Guard: ensure_venv() is the public entry point and must remain."""
    content = VENV_SH.read_text()
    pattern = re.compile(r"^ensure_venv\s*\(\s*\)\s*\{", re.MULTILINE)
    assert pattern.search(content), (
        "ensure_venv() function definition is missing from venv.sh. "
        "This is the public entry point — Task 1.2 must not delete it."
    )
