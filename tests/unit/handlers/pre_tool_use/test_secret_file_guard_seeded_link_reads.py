"""A protected file seeded into a worktree as a link is still unreadable (Plan 00613 Task 3.1).

The owner approved linking a protected file into a worktree (Plan 00613 DESIGN,
Owner decision): the link reads nothing, and the file already exists on the
filesystem. What the approval does NOT change is the secret guard's reading
contract: the link is a new path to the same bytes, so every read through it
must be refused exactly as a read of the canonical file is.

These are DESIGN section 8 group C, run against a link the seeding executor
itself placed (``seed_worktree``), with the hook ``cwd`` inside the worktree,
which is where an agent working there stands.

Protected names are assembled from pieces so this file does not itself name a
protected path to the secret guard.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.indexed_project import index_project

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.worktree_seed import SEED_MODE_SYMLINK, SeedEntry
from claude_code_hooks_daemon.handlers.pre_tool_use import secret_file_guard as guard_module
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)
from claude_code_hooks_daemon.utils import protected_file_index
from claude_code_hooks_daemon.utils.worktree_seeding import LinkAudit, seed_worktree

VAULT = "." + "vault" + "-pass"
# Not dot-named, so a bare ``*`` glob in the linked directory really expands to it.
DB_SECRET = "db" + ".sec" + "ret"
_LINKED_DIR = "localconf"
_WORKTREE = ".claude/worktrees/alpha-1234abcd"


@pytest.fixture()
def worktree(tmp_path: Path) -> Iterator[Path]:
    """A main checkout whose protected file and a directory holding one are seeded as links."""
    root = tmp_path / "project"
    root.mkdir()
    (root / VAULT).write_bytes(b"not-a-real-secret\n")
    (root / _LINKED_DIR).mkdir()
    (root / _LINKED_DIR / VAULT).write_bytes(b"not-a-real-secret\n")
    (root / _LINKED_DIR / DB_SECRET).write_bytes(b"not-a-real-secret\n")
    tree = root / _WORKTREE
    tree.mkdir(parents=True)
    protected_file_index.reset_index_cache()
    with patch.object(guard_module, "resolve_project_root", return_value=str(root)):
        patterns = SecretFileGuardHandler()._patterns()
        placed = seed_worktree(
            root,
            tree,
            [
                SeedEntry(path=VAULT, mode=SEED_MODE_SYMLINK),
                SeedEntry(path=_LINKED_DIR, mode=SEED_MODE_SYMLINK),
            ],
            audit=LinkAudit(
                log_path=tmp_path / "audit.jsonl",
                protected_patterns=lambda: patterns,
                session_id=None,
            ),
        )
        assert [path.is_symlink() for path in placed] == [True, True]
        index_project(root, patterns)
        yield tree
    protected_file_index.reset_index_cache()


def _decision(cwd: Path, tool_name: str, tool_input: dict[str, Any]) -> Decision:
    hook_input: dict[str, Any] = {"tool_name": tool_name, "tool_input": tool_input, "cwd": str(cwd)}
    handler = SecretFileGuardHandler()
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


class TestToolReadsThroughTheSeededLinkAreDenied:
    def test_read_of_the_absolute_link_path(self, worktree: Path) -> None:
        assert _decision(worktree, "Read", {"file_path": str(worktree / VAULT)}) == Decision.DENY

    def test_read_of_a_protected_file_through_a_linked_directory(self, worktree: Path) -> None:
        target = worktree / _LINKED_DIR / VAULT
        assert _decision(worktree, "Read", {"file_path": str(target)}) == Decision.DENY

    def test_edit_through_the_link(self, worktree: Path) -> None:
        tool_input = {"file_path": str(worktree / VAULT), "old_string": "a", "new_string": "b"}
        assert _decision(worktree, "Edit", tool_input) == Decision.DENY

    def test_grep_tool_rooted_at_the_worktree(self, worktree: Path) -> None:
        tool_input = {"path": str(worktree), "pattern": "secret"}
        assert _decision(worktree, "Grep", tool_input) == Decision.DENY


class TestBashReadsThroughTheSeededLinkAreDenied:
    @pytest.mark.parametrize(
        "command",
        [
            f"cat {VAULT}",
            f"cat ./{VAULT}",
            f"cat < {VAULT}",
            f"python3 -c \"print(open('{VAULT}').read())\"",
            f"cp -L {VAULT} plain.txt",
            f"> {VAULT}",
            f"cat {_LINKED_DIR}/{VAULT}",
            f"cat {_LINKED_DIR}/{DB_SECRET}",
            f"cat {_LINKED_DIR}/*",
            f"cat {_LINKED_DIR}/db.*",
            f"cat {_LINKED_DIR}/.v*",
            "grep -r secret .",
            f"grep -r secret {_LINKED_DIR}",
        ],
    )
    def test_from_inside_the_worktree(self, worktree: Path, command: str) -> None:
        assert _decision(worktree, "Bash", {"command": command}) == Decision.DENY


class TestAnUnprotectedNeighbourStaysReadable:
    """Control: the denials above come from the protected link, not from the worktree."""

    def test_plain_file_in_the_worktree(self, worktree: Path) -> None:
        (worktree / "plain.txt").write_text("ordinary\n", encoding="utf-8")
        assert _decision(worktree, "Bash", {"command": "cat plain.txt"}) == Decision.ALLOW
