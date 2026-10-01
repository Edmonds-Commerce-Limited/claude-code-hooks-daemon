"""Text that is not a pipe is never judged as one (ledger 00474 N284).

`grep -rn "HEAD:x\\|rev:path\\|HEAD:<p>" a/ b.md | cut -c1-200` was denied as a
pipe to `head`, with the quoted pattern named as the producer. Two defects met:

- the pipe pattern matched `head` case-insensitively, so the `HEAD` of a git
  revision read as the `head` command (a Linux command word is case-sensitive)
- the pattern did not know a backslash-escaped bar is a literal character: in
  double quotes `\\|` is two characters, and unquoted `\\|` is one escaped
  character, so neither is the shell's pipe

Real pipes are untouched: command substitution inside double quotes executes,
so a pipe there is still judged on its own producer.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker() -> Any:
    reset_data_layer()
    yield
    reset_data_layer()


@pytest.fixture
def handler() -> PipeBlockerHandler:
    return PipeBlockerHandler()


def _bash(command: str) -> dict[str, Any]:
    return {"tool_name": ToolName.BASH, "tool_input": {"command": command}}


class TestTheFieldReport:
    def test_an_alternation_with_a_revision_word_is_allowed(
        self, handler: PipeBlockerHandler
    ) -> None:
        command = (
            'grep -rn "HEAD:notes.txt\\|rev:path\\|HEAD:<protected>" '
            "CLAUDE/Plan/x/ CLAUDE/Plan/y.md | cut -c1-200"
        )
        assert handler.matches(_bash(command)) is False

    def test_the_double_quoted_escaped_bar_alone_is_allowed(
        self, handler: PipeBlockerHandler
    ) -> None:
        assert handler.matches(_bash('pytest "a\\|head" f')) is False

    def test_an_uppercase_head_after_a_real_bar_is_not_the_head_command(
        self, handler: PipeBlockerHandler
    ) -> None:
        assert handler.matches(_bash("pytest | HEAD")) is False

    def test_an_uppercase_tail_after_a_real_bar_is_not_the_tail_command(
        self, handler: PipeBlockerHandler
    ) -> None:
        assert handler.matches(_bash("pytest | TAIL -5")) is False


class TestAnEscapedBarIsLiteral:
    def test_an_unquoted_escaped_bar_is_allowed(self, handler: PipeBlockerHandler) -> None:
        assert handler.matches(_bash('pytest "a" \\| head')) is False

    def test_an_escaped_bar_followed_by_a_space_in_single_quotes_is_allowed(
        self, handler: PipeBlockerHandler
    ) -> None:
        assert handler.matches(_bash("pytest 'a\\| head'")) is False

    def test_an_escaped_backslash_leaves_the_bar_real(self, handler: PipeBlockerHandler) -> None:
        # `\\|` is an escaped backslash followed by a real pipe.
        assert handler.matches(_bash("pytest \\\\| head")) is True


class TestRealPipesStayBlocked:
    @pytest.mark.parametrize(
        "command",
        [
            "pytest | head",
            "pytest|head",
            'pytest "x" | head',
            "pytest | tail -5",
            'echo "$( pytest | head )"',
            'echo "`pytest | head`"',
            "echo $(pytest | head -1)",
            'pytest "a\\|b" | head',
        ],
    )
    def test_is_blocked(self, handler: PipeBlockerHandler, command: str) -> None:
        assert handler.matches(_bash(command)) is True

    def test_a_real_pipe_after_a_quoted_alternation_names_the_real_producer(
        self, handler: PipeBlockerHandler
    ) -> None:
        reason = handler.handle(_bash('pytest "a\\|HEAD:b" | head')).reason or ""
        assert "pytest" in reason
        assert 'HEAD:b"' not in reason.split("pytest")[0]
