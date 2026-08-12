"""Tests for CommandHintsHandler (Plan 00212).

A single, config-driven PostToolUse advisory handler: when a Bash command
matches a configured hint's ``pattern`` (a literal command name, matched at
the start of a shell segment — path-qualified and ``env``-prefixed spellings
included), a rate-limited HINT is injected as advisory context. Never blocks.
"""

from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.post_tool_use.command_hints import (
    _AGENT_BROWSER_HINT_ID,
    _DEFAULT_TTL_SECONDS,
    _MAX_TRACKED_FIRE_STATES,
    CommandHint,
    CommandHintsHandler,
    _compile_hint_pattern,
    _parse_hint_entry,
    _parse_raw_hints,
    _segment_commands,
)

_MONOTONIC_PATH = "claude_code_hooks_daemon.handlers.post_tool_use.command_hints.time.monotonic"


def _bash(command: str = "echo hi", *, session_id: str = "s1") -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": session_id,
    }


class TestInit:
    @pytest.fixture
    def handler(self) -> CommandHintsHandler:
        return CommandHintsHandler()

    def test_name(self, handler: CommandHintsHandler) -> None:
        assert handler.name == "command-hints"

    def test_priority(self, handler: CommandHintsHandler) -> None:
        assert handler.priority == 29

    def test_not_terminal(self, handler: CommandHintsHandler) -> None:
        assert handler.terminal is False

    def test_default_enabled(self, handler: CommandHintsHandler) -> None:
        assert handler.get_default_enabled() is True


class TestCommandHintValidation:
    def test_valid_hint_defaults_min_calls_between_to_zero(self) -> None:
        hint = CommandHint(id="x", pattern="foo", hint="do the thing", ttl_seconds=10)
        assert hint.min_calls_between == 0

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"id": "", "pattern": "foo", "hint": "h", "ttl_seconds": 10},
            {"id": "x", "pattern": "", "hint": "h", "ttl_seconds": 10},
            {"id": "x", "pattern": "foo", "hint": "", "ttl_seconds": 10},
            {"id": "x", "pattern": "foo", "hint": "h", "ttl_seconds": -1},
            {
                "id": "x",
                "pattern": "foo",
                "hint": "h",
                "ttl_seconds": 10,
                "min_calls_between": -1,
            },
        ],
    )
    def test_invalid_hint_raises(self, kwargs: dict) -> None:
        with pytest.raises(ValueError):
            CommandHint(**kwargs)


class TestSegmentCommands:
    def test_single_segment(self) -> None:
        assert _segment_commands("agent-browser --close") == ["agent-browser --close"]

    def test_splits_on_chain_operators(self) -> None:
        assert _segment_commands("cd /tmp && agent-browser --close") == [
            "cd /tmp",
            "agent-browser --close",
        ]

    def test_splits_on_pipe(self) -> None:
        assert _segment_commands("true | agent-browser") == ["true", "agent-browser"]

    def test_quoted_separator_is_not_a_split_point(self) -> None:
        assert _segment_commands('grep -E "a;b" file') == ['grep -E "a;b" file']

    def test_empty_command_returns_no_segments(self) -> None:
        assert _segment_commands("") == []
        assert _segment_commands("   ") == []


class TestCompileHintPattern:
    def test_matches_bare_and_with_trailing_args(self) -> None:
        pattern = _compile_hint_pattern("agent-browser")
        assert pattern.match("agent-browser")
        assert pattern.match("agent-browser --close")

    def test_does_not_match_hyphenated_extension(self) -> None:
        """Regression: a trailing \\b would also match 'agent-browser-extra'
        because '-' is a non-word char to Python re (Technical Decision 2)."""
        pattern = _compile_hint_pattern("agent-browser")
        assert not pattern.match("agent-browser-extra-tool")

    def test_does_not_match_when_not_at_start(self) -> None:
        pattern = _compile_hint_pattern("agent-browser")
        assert not pattern.match("xagent-browser")


