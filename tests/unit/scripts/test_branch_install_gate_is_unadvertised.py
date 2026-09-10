"""Plan 00291 — the branch-install gate stays out of the user-facing documents.

The owner ruling makes the mechanism "guarded and non obvious". The only
place its variable names may be written down is the plan's own design note
and the code that implements it. This test fails the moment either name
reaches a document a client reads.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

_GATE_NAMES: Final[tuple[str, ...]] = (
    "HOOKS_DAEMON_UNSAFE_TRACK_REF",
    "HOOKS_DAEMON_UNSAFE_TRACK_REF_BECAUSE",
)

_USER_FACING_FILES: Final[tuple[str, ...]] = (
    "CLAUDE/LLM-INSTALL.md",
    "CLAUDE/LLM-UPDATE.md",
    "README.md",
    ".claude/HOOKS-DAEMON.md",
    "CLAUDE/UPGRADES/README.md",
    "scripts/install/README.md",
)


@pytest.mark.parametrize("relative", _USER_FACING_FILES)
def test_user_facing_document_does_not_name_the_gate(relative: str) -> None:
    path = _REPO_ROOT / relative
    assert path.is_file(), f"expected {relative} to exist"
    text = path.read_text(encoding="utf-8")
    for name in _GATE_NAMES:
        assert name not in text, f"{relative} names the branch-install gate ({name})"


def test_human_docs_tree_does_not_name_the_gate() -> None:
    offenders = [
        str(md.relative_to(_REPO_ROOT))
        for md in (_REPO_ROOT / "docs").rglob("*.md")
        if any(name in md.read_text(encoding="utf-8") for name in _GATE_NAMES)
    ]
    assert not offenders, f"docs/ names the branch-install gate: {offenders}"


def test_release_notes_callouts_do_not_name_the_gate() -> None:
    callouts = _REPO_ROOT / "CLAUDE" / "UPGRADES" / "UNRELEASED" / "release-notes"
    offenders = [
        md.name
        for md in callouts.glob("*.md")
        if any(name in md.read_text(encoding="utf-8") for name in _GATE_NAMES)
    ]
    assert not offenders, f"release-notes callouts name the branch-install gate: {offenders}"


def test_no_handler_guidance_names_the_gate() -> None:
    """The generated HOOKS-DAEMON.md is built from handler guidance strings."""
    handlers = _REPO_ROOT / "src" / "claude_code_hooks_daemon" / "handlers"
    offenders = [
        str(py.relative_to(_REPO_ROOT))
        for py in handlers.rglob("*.py")
        if any(name in py.read_text(encoding="utf-8") for name in _GATE_NAMES)
    ]
    assert not offenders, f"handler source names the branch-install gate: {offenders}"
