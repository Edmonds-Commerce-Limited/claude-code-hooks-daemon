"""git_stash and destructive_git judge COMMAND position, not quoted text (ledger N241, N200).

Governing ruling: CLAUDE/ARCHITECTURE.md, "Threat model: the agent is careless,
not hostile". A false positive on ordinary work is fixed by narrowing the
matcher; a literal `bash -c '...'` body stays in scope.

The command strings here are written in this file rather than typed on a Bash
command line, because a live guard would deny the command line that carries
them.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import DestructiveGitHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.git_stash import GitStashHandler


@pytest.fixture(autouse=True)
def _fresh_data_layer() -> Any:
    reset_data_layer()
    yield
    reset_data_layer()


def _input(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


#: Ordinary commands that only MENTION a guarded command. None may be denied.
_PROSE_COMMANDS = [
    "git commit -m 'document the git stash guard'",
    "grep -n 'git stash' CLAUDE/ARCHITECTURE.md",
    "cat > notes.md <<'EOF'\nnever run git stash\nEOF",
    "echo 'do not run git reset --hard'",
    "gh pr create --title x --body 'we ban git stash and git reset --hard'",
    "bash -c 'git commit -m \"document --amend\"'",
    "git commit -m 'mention git reset --hard and git commit --amend'",
    "printf '%s\\n' 'git stash is banned' > notes.txt",
    "echo 'git stash' && git status",
    "grep -rn 'git reset --hard' docs/ | wc -l",
    "gh issue create --title 'git stash bug' --body 'git stash drops work'",
]


class TestProseIsNotDenied:
    """Text in argument position is not a command in command position."""

    @pytest.mark.parametrize("command", _PROSE_COMMANDS)
    def test_git_stash_allows(self, command: str) -> None:
        assert GitStashHandler().matches(_input(command)) is False

    @pytest.mark.parametrize("command", _PROSE_COMMANDS)
    def test_destructive_git_allows(self, command: str) -> None:
        assert DestructiveGitHandler().matches(_input(command)) is False


#: Real commands, which must keep being denied.
_STASH_COMMANDS = [
    "git stash",
    "git stash push",
    "git stash push -m 'wip'",
    "bash -c 'git stash'",
    "bash -c 'git stash list; git stash'",
    "git stash list; git stash",
    "git stash list && git stash push",
    "git stash pop && git stash",
    "echo hi; git stash",
    "echo hi & git stash",
    "echo hi | git stash",
    "git status && git stash",
    "echo 'git stash' | bash",
    "echo 'git stash' | sh",
    "sudo git stash",
]

_RESET_COMMANDS = [
    "git reset --hard",
    "bash -c 'git reset --hard'",
    "git commit -m 'x' ; git reset --hard",
    "echo hi; git reset --hard HEAD~1",
    "git commit --amend",
    "bash -c 'git commit --amend'",
    "echo 'git reset --hard' | bash",
    # bash ends a single-quoted message at the next quote: a backslash does
    # not escape inside single quotes, so `git reset --hard` runs (N241).
    "git commit -m 'x\\' ; git reset --hard ; echo 'y'",
]


class TestRealCommandsAreStillDenied:
    @pytest.mark.parametrize("command", _STASH_COMMANDS)
    def test_git_stash_denies(self, command: str) -> None:
        assert GitStashHandler().matches(_input(command)) is True

    @pytest.mark.parametrize("command", _RESET_COMMANDS)
    def test_destructive_git_denies(self, command: str) -> None:
        assert DestructiveGitHandler().matches(_input(command)) is True


class TestRecoveryInOneSegmentDoesNotExemptAnother:
    """N200: judge each command segment on its own."""

    @pytest.mark.parametrize(
        "command",
        [
            "git stash list; git stash",
            "git stash list && git stash push",
            "git stash show || git stash",
        ],
    )
    def test_a_stash_after_a_recovery_form_is_denied(self, command: str) -> None:
        assert GitStashHandler().matches(_input(command)) is True

    @pytest.mark.parametrize(
        "command",
        [
            "git stash list",
            "git stash pop",
            "git stash apply && git stash list",
            "git stash list; git status",
        ],
    )
    def test_recovery_forms_alone_are_allowed(self, command: str) -> None:
        assert GitStashHandler().matches(_input(command)) is False

    def test_the_escape_hatch_still_passes_a_stash(self) -> None:
        command = 'MUST_STASH_BECAUSE="commit cannot work"; git stash'
        assert GitStashHandler().matches(_input(command)) is False