class TestParseHintEntry:
    def test_valid_entry(self) -> None:
        hint = _parse_hint_entry({"id": "x", "pattern": "foo", "hint": "do it", "ttl_seconds": 5}, 0)
        assert hint == CommandHint(id="x", pattern="foo", hint="do it", ttl_seconds=5)

    def test_missing_id_skipped(self) -> None:
        assert _parse_hint_entry({"pattern": "foo", "hint": "h", "ttl_seconds": 5}, 0) is None

    def test_missing_pattern_skipped(self) -> None:
        assert _parse_hint_entry({"id": "x", "hint": "h", "ttl_seconds": 5}, 0) is None

    def test_missing_hint_text_skipped(self) -> None:
        assert _parse_hint_entry({"id": "x", "pattern": "foo", "ttl_seconds": 5}, 0) is None

    def test_non_dict_entry_skipped(self) -> None:
        assert _parse_hint_entry("not-a-dict", 0) is None
        assert _parse_hint_entry(None, 0) is None
        assert _parse_hint_entry(["nope"], 0) is None

    def test_missing_ttl_falls_back_to_default(self) -> None:
        hint = _parse_hint_entry({"id": "x", "pattern": "foo", "hint": "h"}, 0)
        assert hint is not None
        assert hint.ttl_seconds == _DEFAULT_TTL_SECONDS

    def test_non_int_ttl_falls_back_to_default(self) -> None:
        hint = _parse_hint_entry(
            {"id": "x", "pattern": "foo", "hint": "h", "ttl_seconds": "soon"}, 0
        )
        assert hint is not None
        assert hint.ttl_seconds == _DEFAULT_TTL_SECONDS

    def test_bool_ttl_rejected_as_non_int(self) -> None:
        """bool is a subclass of int in Python; must not silently pass through."""
        hint = _parse_hint_entry({"id": "x", "pattern": "foo", "hint": "h", "ttl_seconds": True}, 0)
        assert hint is not None
        assert hint.ttl_seconds == _DEFAULT_TTL_SECONDS

    def test_negative_ttl_falls_back_to_default(self) -> None:
        hint = _parse_hint_entry({"id": "x", "pattern": "foo", "hint": "h", "ttl_seconds": -5}, 0)
        assert hint is not None
        assert hint.ttl_seconds == _DEFAULT_TTL_SECONDS

    def test_negative_min_calls_between_falls_back_to_zero(self) -> None:
        hint = _parse_hint_entry(
            {
                "id": "x",
                "pattern": "foo",
                "hint": "h",
                "ttl_seconds": 5,
                "min_calls_between": -3,
            },
            0,
        )
        assert hint is not None
        assert hint.min_calls_between == 0

    def test_valid_min_calls_between_preserved(self) -> None:
        hint = _parse_hint_entry(
            {
                "id": "x",
                "pattern": "foo",
                "hint": "h",
                "ttl_seconds": 5,
                "min_calls_between": 3,
            },
            0,
        )
        assert hint is not None
        assert hint.min_calls_between == 3


class TestParseRawHints:
    def test_none_or_empty_yields_no_hints(self) -> None:
        assert _parse_raw_hints(None) == []
        assert _parse_raw_hints([]) == []

    def test_non_list_yields_no_hints(self) -> None:
        assert _parse_raw_hints({"id": "x"}) == []

    def test_skips_malformed_entries_keeps_valid_ones(self) -> None:
        raw = [
            {"id": "good", "pattern": "foo", "hint": "h", "ttl_seconds": 5},
            {"id": "bad-missing-pattern", "hint": "h"},
        ]
        parsed = _parse_raw_hints(raw)
        assert [hint.id for hint in parsed] == ["good"]


class TestMatchesDefaultHint:
    @pytest.fixture
    def handler(self) -> CommandHintsHandler:
        return CommandHintsHandler()

    @pytest.mark.parametrize(
        "command",
        [
            "agent-browser --close",
            "agent-browser",
            "/usr/local/bin/agent-browser --close",
            "./agent-browser",
            "env agent-browser --close",
            "cd /tmp && agent-browser --close",
            "true | agent-browser",
            "env \\\nagent-browser --close",
        ],
    )
    def test_matches_agent_browser_spellings(self, handler: CommandHintsHandler, command: str) -> None:
        assert handler.matches(_bash(command)) is True

    @pytest.mark.parametrize(
        "command",
        [
            "echo hello",
            "grep agent-browser notes.md",
            'git commit -m "agent-browser fix"',
            "agent-browser-extra-tool --run",
            "agentbrowser --close",
        ],
    )
    def test_does_not_match_unrelated_commands(
        self, handler: CommandHintsHandler, command: str
    ) -> None:
        assert handler.matches(_bash(command)) is False

    def test_non_bash_tool_never_matches(self, handler: CommandHintsHandler) -> None:
        assert handler.matches({"tool_name": "Read", "tool_input": {}}) is False

    def test_empty_command_does_not_match(self, handler: CommandHintsHandler) -> None:
        assert handler.matches(_bash("")) is False

    def test_separators_only_command_yields_no_segments(self, handler: CommandHintsHandler) -> None:
        """A command that is only separators (";;") splits into empty segments."""
        assert handler.matches(_bash(";;")) is False

    def test_matches_does_not_mutate_fire_state(self, handler: CommandHintsHandler) -> None:
        handler.matches(_bash("agent-browser"))
        handler.matches(_bash("agent-browser"))
        result = handler.handle(_bash("agent-browser"))
        assert result.context


