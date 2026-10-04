"""A ``for`` word list of ``dir/*`` globs is judged word by word, as written.

Ledger 00474 N350: ``cd untracked; for d in repos/* worktrees/*; do git -C "$d"
ls-files; done`` was reported denied on a lone ``*``. The working directory the
``cd`` sets holds a protected file; none of the loop words reaches one.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use import secret_file_guard as guard_module
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)

# Assembled so this file never spells a protected name itself.
_SUFFIX = "sec" + "ret"
_PROTECTED = f"key.{_SUFFIX}"

_LOOP = 'for d in repos/* worktrees/* fd-worktrees/*; do git -C "$d" ls-files; done'


@pytest.fixture()
def project(tmp_path: Path) -> Iterator[Path]:
    """A project whose ``untracked`` directory holds a protected file beside the loop's roots."""
    root = tmp_path / "project"
    store = root / "untracked"
    for parent in ("repos", "worktrees", "fd-worktrees"):
        (store / parent / "one").mkdir(parents=True)
        (store / parent / "one" / "plain.txt").write_bytes(b"hello\n")
    (store / _PROTECTED).write_bytes(b"not-a-real-secret\n")
    with patch.object(guard_module, "resolve_project_root", return_value=str(root)):
        yield root


def _verdict(root: Path, command: str, cwd: Path | None = None) -> Decision:
    hook_input: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd or root),
    }
    handler = SecretFileGuardHandler()
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


class TestForLoopGlobWordList:
    """N350."""

    def test_loop_after_cd_into_a_directory_holding_a_protected_file_is_allowed(
        self, project: Path
    ) -> None:
        assert _verdict(project, f"cd untracked; {_LOOP}") == Decision.ALLOW

    def test_loop_run_from_inside_that_directory_is_allowed(self, project: Path) -> None:
        assert _verdict(project, _LOOP, cwd=project / "untracked") == Decision.ALLOW

    def test_loop_from_the_project_root_is_allowed(self, project: Path) -> None:
        assert _verdict(project, _LOOP.replace("repos/", "untracked/repos/")) == Decision.ALLOW

    def test_loop_with_the_cd_joined_by_and_is_allowed(self, project: Path) -> None:
        assert _verdict(project, f"cd untracked && {_LOOP}") == Decision.ALLOW

    def test_a_loop_word_that_reaches_a_protected_file_is_denied(self, project: Path) -> None:
        command = 'cd untracked; for d in repos/* ./*; do cat "$d"; done'
        assert _verdict(project, command) == Decision.DENY

    def test_a_loop_word_naming_a_protected_file_is_denied(self, project: Path) -> None:
        command = f'cd untracked; for f in {_PROTECTED}; do cat "$f"; done'
        assert _verdict(project, command) == Decision.DENY

    def test_a_variable_the_loop_does_not_bind_is_still_denied_in_a_protected_directory(
        self, project: Path
    ) -> None:
        command = 'cd untracked; for d in repos/*; do cat "$other"; done'
        assert _verdict(project, command) == Decision.DENY

    def test_a_reassigned_loop_variable_is_still_denied_in_a_protected_directory(
        self, project: Path
    ) -> None:
        command = 'cd untracked; for d in repos/*; do d=$(pwd); cat "$d"; done'
        assert _verdict(project, command) == Decision.DENY

    def test_a_bare_star_loop_word_in_a_protected_directory_is_denied(
        self, project: Path
    ) -> None:
        assert _verdict(project, "cd untracked; for f in *; do cat $f; done") == Decision.DENY
