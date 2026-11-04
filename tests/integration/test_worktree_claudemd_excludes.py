"""Every worktree root the daemon creates must be excluded from CLAUDE.md loading.

A sub-agent rooted at the main checkout already loads the root CLAUDE.md. Its
first read inside a worktree would inject that worktree's copy of the same file
(Plan 00561, GitHub #156). ``claudeMdExcludes`` in ``.claude/settings.local.json``
prevents that, and this test fails when a worktree root has no matching glob.
"""

import json
import re
from pathlib import Path, PurePosixPath

import pytest

from claude_code_hooks_daemon.config_optimisation.claudemd_excludes import (
    KNOWN_WORKTREE_ROOTS,
    glob_to_regex,
)
from claude_code_hooks_daemon.core.worktree_naming import WORKTREES_SUBDIR

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = REPO_ROOT / ".claude" / "settings.local.json"
SETUP_SCRIPT = REPO_ROOT / "scripts" / "setup_worktree.sh"
EXAMPLE_PROJECT = PurePosixPath("/example/project")
EXAMPLE_WORKTREE = "worktree-example"

_SCRIPT_WORKTREES_DIR = re.compile(r'^WORKTREES_DIR="\$\{PROJECT_ROOT\}/(?P<rel>[^"]+)"$', re.M)


def _worktree_roots() -> dict[str, str]:
    """Return worktree root (relative to the project) per creating component."""
    match = _SCRIPT_WORKTREES_DIR.search(SETUP_SCRIPT.read_text())
    assert match is not None, f"WORKTREES_DIR not found in {SETUP_SCRIPT}"
    return {
        "scripts/setup_worktree.sh": match.group("rel"),
        "WorktreeCreate handler": WORKTREES_SUBDIR,
    }


def _excludes() -> list[str]:
    settings = json.loads(SETTINGS_PATH.read_text())
    excludes = settings.get("claudeMdExcludes", [])
    assert isinstance(excludes, list)
    return [str(entry) for entry in excludes]


@pytest.mark.parametrize("creator", sorted(_worktree_roots()))
def test_worktree_root_claude_md_is_excluded(creator: str) -> None:
    """The root CLAUDE.md copy in each daemon-created worktree matches an exclude glob."""
    root = _worktree_roots()[creator]
    target = str(EXAMPLE_PROJECT / root / EXAMPLE_WORKTREE / "CLAUDE.md")
    patterns = _excludes()
    assert any(glob_to_regex(p).match(target) for p in patterns), (
        f"{creator} creates worktrees under {root}/ but no claudeMdExcludes glob "
        f"in {SETTINGS_PATH.name} matches {target}; globs: {patterns}"
    )


def test_nested_claude_md_in_worktree_still_loads() -> None:
    """Only the worktree-root CLAUDE.md is excluded; nested ones keep loading."""
    for creator, root in _worktree_roots().items():
        nested = str(EXAMPLE_PROJECT / root / EXAMPLE_WORKTREE / "src" / "CLAUDE.md")
        assert not any(glob_to_regex(p).match(nested) for p in _excludes()), creator


def test_optimise_known_roots_match_the_creators() -> None:
    """The roots `optimise` checks are exactly the roots the daemon's creators use."""
    assert set(KNOWN_WORKTREE_ROOTS) == set(_worktree_roots().values())
