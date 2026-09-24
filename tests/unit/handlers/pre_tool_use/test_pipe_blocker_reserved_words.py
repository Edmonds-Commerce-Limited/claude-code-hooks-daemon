"""A shell reserved word is never a pipe's producer (Plan 00422 N25).

`for f in a b; do grep x "$f" | head; done` splits on `;` into the segment
` do grep x "$f"`, and the producer extraction kept `do` in front of the
command. `grep` is whitelisted, `do` is not, so the pipe was denied as
"do unrecognized", and the fix the deny message printed was
`extra_whitelist: - "^do\\b"`. Copying it would exempt every loop body's pipe,
`do pytest ... | tail` included, which is worse than the false positive.

The producer is the command AFTER the reserved words. A pipe fed by a whole
compound command (`...; done | tail`) has no single producer to whitelist, so
the message must not suggest one.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler

# Every reserved word that can stand in front of a command in bash.
_PREFIXES = ("do ", "then ", "else ", "elif ", "if ", "while ", "until ", "! ", "{ ", "time ")


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker() -> Any:
    reset_data_layer()
    yield
    reset_data_layer()


@pytest.fixture
def handler() -> PipeBlockerHandler:
    return PipeBlockerHandler()


def _bash(command: str, transcript_path: str | None = None) -> dict[str, Any]:
    hook_input: dict[str, Any] = {"tool_name": ToolName.BASH, "tool_input": {"command": command}}
    if transcript_path is not None:
        hook_input["transcript_path"] = transcript_path
    return hook_input


def _reason(handler: PipeBlockerHandler, command: str, transcript_path: str | None = None) -> str:
    return handler.handle(_bash(command, transcript_path)).reason or ""


class TestTheFieldReport:
    def test_a_whitelisted_producer_in_a_loop_body_is_allowed(
        self, handler: PipeBlockerHandler
    ) -> None:
        assert handler.matches(_bash('for f in a b; do grep x "$f" | head; done')) is False

    def test_the_multi_line_loop_is_allowed(self, handler: PipeBlockerHandler) -> None:
        command = 'for x in $f; do\n  grep -n "pat" $x | head -30\ndone'
        assert handler.matches(_bash(command)) is False


class TestEveryReservedWordIsSkipped:
    @pytest.mark.parametrize("prefix", _PREFIXES)
    def test_a_whitelisted_producer_stays_allowed(
        self, handler: PipeBlockerHandler, prefix: str
    ) -> None:
        assert handler.matches(_bash(f"{prefix}grep x f | head")) is False

    @pytest.mark.parametrize("prefix", _PREFIXES)
    def test_an_expensive_producer_is_still_denied(
        self, handler: PipeBlockerHandler, prefix: str
    ) -> None:
        """Skipping the word must not launder the pipe: `do pytest | head` still denies."""
        assert handler.matches(_bash(f"{prefix}pytest tests/ | head")) is True

    @pytest.mark.parametrize("prefix", _PREFIXES)
    def test_the_expensive_producer_is_named_as_itself(
        self, handler: PipeBlockerHandler, prefix: str
    ) -> None:
        reason = _reason(handler, f"{prefix}pytest tests/ | tail -5")
        assert "Piping pytest to tail/head" in reason

    def test_stacked_reserved_words_are_all_skipped(self, handler: PipeBlockerHandler) -> None:
        assert (
            handler.matches(_bash("while true; do if ! grep -q x f | head; then :; fi; done"))
            is False
        )

    def test_time_with_its_posix_flag_is_skipped(self, handler: PipeBlockerHandler) -> None:
        assert handler.matches(_bash("time -p grep x f | head")) is False


class TestTheWhitelistSuggestionNeverNamesAReservedWord:
    @pytest.mark.parametrize("prefix", _PREFIXES)
    def test_an_unknown_producer_is_suggested_by_its_own_name(
        self, handler: PipeBlockerHandler, prefix: str
    ) -> None:
        reason = _reason(handler, f"{prefix}mytool --report | head")
        assert '"^mytool\\\\b"' in reason
        assert f'"^{prefix.strip()}' not in reason

    @pytest.mark.parametrize(
        "command",
        [
            "for f in a b; do mytool $f; done | tail -5",
            "if true; then mytool; fi | head",
            "{ mytool; } | head",
            "case $x in a) mytool;; esac | tail",
        ],
    )
    def test_a_compound_command_gets_no_whitelist_line(
        self, handler: PipeBlockerHandler, command: str
    ) -> None:
        """The producer is the whole loop, `if` or group, which no pattern can name.

        Fired twice under one transcript so both the verbose first message and
        the terse repeat are checked.
        """
        assert handler.matches(_bash(command)) is True
        for fire in ("verbose", "terse"):
            reason = _reason(handler, command, "/tmp/n25-transcript.jsonl")
            assert "extra_whitelist" not in reason, fire
            assert "compound command" in reason, fire