class TestHandleTtlGating:
    @pytest.fixture
    def handler(self) -> CommandHintsHandler:
        return CommandHintsHandler()

    def test_first_call_returns_allow_with_context(self, handler: CommandHintsHandler) -> None:
        result = handler.handle(_bash("agent-browser --close"))
        assert result.decision == Decision.ALLOW
        assert result.context
        assert any("close" in ctx.lower() for ctx in result.context)

    def test_second_call_within_ttl_is_suppressed(self, handler: CommandHintsHandler) -> None:
        handler.handle(_bash("agent-browser --close"))
        result = handler.handle(_bash("agent-browser --close"))
        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_fires_again_after_ttl_elapses(self, handler: CommandHintsHandler) -> None:
        with patch(_MONOTONIC_PATH) as mono:
            mono.return_value = 1000.0
            first = handler.handle(_bash("agent-browser --close"))
            assert first.context

            mono.return_value = 1000.0 + _DEFAULT_TTL_SECONDS + 1
            second = handler.handle(_bash("agent-browser --close"))
            assert second.context

    def test_does_not_fire_before_ttl_elapses(self, handler: CommandHintsHandler) -> None:
        with patch(_MONOTONIC_PATH) as mono:
            mono.return_value = 1000.0
            handler.handle(_bash("agent-browser --close"))

            mono.return_value = 1000.0 + _DEFAULT_TTL_SECONDS - 1
            result = handler.handle(_bash("agent-browser --close"))
            assert result.context == []

    def test_different_sessions_tracked_independently(self, handler: CommandHintsHandler) -> None:
        handler.handle(_bash("agent-browser --close", session_id="a"))
        result = handler.handle(_bash("agent-browser --close", session_id="b"))
        assert result.context

    def test_no_match_returns_allow_no_context(self, handler: CommandHintsHandler) -> None:
        result = handler.handle(_bash("echo hi"))
        assert result.decision == Decision.ALLOW
        assert result.context == []


class TestMinCallsBetweenSecondaryGate:
    def test_requires_both_ttl_and_call_count(self) -> None:
        handler = CommandHintsHandler()
        handler._mode = "replace"
        handler._hints = [
            {
                "id": "custom",
                "pattern": "my-tool",
                "hint": "remember X",
                "ttl_seconds": 0,
                "min_calls_between": 2,
            }
        ]

        assert handler.handle(_bash("my-tool")).context  # 1st: first-ever fire
        assert handler.handle(_bash("my-tool")).context == []  # 2nd: 0 calls since fire
        assert handler.handle(_bash("my-tool")).context == []  # 3rd: 1 call since fire
        assert handler.handle(_bash("my-tool")).context  # 4th: 2 calls since fire + ttl elapsed


class TestBoundedFireState:
    def test_state_map_is_bounded(self) -> None:
        handler = CommandHintsHandler()
        for i in range(_MAX_TRACKED_FIRE_STATES + 50):
            handler.handle(_bash("agent-browser", session_id=f"s{i}"))
        assert len(handler._fire_state) <= _MAX_TRACKED_FIRE_STATES


class TestConfigModeAdditive:
    def test_default_mode_only_builtin_hint_active(self) -> None:
        handler = CommandHintsHandler()
        assert handler.matches(_bash("agent-browser")) is True
        assert handler.matches(_bash("my-tool")) is False

    def test_additive_adds_new_project_hint(self) -> None:
        handler = CommandHintsHandler()
        handler._hints = [
            {"id": "custom", "pattern": "my-tool", "hint": "remember X", "ttl_seconds": 10}
        ]
        assert handler.matches(_bash("agent-browser")) is True
        assert handler.matches(_bash("my-tool run")) is True

    def test_additive_project_hint_overrides_builtin_by_id(self) -> None:
        handler = CommandHintsHandler()
        handler._hints = [
            {
                "id": _AGENT_BROWSER_HINT_ID,
                "pattern": "agent-browser",
                "hint": "CUSTOM TEXT",
                "ttl_seconds": 1,
            }
        ]
        result = handler.handle(_bash("agent-browser"))
        assert len(result.context) == 1
        assert "CUSTOM TEXT" in result.context[0]

    def test_unknown_mode_falls_back_to_additive(self) -> None:
        handler = CommandHintsHandler()
        handler._mode = "bogus"
        assert handler.matches(_bash("agent-browser")) is True


class TestConfigModeReplace:
    def test_replace_discards_builtin(self) -> None:
        handler = CommandHintsHandler()
        handler._mode = "replace"
        handler._hints = [
            {"id": "custom", "pattern": "my-tool", "hint": "remember X", "ttl_seconds": 10}
        ]
        assert handler.matches(_bash("agent-browser")) is False
        assert handler.matches(_bash("my-tool")) is True

    def test_replace_with_no_project_hints_yields_zero_hints(self) -> None:
        handler = CommandHintsHandler()
        handler._mode = "replace"
        assert handler.matches(_bash("agent-browser")) is False


class TestClaudeMdAndAcceptanceTests:
    @pytest.fixture
    def handler(self) -> CommandHintsHandler:
        return CommandHintsHandler()

    def test_get_claude_md_mentions_command_hints_and_modes(
        self, handler: CommandHintsHandler
    ) -> None:
        content = handler.get_claude_md()
        assert content is not None
        assert "command_hints" in content
        assert "additive" in content
        assert "replace" in content

    def test_get_acceptance_tests_nonempty(self, handler: CommandHintsHandler) -> None:
        tests = handler.get_acceptance_tests()
        assert len(tests) >= 1
        for test in tests:
            assert test.title
            assert test.command
            assert test.description
