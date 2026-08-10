"""destructive_git must not be bypassable by git's GLOBAL options.

Every destructive pattern was anchored ``\\bgit\\s+<subcommand>``, which requires
the subcommand to follow ``git`` immediately. Git accepts global options before
the subcommand, so inserting one silently defeated the entire handler::

    git reset --hard origin/main        -> denied
    git -C /path reset --hard origin/main  -> ALLOWED

The same one-token insertion bypassed ``clean -f``, ``push --force`` and
``stash drop`` too — i.e. the whole safety handler, not one rule.

``--git-dir=/repo/.git reset --hard`` appeared to be caught, but only by
accident: the path ends in ``.git``, and ``\\bgit`` matched *inside the path*,
with ``\\s+reset`` matching immediately after it. Point it at a directory not
ending in ``.git`` and the block vanished. That near-miss is why these tests
assert against a path with no ``git`` substring anywhere in it — otherwise a
test can pass while the rule it claims to cover is doing nothing.

A safety handler must fail CLOSED. False positives here are explicitly
acceptable to this project (CLAUDE.md documents that blocking a commit message
containing a dangerous command is intended behaviour); silent bypasses are not.
"""

from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import (
    DestructiveGitHandler,
)

# Deliberately contains no "git" substring: a path like /repo/.git would let
# `\bgit` match inside the path and mask a broken rule.
_SAFE_PATH = "/srv/project"

# Real git global options, in the forms git actually accepts.
_GLOBAL_OPTION_PREFIXES = [
    f"-C {_SAFE_PATH}",
    "-c core.pager=cat",
    f"--git-dir={_SAFE_PATH}/.repo",
    f"--work-tree={_SAFE_PATH}",
    "--no-pager",
    f"--no-pager -C {_SAFE_PATH}",
]

# One representative command per destructive rule the handler owns.
_DESTRUCTIVE_SUBCOMMANDS = [
    "reset --hard origin/main",
    "clean -fd",
    "stash drop",
    "stash clear",
    "push --force origin main",
    "branch -D feature/old",
    "commit --amend -m x",
    "checkout HEAD -- src/app.py",
    "restore src/app.py",
]


def _bash(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def _denies(handler: DestructiveGitHandler, command: str) -> bool:
    hook_input = _bash(command)
    if not handler.matches(hook_input):
        return False
    return handler.handle(hook_input).decision == Decision.DENY


@pytest.fixture
def handler() -> DestructiveGitHandler:
    return DestructiveGitHandler()


class TestBareFormsStillBlocked:
    """Baseline: without a global option, every rule already worked."""

    @pytest.mark.parametrize("subcommand", _DESTRUCTIVE_SUBCOMMANDS)
    def test_bare_form_is_denied(self, handler: DestructiveGitHandler, subcommand: str) -> None:
        assert _denies(handler, f"git {subcommand}") is True


class TestGlobalOptionsCannotBypass:
    """A global option before the subcommand must not defeat the rule."""

    @pytest.mark.parametrize("subcommand", _DESTRUCTIVE_SUBCOMMANDS)
    @pytest.mark.parametrize("prefix", _GLOBAL_OPTION_PREFIXES)
    def test_global_option_still_denied(
        self, handler: DestructiveGitHandler, prefix: str, subcommand: str
    ) -> None:
        command = f"git {prefix} {subcommand}"

        assert _denies(handler, command) is True, (
            f"BYPASS: {command!r} was allowed. Git global options may precede "
            "the subcommand, so every destructive pattern must tolerate them."
        )

    def test_git_dir_rule_is_not_passing_by_accident(self, handler: DestructiveGitHandler) -> None:
        """Pin the near-miss: a --git-dir path with no 'git' substring in it.

        The original pattern only caught this form when the path happened to
        end in `.git`, because `\\bgit` matched inside the PATH.
        """
        command = "git --git-dir=/srv/project/.repo reset --hard HEAD"

        assert _denies(handler, command) is True


class TestSafeCommandsStillAllowed:
    """Widening the prefix must not start blocking safe git usage."""

    @pytest.mark.parametrize(
        "command",
        [
            "git status",
            f"git -C {_SAFE_PATH} status --porcelain",
            f"git -C {_SAFE_PATH} log --oneline -n 5",
            "git branch -d merged-feature",
            f"git -C {_SAFE_PATH} branch -d merged-feature",
            "git restore --staged src/app.py",
            f"git -C {_SAFE_PATH} restore --staged src/app.py",
            "git restore -S src/app.py",
            "git stash list",
            f"git -C {_SAFE_PATH} stash list",
            "git stash show",
            "git push origin main",
            f"git -C {_SAFE_PATH} push origin main",
            "git commit -m 'ordinary commit'",
            f"git -C {_SAFE_PATH} fetch --tags --force",
            "git diff HEAD",
        ],
    )
    def test_safe_command_is_not_denied(self, handler: DestructiveGitHandler, command: str) -> None:
        assert (
            _denies(handler, command) is False
        ), f"FALSE POSITIVE: {command!r} is safe but was blocked."

    def test_subcommand_named_in_a_path_is_not_a_subcommand(
        self, handler: DestructiveGitHandler
    ) -> None:
        """A widened prefix must not match a word that merely appears later."""
        assert _denies(handler, "git show HEAD:scripts/reset --hard-notes") is False
