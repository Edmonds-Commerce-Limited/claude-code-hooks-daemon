r"""A newline ENDS a command, so no handler pattern may judge across one.

Plan 00406, graduated from Plan 00405 N8. Four blocking handlers matched a RAW
multi-line command with a negated separator class that omitted ``\n``
(``SUBCOMMAND_SEPARATOR_CHARS`` was ``";&|"``), or with a ``\s+`` sitting in
front of one. ``\s`` matches a newline, so both let a pattern step past the end
of its own command and convict the NEXT line.

**The control is what makes each of these a defect rather than a preference.**
Join the same two lines with ``&&`` instead of a newline and the verdict
reverses -- yet ``;``, ``&&`` and a newline are three spellings of one shell
structure, "run this, then that". Two spellings disagreeing is a fact about the
implementation, never about the policy, so every case below asserts BOTH
spellings and requires them to agree.

The opposite direction must stay closed, and it is asserted here too: a
``\<newline>`` line continuation is the one newline that is NOT a boundary --
the shell REMOVES it and joins the halves into a single word. Plan 00405 N7
closed that hole (``git pu\<newline>sh --force`` is a real force push), and a
naive "just stop matching newlines" fix would reopen it. That is also why
``daemon_location_guard`` had to be routed through ``get_bash_command`` BEFORE
its gap was tightened: it read ``tool_input`` directly, so it never saw the
normalisation that turns a continuation into one line.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.handlers.pre_tool_use.ancestry_preserving_merge import (
    AncestryPreservingMergeHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.daemon_location_guard import (
    DaemonLocationGuardHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import (
    DestructiveGitHandler,
)


def _bash(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


# Each row: handler factory, the FIRST line, the SECOND line, and the one-line
# command that must still be denied. The second line is always something a
# person would really type, and always innocent on its own.
_CROSS_LINE_CASES: list[tuple[str, type[Handler], str, str, str]] = [
    (
        "destructive_git push-force",
        DestructiveGitHandler,
        "git push origin main",
        # `-f` here is grep's, not git's.
        "grep -f patterns.txt notes.txt",
        "git push --force origin main",
    ),
    (
        "destructive_git update-ref",
        DestructiveGitHandler,
        "git update-ref refs/heads/backup HEAD",
        # The SAFE delete this project's own rules table prescribes over `-D`.
        "git branch -d refs/heads/old",
        "git update-ref -d refs/heads/old",
    ),
    (
        "ancestry_preserving_merge",
        AncestryPreservingMergeHandler,
        "git merge origin/main",
        "echo --squash is what we avoid",
        "git merge --squash origin/main",
    ),
    (
        "daemon_location_guard",
        DaemonLocationGuardHandler,
        # A bare `cd`, then the very command the guard's own deny message
        # tells the reader to run instead.
        "cd",
        ".claude/hooks-daemon/bin/hooks-daemon status",
        "cd .claude/hooks-daemon",
    ),
]


@pytest.mark.parametrize(
    ("label", "handler_cls", "first", "second", "genuine"),
    _CROSS_LINE_CASES,
    ids=[case[0] for case in _CROSS_LINE_CASES],
)
class TestANewlineEndsTheCommand:
    def test_a_newline_separated_pair_is_not_judged_as_one_command(
        self, label: str, handler_cls: type[Handler], first: str, second: str, genuine: str
    ) -> None:
        command = f"{first}\n{second}"

        assert handler_cls().matches(_bash(command)) is False, (
            f"{label}: denied {command!r}, but these are two commands and neither "
            f"is a violation on its own."
        )

    def test_the_ampersand_spelling_agrees_with_the_newline_spelling(
        self, label: str, handler_cls: type[Handler], first: str, second: str, genuine: str
    ) -> None:
        """The falsifying control: one shell structure, two spellings, one verdict."""
        newline_verdict = handler_cls().matches(_bash(f"{first}\n{second}"))
        ampersand_verdict = handler_cls().matches(_bash(f"{first} && {second}"))

        assert newline_verdict == ampersand_verdict, (
            f"{label}: `\\n` gave {newline_verdict} but `&&` gave {ampersand_verdict}. "
            f"They are the same shell structure, so a disagreement is an "
            f"implementation defect, not a policy choice."
        )

    def test_the_genuine_one_line_form_is_still_denied(
        self, label: str, handler_cls: type[Handler], first: str, second: str, genuine: str
    ) -> None:
        """Handlers fail CLOSED: narrowing the boundary must not open a hole."""
        assert handler_cls().matches(_bash(genuine)) is True, (
            f"{label}: stopped denying {genuine!r}, which is the real violation."
        )


class TestTheLineContinuationHoleStaysClosed:
    r"""A ``\<newline>`` is NOT a boundary -- the shell removes it (Plan 00405 N7)."""

    def test_a_split_force_flag_is_still_a_force_push(self) -> None:
        assert DestructiveGitHandler().matches(_bash("git push --fo\\\nrce origin main")) is True

    def test_a_split_cd_target_still_reaches_the_daemon_dir(self) -> None:
        assert DaemonLocationGuardHandler().matches(_bash("cd \\\n.claude/hooks-daemon")) is True

    def test_a_split_squash_flag_is_still_a_squash_merge(self) -> None:
        assert (
            AncestryPreservingMergeHandler().matches(_bash("git merge --squ\\\nash origin/main"))
            is True
        )
