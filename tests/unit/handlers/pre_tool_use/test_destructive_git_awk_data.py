"""Git text inside a quoted awk program is data, not a removal (GitHub #170, Plan 00478 Phase 0).

``printf 'x\\n' | awk '{print "git worktree remove " $1}'`` runs no git: the text is a
string in a single-quoted awk program, and ``$1`` is awk's field, not a shell
expansion. The guard's raw-text patterns still saw ``git worktree remove`` there
(the ``$`` kept the program from being blanked), the parser read no removal, and
the fail-closed "unreadable" branch denied.

Every allow below has an EXECUTING twin that must still be denied.
"""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import DestructiveGitHandler

_PRINT = "awk '{print \"git worktree remove \" $1}'"
_FEED = "printf 'untracked/scratch/x\\n' | "


def _event(command: str, cwd: Path) -> dict[str, object]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


def _allowed(command: str, cwd: Path) -> bool:
    handler = DestructiveGitHandler()
    event = _event(command, cwd)
    return (not handler.matches(event)) or handler.handle(event).decision == Decision.ALLOW


class TestGitTextPrintedByAwkIsData:
    @pytest.mark.parametrize(
        "command",
        [
            _FEED + _PRINT,
            _FEED + "awk -F: '{print \"git worktree remove \" $1}'",
            _FEED + "awk '{printf \"git worktree remove %s\\n\", $1}'",
            _FEED + "awk '{print \"git branch -D \" $1}'",
            _FEED + "awk '{printf \"git branch -D %s\\n\", $1}'",
            "awk 'BEGIN{print \"git worktree remove untracked/scratch/x\"}'",
            'echo "git worktree remove x"',
            "echo 'git branch -D x'",
        ],
    )
    def test_it_is_allowed(self, command: str, tmp_path: Path) -> None:
        assert _allowed(command, tmp_path)


class TestAnythingThatMayRunTheTextStillDenies:
    @pytest.mark.parametrize(
        "command",
        [
            _FEED + _PRINT + " | sh",
            _FEED + _PRINT + " | bash",
            _FEED + _PRINT + " |& sh",
            _FEED + _PRINT + " | xargs -I{} sh -c '{}'",
            'eval "$(' + _FEED + _PRINT + ')"',
            "source <(" + _FEED + _PRINT + ")",
            'bash -c "$(' + _FEED + _PRINT + ')"',
            "$(" + _FEED + _PRINT + ")",
            _FEED + "awk '{print \"git worktree remove \" $1 | \"sh\"}'",
            _FEED + "awk '{system(\"git worktree remove \" $1)}'",
            _FEED + "awk '{print \"git branch -D \" $1}' | sh",
            _FEED + _PRINT + " > s.sh && sh s.sh",
            _FEED + "awk '{print \"git worktree remove \" $(1)}' | sh",
            _FEED + "awk '{print \"git worktree remove \" $1 > \"s.sh\"}'; sh s.sh",
        ],
    )
    def test_it_is_still_denied(self, command: str, tmp_path: Path) -> None:
        assert not _allowed(command, tmp_path)

    def test_a_real_removal_beside_the_awk_print_denies_on_the_removal(self, tmp_path: Path) -> None:
        command = "git worktree remove /nonexistent/dirty; " + _FEED + _PRINT
        handler = DestructiveGitHandler()
        result = handler.handle(_event(command, tmp_path))
        assert result.decision == Decision.DENY
