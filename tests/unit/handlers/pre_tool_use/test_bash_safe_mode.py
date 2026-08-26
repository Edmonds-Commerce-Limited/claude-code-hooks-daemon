"""Tests for the opt-in bash safe-mode forcer (Plan 00270).

The handler ships ``enabled: false`` and, when enabled, defaults to
``mode: warn``. Every Plan 00268 §6 false-positive shape must be an ALLOW
decision under the defaults, and never flagged at all under
``only_with_mutator: true``.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.bash_safe_mode import BashSafeModeHandler


def _bash(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


@pytest.fixture
def handler() -> BashSafeModeHandler:
    return BashSafeModeHandler()


class TestInitialization:
    def test_identity(self, handler: BashSafeModeHandler) -> None:
        assert handler.handler_id == HandlerID.BASH_SAFE_MODE
        assert handler.priority == Priority.BASH_SAFE_MODE
        assert handler.terminal is False


class TestMatchesPositive:
    def test_multi_statement_without_prelude(self, handler: BashSafeModeHandler) -> None:
        assert handler.matches(_bash("pytest tests/\ngit commit -m x")) is True

    def test_semicolon_separated(self, handler: BashSafeModeHandler) -> None:
        assert handler.matches(_bash("grep -q pattern file.txt; echo done")) is True

    def test_partial_prelude_still_matches(self, handler: BashSafeModeHandler) -> None:
        # errexit present, pipefail (also required by default) missing.
        assert handler.matches(_bash("set -e\npytest tests/\ngit commit -m x")) is True


class TestMatchesNegative:
    def test_non_bash_tool(self, handler: BashSafeModeHandler) -> None:
        assert handler.matches({"tool_name": "Write", "tool_input": {}}) is False

    def test_empty_command(self, handler: BashSafeModeHandler) -> None:
        assert handler.matches(_bash("")) is False

    def test_single_statement_never_flagged(self, handler: BashSafeModeHandler) -> None:
        assert handler.matches(_bash("ls -la untracked/")) is False

    def test_pure_and_chain_is_one_statement(self, handler: BashSafeModeHandler) -> None:
        # `&&`-only chaining IS consumption; split on (";", "\n") yields one
        # statement, below the threshold — BRAINSTORM §4's resolution.
        assert handler.matches(_bash("ruff check src/ && git commit -m x")) is False

    def test_full_prelude_stands_the_handler_down(self, handler: BashSafeModeHandler) -> None:
        assert handler.matches(_bash("set -euo pipefail\npytest tests/\ngit commit -m x")) is False

    def test_prelude_split_across_statements(self, handler: BashSafeModeHandler) -> None:
        command = "set -e\nset -o pipefail\npytest tests/\ngit commit -m x"
        assert handler.matches(_bash(command)) is False

    def test_escape_hatch(self, handler: BashSafeModeHandler) -> None:
        command = 'MUST_SKIP_SAFE_MODE_BECAUSE="diagnostic sweep"; pytest tests/; git commit -m x'
        assert handler.matches(_bash(command)) is False


class TestConfigurableOptions:
    def test_require_errexit_only(self, handler: BashSafeModeHandler) -> None:
        handler._require = ["errexit"]
        assert handler.matches(_bash("set -e\npytest tests/\ngit commit -m x")) is False

    def test_require_including_nounset(self, handler: BashSafeModeHandler) -> None:
        handler._require = ["errexit", "pipefail", "nounset"]
        assert handler.matches(_bash("set -eo pipefail\na\nb")) is True
        assert handler.matches(_bash("set -euo pipefail\na\nb")) is False

    def test_min_statements_raised(self, handler: BashSafeModeHandler) -> None:
        handler._min_statements = 3
        assert handler.matches(_bash("a\nb")) is False
        assert handler.matches(_bash("a\nb\nc")) is True

    def test_only_with_mutator_spares_pure_diagnostics(
        self, handler: BashSafeModeHandler
    ) -> None:
        handler._only_with_mutator = True
        assert handler.matches(_bash("grep -q pattern file.txt; echo done")) is False
        assert handler.matches(_bash("pytest tests/\ngit commit -m x")) is True

    def test_exempt_patterns(self, handler: BashSafeModeHandler) -> None:
        handler._exempt_patterns = [r"^make\s"]
        assert handler.matches(_bash("make lint\nmake test")) is False

    def test_malformed_options_fall_back_to_defaults(self, handler: BashSafeModeHandler) -> None:
        handler._require = "not-a-list"
        handler._min_statements = "soon"
        handler._exempt_patterns = {"nope": 1}
        assert handler.matches(_bash("pytest tests/\ngit commit -m x")) is True


class TestModeProperty:
    def test_inject_is_rejected_naming_the_missing_capability(
        self, handler: BashSafeModeHandler
    ) -> None:
        with pytest.raises(ValueError, match="updatedInput"):
            handler._mode = "inject"

    def test_unknown_mode_is_rejected(self, handler: BashSafeModeHandler) -> None:
        with pytest.raises(ValueError, match="mode"):
            handler._mode = "yolo"

    def test_warn_and_block_are_accepted(self, handler: BashSafeModeHandler) -> None:
        handler._mode = "block"
        assert handler._mode == "block"
        handler._mode = "warn"
        assert handler._mode == "warn"


class TestHandleWarnMode:
    def test_warn_allows_with_guidance(self, handler: BashSafeModeHandler) -> None:
        result = handler.handle(_bash("pytest tests/\ngit commit -m x"))
        assert result.decision == Decision.ALLOW
        assert result.context
        assert result.guidance is not None
        assert "MUST_SKIP_SAFE_MODE_BECAUSE" in result.guidance

    def test_message_names_only_the_missing_flags(self, handler: BashSafeModeHandler) -> None:
        result = handler.handle(_bash("set -e\npytest tests/\ngit commit -m x"))
        assert result.guidance is not None
        assert "pipefail" in result.guidance
        assert "errexit" not in "".join(result.context or [])

    def test_guidance_teaches_the_blind_spots(self, handler: BashSafeModeHandler) -> None:
        result = handler.handle(_bash("pytest tests/\ngit commit -m x"))
        guidance = result.guidance or ""
        assert "if" in guidance
        assert "&&" in guidance
        assert "local x=$(fail)" in guidance
        assert "SIGPIPE" in guidance

    def test_clean_command_allows_silently(self, handler: BashSafeModeHandler) -> None:
        result = handler.handle(_bash("set -euo pipefail\npytest tests/\ngit commit -m x"))
        assert result.decision == Decision.ALLOW
        assert not result.context


class TestHandleBlockMode:
    def test_block_denies(self, handler: BashSafeModeHandler) -> None:
        handler._mode = "block"
        result = handler.handle(_bash("pytest tests/\ngit commit -m x"))
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "pipefail" in result.reason


class TestFalsePositiveShapesFrom00268:
    """Every §6 shape is an ALLOW decision under the shipped defaults."""

    @pytest.mark.parametrize(
        "command",
        [
            "grep -q pattern file.txt; echo done",
            'cmd > /tmp/out.txt 2>&1; echo "exit=$?"',
            "echo '== section 1 =='; probe-one; echo '== section 2 =='; probe-two",
        ],
    )
    def test_warn_mode_never_stops_the_shape(
        self, handler: BashSafeModeHandler, command: str
    ) -> None:
        result = handler.handle(_bash(command))
        assert result.decision == Decision.ALLOW

    @pytest.mark.parametrize(
        "command",
        [
            "grep -q pattern file.txt; echo done",
            'cmd > /tmp/out.txt 2>&1; echo "exit=$?"',
            "echo '== section 1 =='; probe-one; echo '== section 2 =='; probe-two",
        ],
    )
    def test_only_with_mutator_never_flags_the_shape(
        self, handler: BashSafeModeHandler, command: str
    ) -> None:
        handler._only_with_mutator = True
        assert handler.matches(_bash(command)) is False


class TestResidentGuidance:
    def test_get_claude_md_is_present_and_teaches(self, handler: BashSafeModeHandler) -> None:
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "opt-in" in guidance
        assert "errexit" in guidance
        assert "local x=$(fail)" in guidance

    def test_acceptance_tests_exist(self, handler: BashSafeModeHandler) -> None:
        assert handler.get_acceptance_tests()
