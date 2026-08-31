"""Tests for AskUserQuestionBlockerHandler — nuanced prefix-positive policy.

Plan 00108: The handler allows AskUserQuestion only when every question
carries the `ASKING BECAUSE:` prefix (mirrors the Stop handler's
`STOPPING BECAUSE:` convention). Without that prefix, the call is denied
with guidance to state the assumed-correct answer and proceed.
"""

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, HookResult
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.rule import Rule

REQUIRED_PREFIX = "ASKING BECAUSE:"


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker():
    """Reset the shared DaemonDataLayer singleton around every test in this module."""
    reset_data_layer()
    yield
    reset_data_layer()


class TestAskUserQuestionBlockerHandler:
    """Test suite for AskUserQuestionBlockerHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance with strict mode default."""
        from claude_code_hooks_daemon.handlers.pre_tool_use.ask_user_question_blocker import (
            AskUserQuestionBlockerHandler,
        )

        return AskUserQuestionBlockerHandler()

    @pytest.fixture
    def advisory_handler(self):
        """Create handler instance in advisory mode."""
        from claude_code_hooks_daemon.handlers.pre_tool_use.ask_user_question_blocker import (
            AskUserQuestionBlockerHandler,
        )

        instance = AskUserQuestionBlockerHandler()
        instance._mode = "advisory"
        return instance

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------
    def test_init_sets_correct_name(self, handler):
        assert handler.name == "block-ask-user-question"

    def test_init_sets_correct_priority(self, handler):
        assert handler.priority == 10

    def test_init_is_terminal(self, handler):
        assert handler.terminal is True

    # ------------------------------------------------------------------
    # matches()
    # ------------------------------------------------------------------
    def test_matches_ask_user_question(self, handler):
        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "AskUserQuestion",
            "tool_input": {"questions": [{"question": "Which approach?"}]},
        }
        assert handler.matches(hook_input) is True

    def test_matches_bash_returns_false(self, handler):
        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_missing_tool_name_returns_false(self, handler):
        assert handler.matches({"hook_event_name": "PreToolUse"}) is False

    def test_matches_none_tool_name_returns_false(self, handler):
        assert handler.matches({"tool_name": None}) is False

    # ------------------------------------------------------------------
    # handle() — ALLOW path (prefix on every question)
    # ------------------------------------------------------------------
    def test_handle_allows_when_single_question_has_prefix(self, handler):
        hook_input = {
            "tool_name": "AskUserQuestion",
            "tool_input": {
                "questions": [
                    {
                        "question": (
                            f"{REQUIRED_PREFIX} the user has not specified "
                            "which database driver they want and both are "
                            "supported equally. Postgres or MySQL?"
                        )
                    }
                ]
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handle_allows_when_all_questions_have_prefix(self, handler):
        hook_input = {
            "tool_name": "AskUserQuestion",
            "tool_input": {
                "questions": [
                    {"question": f"{REQUIRED_PREFIX} reason 1. Q1?"},
                    {"question": f"{REQUIRED_PREFIX} reason 2. Q2?"},
                ]
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handle_allows_with_leading_whitespace_before_prefix(self, handler):
        hook_input = {
            "tool_name": "AskUserQuestion",
            "tool_input": {"questions": [{"question": f"   {REQUIRED_PREFIX} reason. Q?"}]},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    # ------------------------------------------------------------------
    # handle() — DENY path (prefix missing on any question)
    # ------------------------------------------------------------------
    def test_handle_denies_when_question_has_no_prefix(self, handler):
        hook_input = {
            "tool_name": "AskUserQuestion",
            "tool_input": {"questions": [{"question": "Should I continue?"}]},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_handle_denies_when_mixed_prefix_state(self, handler):
        hook_input = {
            "tool_name": "AskUserQuestion",
            "tool_input": {
                "questions": [
                    {"question": f"{REQUIRED_PREFIX} reason. Q1?"},
                    {"question": "Q2 without prefix"},
                ]
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_handle_denies_with_lowercase_prefix(self, handler):
        hook_input = {
            "tool_name": "AskUserQuestion",
            "tool_input": {"questions": [{"question": "asking because: reason. Q?"}]},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_handle_denies_when_prefix_appears_mid_string(self, handler):
        hook_input = {
            "tool_name": "AskUserQuestion",
            "tool_input": {
                "questions": [
                    {
                        "question": (
                            f"Should I do X? {REQUIRED_PREFIX} actually I " "want this allowed"
                        )
                    }
                ]
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_handle_denies_when_questions_array_empty(self, handler):
        hook_input = {
            "tool_name": "AskUserQuestion",
            "tool_input": {"questions": []},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_handle_denies_when_tool_input_missing(self, handler):
        hook_input = {"tool_name": "AskUserQuestion"}
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_handle_denies_when_questions_key_missing(self, handler):
        hook_input = {"tool_name": "AskUserQuestion", "tool_input": {}}
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_handle_denies_when_question_text_missing(self, handler):
        hook_input = {
            "tool_name": "AskUserQuestion",
            "tool_input": {"questions": [{"header": "no question key"}]},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    # ------------------------------------------------------------------
    # handle() — DENY reason content
    # ------------------------------------------------------------------
    def test_deny_reason_mentions_prefix(self, handler):
        result = handler.handle(
            {
                "tool_name": "AskUserQuestion",
                "tool_input": {"questions": [{"question": "Should I continue?"}]},
            }
        )
        assert REQUIRED_PREFIX in result.reason

    def test_deny_reason_instructs_state_assumption(self, handler):
        result = handler.handle(
            {
                "tool_name": "AskUserQuestion",
                "tool_input": {"questions": [{"question": "Should I continue?"}]},
            }
        )
        assert "assum" in result.reason.lower()

    def test_deny_reason_mentions_user_will_interrupt(self, handler):
        result = handler.handle(
            {
                "tool_name": "AskUserQuestion",
                "tool_input": {"questions": [{"question": "Should I continue?"}]},
            }
        )
        assert "interrupt" in result.reason.lower() or "watching" in result.reason.lower()

    def test_deny_reason_lists_tautological_examples(self, handler):
        """Reason should call out good-vs-bad question patterns explicitly."""
        result = handler.handle(
            {
                "tool_name": "AskUserQuestion",
                "tool_input": {"questions": [{"question": "Should I bodge it?"}]},
            }
        )
        reason_lower = result.reason.lower()
        assert "best practice" in reason_lower
        assert "delivering" in reason_lower
        assert "quality" in reason_lower

    def test_claude_md_lists_tautological_examples(self, handler):
        """get_claude_md should also include the good-vs-bad guidance."""
        guidance = handler.get_claude_md()
        assert guidance is not None
        lower = guidance.lower()
        assert "best practice" in lower
        assert "bodge" in lower

    def test_handle_returns_hook_result(self, handler):
        result = handler.handle(
            {
                "tool_name": "AskUserQuestion",
                "tool_input": {"questions": [{"question": "Q?"}]},
            }
        )
        assert isinstance(result, HookResult)

    # ------------------------------------------------------------------
    # handle() — advisory mode (warn-only)
    # ------------------------------------------------------------------
    def test_advisory_mode_allows_unjustified_question(self, advisory_handler):
        result = advisory_handler.handle(
            {
                "tool_name": "AskUserQuestion",
                "tool_input": {"questions": [{"question": "Should I continue?"}]},
            }
        )
        assert result.decision == Decision.ALLOW

    def test_advisory_mode_attaches_context_warning(self, advisory_handler):
        result = advisory_handler.handle(
            {
                "tool_name": "AskUserQuestion",
                "tool_input": {"questions": [{"question": "Should I continue?"}]},
            }
        )
        # Warning text should mention the missing prefix
        joined = " ".join(result.context or []) + (result.guidance or "")
        assert REQUIRED_PREFIX in joined

    def test_advisory_mode_allows_justified_question_silently(self, advisory_handler):
        result = advisory_handler.handle(
            {
                "tool_name": "AskUserQuestion",
                "tool_input": {"questions": [{"question": f"{REQUIRED_PREFIX} reason. Q?"}]},
            }
        )
        assert result.decision == Decision.ALLOW
        # No warning needed when the call is properly justified
        assert not result.context

    # ------------------------------------------------------------------
    # handle() — custom required_prefix override
    # ------------------------------------------------------------------
    def test_custom_required_prefix_override(self, handler):
        handler._required_prefix = "JUSTIFICATION:"
        result_allow = handler.handle(
            {
                "tool_name": "AskUserQuestion",
                "tool_input": {"questions": [{"question": "JUSTIFICATION: reason. Q?"}]},
            }
        )
        result_deny = handler.handle(
            {
                "tool_name": "AskUserQuestion",
                "tool_input": {"questions": [{"question": f"{REQUIRED_PREFIX} reason. Q?"}]},
            }
        )
        assert result_allow.decision == Decision.ALLOW
        assert result_deny.decision == Decision.DENY

    # ------------------------------------------------------------------
    # get_claude_md()
    # ------------------------------------------------------------------
    def test_get_claude_md_returns_guidance(self, handler):
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert REQUIRED_PREFIX in guidance

    def test_get_claude_md_mentions_assumption_audit_pattern(self, handler):
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "assum" in guidance.lower()

    # ------------------------------------------------------------------
    # handle() — deny message leads with the rule ID (Plan 00116)
    # ------------------------------------------------------------------
    def test_handle_deny_leads_with_rule_id(self, handler):
        result = handler.handle(
            {
                "tool_name": "AskUserQuestion",
                "tool_input": {"questions": [{"question": "Should I continue?"}]},
                "transcript_path": "/tmp/agent-1/transcript.jsonl",
            }
        )
        assert result.decision == Decision.DENY
        assert result.reason.startswith(f"BLOCKED [{RuleID.ASK_USER_QUESTION_UNJUSTIFIED}]")


class TestAskUserQuestionBlockerGetRules:
    """get_rules() declares the single Rule backing strict-mode blocking."""

    @pytest.fixture
    def handler(self):
        from claude_code_hooks_daemon.handlers.pre_tool_use.ask_user_question_blocker import (
            AskUserQuestionBlockerHandler,
        )

        return AskUserQuestionBlockerHandler()

    def test_returns_one_rule(self, handler):
        rules = handler.get_rules()
        assert len(rules) == 1
        assert isinstance(rules[0], Rule)

    def test_rule_id_matches_constant(self, handler):
        assert handler.get_rules()[0].rule_id == RuleID.ASK_USER_QUESTION_UNJUSTIFIED

    def test_rule_has_non_empty_verbose(self, handler):
        assert handler.get_rules()[0].verbose


class TestAskUserQuestionBlockerDisclosureLadder:
    """Verbose-first / terse-after per-agent disclosure ladder (Plan 00116, Decision G)."""

    @pytest.fixture
    def handler(self):
        from claude_code_hooks_daemon.handlers.pre_tool_use.ask_user_question_blocker import (
            AskUserQuestionBlockerHandler,
        )

        return AskUserQuestionBlockerHandler()

    def _hook_input(self, question: str, transcript_path: str):
        return {
            "tool_name": "AskUserQuestion",
            "tool_input": {"questions": [{"question": question}]},
            "transcript_path": transcript_path,
        }

    def test_first_fire_for_agent_is_verbose(self, handler):
        result = handler.handle(
            self._hook_input("Should I continue?", "/tmp/agent-a/transcript.jsonl")
        )
        assert "TAUTOLOGICAL QUESTIONS" in result.reason

    def test_second_fire_for_same_agent_is_terse(self, handler):
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(self._hook_input("Should I continue?", transcript_path))
        result = handler.handle(self._hook_input("Should I bodge it?", transcript_path))

        assert result.decision == Decision.DENY
        assert "TAUTOLOGICAL QUESTIONS" not in result.reason
        assert result.reason.startswith(f"BLOCKED [{RuleID.ASK_USER_QUESTION_UNJUSTIFIED}]")
        assert "Fix:" in result.reason

    def test_different_agent_is_independently_verbose(self, handler):
        handler.handle(self._hook_input("Should I continue?", "/tmp/agent-a/transcript.jsonl"))
        result = handler.handle(
            self._hook_input("Should I continue?", "/tmp/agent-b/transcript.jsonl")
        )
        assert "TAUTOLOGICAL QUESTIONS" in result.reason

    def test_missing_transcript_path_fails_toward_verbose_every_time(self, handler):
        hook_input = {
            "tool_name": "AskUserQuestion",
            "tool_input": {"questions": [{"question": "Should I continue?"}]},
        }
        first = handler.handle(hook_input)
        second = handler.handle(hook_input)
        assert "TAUTOLOGICAL QUESTIONS" in first.reason
        assert "TAUTOLOGICAL QUESTIONS" in second.reason
