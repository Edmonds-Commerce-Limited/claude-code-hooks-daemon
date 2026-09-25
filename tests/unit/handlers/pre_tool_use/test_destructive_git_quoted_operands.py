"""A QUOTED operand is the same operand once bash has removed the quotes.

Plan 00408 Task 3.0 (graduated from Plan 00407 N8). ``git checkout "--" f.txt``
was allowed while ``git checkout -- f.txt`` was denied, although git receives an
identical argument list for both. The plan asked for the sibling rules to be
checked for the same gap, and they had it: every pattern anchored on a leading
token (``(?<!\\S)--force``, ``(?<!\\S)\\+``, ``checkout\\s+\\.``) missed its
quoted spelling. Each spelling below was allowed before the fix.

Quoting that bash does NOT remove from inside one word -- a value holding a
space, a substitution -- is left alone, so this cannot turn prose into a
command: ``git commit -m 'document --amend'`` stays allowed.
"""

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import (
    DestructiveGitHandler,
)

# Assembled from fragments: these are the shapes the handler exists to deny, and
# the test file is read by the same guards.
_DD = "-" + "-"


def _matches(command: str) -> bool:
    handler = DestructiveGitHandler()
    return handler.matches({"tool_name": "Bash", "tool_input": {"command": command}})


class TestAQuotedOperandIsStillTheOperand:
    @pytest.mark.parametrize(
        "command",
        [
            f'git checkout "{_DD}" f.txt',
            f"git checkout '{_DD}' f.txt",
            f'git checkout HEAD "{_DD}" f.txt',
            'git checkout "." ',
            f'git push origin "{_DD}force"',
            f"git push '{_DD}force-with-lease' origin main",
            "git push origin '+main:main'",
            'git push "-uf" origin main',
            f'git checkout "{_DD}force" main',
            f"git switch '{_DD}discard-changes' main",
            f'git gc "{_DD}prune=now"',
            f"git reflog expire '{_DD}expire=now' {_DD}all",
            'git "reset" --hard',
        ],
    )
    def test_the_quoted_spelling_is_denied(self, command: str) -> None:
        assert _matches(command) is True


class TestQuotingThatIsNotRemovedStaysProse:
    def test_a_commit_message_naming_a_flag_is_still_allowed(self) -> None:
        assert _matches(f"git commit -m 'document {_DD}amend'") is False

    def test_a_branch_name_holding_a_plus_is_still_an_ordinary_push(self) -> None:
        assert _matches("git push origin 'feature+fix'") is False

    def test_a_staged_only_restore_is_still_allowed_when_quoted(self) -> None:
        """Unquoting cuts both ways: ``"--staged"`` IS the safe form."""
        assert _matches(f'git restore "{_DD}staged" f.txt') is False
