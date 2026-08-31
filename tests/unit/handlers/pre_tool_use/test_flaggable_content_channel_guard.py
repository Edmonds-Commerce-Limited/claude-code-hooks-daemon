"""Unit tests for FlaggableContentChannelGuardHandler (Plan 00278 Phase 3d.1).

Deny-by-command-shape handler: closes the git/grep contamination channel the
``flaggable_work_advisor`` cannot — content-revealing git commands
(``git diff``, ``git show``, ``git log -p``, ``git add -p``) and the
``grep``/``rg``/``egrep``/``fgrep`` family pull a flaggable file's content
into context inside a routine command's output, with no deliberate ``Read``
at all. Ships DISABLED (opt-in); when enabled it DENIES.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.pre_tool_use.flaggable_content_channel_guard import (
    FlaggableContentChannelGuardHandler,
)


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker():
    """Reset the shared DaemonDataLayer singleton around every test in this module."""
    reset_data_layer()
    yield
    reset_data_layer()


def _bash(command: str) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "s1",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


@pytest.fixture
def handler() -> FlaggableContentChannelGuardHandler:
    instance = FlaggableContentChannelGuardHandler()
    instance._flaggable_path_globs = ["firewall/**", "*.rules"]
    return instance


class TestInitialisation:
    def test_identity(self) -> None:
        instance = FlaggableContentChannelGuardHandler()
        assert instance.handler_id == HandlerID.FLAGGABLE_CONTENT_CHANNEL_GUARD
        assert instance.priority == Priority.FLAGGABLE_CONTENT_CHANNEL_GUARD
        assert instance.terminal is True

    def test_ships_disabled(self) -> None:
        assert FlaggableContentChannelGuardHandler().get_default_enabled() is False


class TestContentRevealingGitShapes:
    def test_git_diff_of_flaggable_path_matches(
        self, handler: FlaggableContentChannelGuardHandler
    ) -> None:
        assert handler.matches(_bash("git diff firewall/edge/rules.yml")) is True

    def test_git_show_of_flaggable_path_matches(
        self, handler: FlaggableContentChannelGuardHandler
    ) -> None:
        assert handler.matches(_bash("git show firewall/edge/rules.yml")) is True

    def test_git_log_dash_p_of_flaggable_path_matches(
        self, handler: FlaggableContentChannelGuardHandler
    ) -> None:
        assert handler.matches(_bash("git log -p -- firewall/edge/rules.yml")) is True

    def test_git_log_long_patch_flag_matches(
        self, handler: FlaggableContentChannelGuardHandler
    ) -> None:
        assert handler.matches(_bash("git log --patch firewall/edge/rules.yml")) is True

    def test_git_add_dash_p_of_flaggable_path_matches(
        self, handler: FlaggableContentChannelGuardHandler
    ) -> None:
        assert handler.matches(_bash("git add -p firewall/edge/rules.yml")) is True

    def test_git_add_long_patch_flag_matches(
        self, handler: FlaggableContentChannelGuardHandler
    ) -> None:
        assert handler.matches(_bash("git add --patch firewall/edge/rules.yml")) is True


class TestNonRevealingGitShapesAllowed:
    def test_git_status_does_not_match(self, handler: FlaggableContentChannelGuardHandler) -> None:
        assert handler.matches(_bash("git status")) is False

    def test_git_log_without_patch_does_not_match(
        self, handler: FlaggableContentChannelGuardHandler
    ) -> None:
        assert handler.matches(_bash("git log firewall/edge/rules.yml")) is False

    def test_git_add_without_patch_does_not_match(
        self, handler: FlaggableContentChannelGuardHandler
    ) -> None:
        assert handler.matches(_bash("git add firewall/edge/rules.yml")) is False

    def test_git_diff_without_any_path_mention_does_not_match(
        self, handler: FlaggableContentChannelGuardHandler
    ) -> None:
        assert handler.matches(_bash("git diff")) is False


class TestGrepFamily:
    def test_grep_of_flaggable_path_matches(
        self, handler: FlaggableContentChannelGuardHandler
    ) -> None:
        assert handler.matches(_bash("grep drop firewall/edge/rules.yml")) is True

    def test_rg_of_flaggable_path_matches(
        self, handler: FlaggableContentChannelGuardHandler
    ) -> None:
        assert handler.matches(_bash("rg drop firewall/edge/rules.yml")) is True

    def test_egrep_of_flaggable_path_matches(
        self, handler: FlaggableContentChannelGuardHandler
    ) -> None:
        assert handler.matches(_bash("egrep drop firewall/edge/rules.yml")) is True

    def test_fgrep_of_flaggable_path_matches(
        self, handler: FlaggableContentChannelGuardHandler
    ) -> None:
        assert handler.matches(_bash("fgrep drop firewall/edge/rules.yml")) is True

    def test_grep_of_unrelated_path_does_not_match(
        self, handler: FlaggableContentChannelGuardHandler
    ) -> None:
        assert handler.matches(_bash("grep TODO src/app.py")) is False


class TestCompoundCommands:
    def test_matches_within_one_segment_of_a_compound_command(
        self, handler: FlaggableContentChannelGuardHandler
    ) -> None:
        assert handler.matches(_bash("git status && git diff firewall/edge/rules.yml")) is True

    def test_pipe_segment_is_checked(self, handler: FlaggableContentChannelGuardHandler) -> None:
        assert handler.matches(_bash("git log -p firewall/edge/rules.yml | less")) is True


class TestInertWithoutConfig:
    def test_no_globs_configured_means_no_match(self) -> None:
        instance = FlaggableContentChannelGuardHandler()
        assert instance.matches(_bash("git diff firewall/edge/rules.yml")) is False

    def test_non_bash_tool_never_matches(
        self, handler: FlaggableContentChannelGuardHandler
    ) -> None:
        payload: dict[str, Any] = {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "Read",
            "tool_input": {"file_path": "firewall/edge/rules.yml"},
        }
        assert handler.matches(payload) is False


class TestModeMerging:
    def test_additive_mode_extends_seed_globs(self) -> None:
        instance = FlaggableContentChannelGuardHandler()
        instance._flaggable_path_globs = ["tarpit/**"]
        assert instance.matches(_bash("git diff tarpit/edge.conf")) is True

    def test_replace_mode_uses_only_project_globs(self) -> None:
        instance = FlaggableContentChannelGuardHandler()
        instance._mode = "replace"
        instance._flaggable_path_globs = ["tarpit/**"]
        assert instance.matches(_bash("git diff tarpit/edge.conf")) is True

    def test_extra_content_revealing_patterns_extend_the_seed(self) -> None:
        instance = FlaggableContentChannelGuardHandler()
        instance._flaggable_path_globs = ["firewall/**"]
        instance._extra_content_revealing_patterns = [r"^git\s+blame\b"]
        assert instance.matches(_bash("git blame firewall/edge/rules.yml")) is True

    def test_invalid_custom_pattern_is_skipped_not_fatal(self) -> None:
        instance = FlaggableContentChannelGuardHandler()
        instance._flaggable_path_globs = ["firewall/**"]
        instance._extra_content_revealing_patterns = ["("]  # invalid regex
        # Built-in shapes still work; the bad pattern is skipped, not fatal.
        assert instance.matches(_bash("git diff firewall/edge/rules.yml")) is True


class TestHandle:
    def test_denies_with_shape_and_glob_in_reason(
        self, handler: FlaggableContentChannelGuardHandler
    ) -> None:
        result = handler.handle(_bash("git diff firewall/edge/rules.yml"))
        assert result.decision == Decision.DENY
        assert "git diff" in result.reason
        assert "firewall/**" in result.reason

    def test_allow_when_no_match(self, handler: FlaggableContentChannelGuardHandler) -> None:
        result = handler.handle(_bash("git status"))
        assert result.decision == Decision.ALLOW

    def test_deny_reason_names_quarantine_delegation(
        self, handler: FlaggableContentChannelGuardHandler
    ) -> None:
        result = handler.handle(_bash("grep drop firewall/edge/rules.yml"))
        assert "subagent" in result.reason.lower()
        assert "NO escape hatch" in result.reason


class TestGuidanceSurfaces:
    def test_get_claude_md(self) -> None:
        guidance = FlaggableContentChannelGuardHandler().get_claude_md()
        assert guidance is not None
        assert "flaggable_content_channel_guard" in guidance

    def test_get_acceptance_tests(self) -> None:
        tests = FlaggableContentChannelGuardHandler().get_acceptance_tests()
        assert tests
        for test in tests:
            assert test.title
        assert any(test.expected_decision == Decision.DENY for test in tests)


class TestEdgeBranches:
    def test_non_dict_hook_input_does_not_match(
        self, handler: FlaggableContentChannelGuardHandler
    ) -> None:
        payload: Any = None
        assert handler.matches(payload) is False

    def test_missing_command_does_not_match(
        self, handler: FlaggableContentChannelGuardHandler
    ) -> None:
        payload: dict[str, Any] = {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {},
        }
        assert handler.matches(payload) is False

    def test_replace_mode_on_globs_never_discards_builtin_shapes(self) -> None:
        """``mode: replace`` governs only the path-glob list, never the shapes.

        Removing the built-in git/grep shapes would leave the handler unable
        to detect the leak it exists for, so there is no supported way to
        discard them -- ``extra_content_revealing_patterns`` only EXTENDS.
        """
        instance = FlaggableContentChannelGuardHandler()
        instance._flaggable_path_globs = ["firewall/**"]
        instance._mode = "replace"
        instance._extra_content_revealing_patterns = [r"^git\s+blame\b"]
        # Built-in "git diff" shape is still active alongside the extra one.
        assert instance.matches(_bash("git diff firewall/edge/rules.yml")) is True
        assert instance.matches(_bash("git blame firewall/edge/rules.yml")) is True


class TestFlaggableContentChannelGuardGetRules:
    """get_rules() declares the single Rule backing this handler (Plan 00116)."""

    def test_returns_one_rule(self, handler: FlaggableContentChannelGuardHandler) -> None:
        rules = handler.get_rules()
        assert len(rules) == 1
        assert isinstance(rules[0], Rule)

    def test_rule_id_matches_constant(self, handler: FlaggableContentChannelGuardHandler) -> None:
        assert handler.get_rules()[0].rule_id == RuleID.FLAGGABLE_CONTENT_CHANNEL

    def test_rule_has_non_empty_verbose(self, handler: FlaggableContentChannelGuardHandler) -> None:
        assert handler.get_rules()[0].verbose


class TestFlaggableContentChannelGuardDisclosureLadder:
    """Verbose-first / terse-after per-agent disclosure ladder (Decision G)."""

    def _bash_with_transcript(self, command: str, transcript_path: str) -> dict[str, Any]:
        hook_input = _bash(command)
        hook_input["transcript_path"] = transcript_path
        return hook_input

    def test_first_fire_for_agent_is_verbose(
        self, handler: FlaggableContentChannelGuardHandler
    ) -> None:
        hook_input = self._bash_with_transcript(
            "git diff firewall/edge/rules.yml", "/tmp/agent-a/transcript.jsonl"
        )
        result = handler.handle(hook_input)

        assert result.decision == Decision.DENY
        assert "NO escape hatch" in result.reason

    def test_second_fire_for_same_agent_is_terse(
        self, handler: FlaggableContentChannelGuardHandler
    ) -> None:
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(
            self._bash_with_transcript("git diff firewall/edge/rules.yml", transcript_path)
        )
        result = handler.handle(
            self._bash_with_transcript("grep drop firewall/edge/rules.yml", transcript_path)
        )

        assert result.decision == Decision.DENY
        assert "NO escape hatch" not in result.reason
        assert "firewall/**" in result.reason

    def test_terse_message_leads_with_rule_id(
        self, handler: FlaggableContentChannelGuardHandler
    ) -> None:
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(
            self._bash_with_transcript("git diff firewall/edge/rules.yml", transcript_path)
        )
        result = handler.handle(
            self._bash_with_transcript("git diff firewall/edge/rules.yml", transcript_path)
        )

        assert result.reason.startswith(f"BLOCKED [{RuleID.FLAGGABLE_CONTENT_CHANNEL}]")

    def test_missing_transcript_path_is_always_verbose(
        self, handler: FlaggableContentChannelGuardHandler
    ) -> None:
        hook_input = _bash("git diff firewall/edge/rules.yml")
        handler.handle(hook_input)
        result = handler.handle(hook_input)

        assert "NO escape hatch" in result.reason
