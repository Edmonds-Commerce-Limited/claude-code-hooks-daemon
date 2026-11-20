"""A hand-typed link or copy of a protected file stays denied (Plan 00613 Task 2.3).

Plan 00613 ruled that a worktree link to a protected file is acceptable only by
a route a human owns (project config, or a command the human types), never by a
route an agent can invoke. Nothing in that plan loosens ``R-SECRET-BASH-MENTION``:
an agent's ``ln -s``, ``ln`` or ``cp`` naming a protected path, including one
aimed into a registered worktree, is denied exactly as before.

This is a PIN, not a red-first test: it passes on the guard as shipped, and can
only be seen failing by breaking the guard. Its job is to fail if a later change
(a verb, an exemption, a worktree special case) opens any of these shapes.

Protected names are assembled from pieces so this file does not itself name a
protected path to the secret guard.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.indexed_project import index_project

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use import secret_file_guard as guard_module
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)
from claude_code_hooks_daemon.utils import protected_file_index

VAULT = "." + "vault" + "-pass"
_WORKTREE = ".claude/worktrees/alpha-1234abcd"
_UP = "../../.."


@pytest.fixture()
def project(tmp_path: Path) -> Iterator[Path]:
    """A main checkout holding a protected file and one worktree directory."""
    root = tmp_path / "project"
    root.mkdir()
    (root / VAULT).write_bytes(b"not-a-real-secret\n")
    (root / _WORKTREE).mkdir(parents=True)
    protected_file_index.reset_index_cache()
    with patch.object(guard_module, "resolve_project_root", return_value=str(root)):
        index_project(root, SecretFileGuardHandler()._patterns())
        yield root
    protected_file_index.reset_index_cache()


def _result(cwd: Path, command: str) -> tuple[Decision, str]:
    hook_input: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }
    handler = SecretFileGuardHandler()
    if not handler.matches(hook_input):
        return Decision.ALLOW, ""
    result = handler.handle(hook_input)
    return result.decision, result.reason or ""


_FROM_ROOT = [
    f"ln -s {_UP}/{VAULT} {_WORKTREE}/{VAULT}",
    f"ln -s $PWD/{VAULT} {_WORKTREE}/{VAULT}",
    f"ln -sf {_UP}/{VAULT} {_WORKTREE}/{VAULT}",
    f"ln -sr {VAULT} {_WORKTREE}/{VAULT}",
    f"ln {VAULT} {_WORKTREE}/{VAULT}",
    f"ln {VAULT} {_WORKTREE}/plain-name",
    f"ln -s {VAULT} {_WORKTREE}/",
    f"cp {VAULT} {_WORKTREE}/{VAULT}",
    f"cp {VAULT} {_WORKTREE}/",
    f"cp -p {VAULT} {_WORKTREE}/plain-name",
    f"cp -L {VAULT} {_WORKTREE}/plain-name",
    f"cp --preserve=all {VAULT} {_WORKTREE}/",
]

_FROM_WORKTREE = [
    f"ln -s {_UP}/{VAULT} {VAULT}",
    f"ln -s {_UP}/{VAULT} plain-name",
    f"ln {_UP}/{VAULT} plain-name",
    f"cp {_UP}/{VAULT} .",
    f"cp {_UP}/{VAULT} plain-name",
]


class TestAHandTypedLinkOrCopyIsDenied:
    @pytest.mark.parametrize("command", _FROM_ROOT)
    def test_from_the_main_checkout(self, project: Path, command: str) -> None:
        decision, reason = _result(project, command)
        assert decision == Decision.DENY
        assert RuleID.SECRET_BASH_MENTION in reason

    @pytest.mark.parametrize("command", _FROM_WORKTREE)
    def test_from_inside_the_worktree(self, project: Path, command: str) -> None:
        decision, reason = _result(project / _WORKTREE, command)
        assert decision == Decision.DENY
        assert RuleID.SECRET_BASH_MENTION in reason

    @pytest.mark.parametrize(
        "command",
        [
            f"cd {_WORKTREE} && ln -s {_UP}/{VAULT} {VAULT}",
            f"true; cp {VAULT} {_WORKTREE}/",
            f"ln -s {_UP}/{VAULT} {_WORKTREE}/{VAULT} || echo failed",
        ],
    )
    def test_chained_with_another_command(self, project: Path, command: str) -> None:
        decision, reason = _result(project, command)
        assert decision == Decision.DENY
        assert RuleID.SECRET_BASH_MENTION in reason
