"""Unit tests for LongRunningCommandGuardHandler (Plan 00602)."""

from __future__ import annotations

import re
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.handlers.pre_tool_use.long_running_command_guard import (
    LongRunningCommandGuardHandler,
)
from claude_code_hooks_daemon.utils.long_running_command import FindingKind, classify

WAIT_COMMAND = (
    "timeout 590 bash -c 'until gh run list --branch plan-1 --json status "
    "| grep -q completed; do sleep 30; done'"
)
QA_COMMAND = "./scripts/qa/llm_qa.py changed --base main --allow-unmapped"
PYTEST_COMMAND = "pytest tests/unit -q"


def _input(command: str, **tool_input: Any) -> dict[str, Any]:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command, **tool_input},
    }


@pytest.fixture
def handler() -> LongRunningCommandGuardHandler:
    return LongRunningCommandGuardHandler()


class TestIdentity:
    def test_handler_id_and_priority(self, handler: LongRunningCommandGuardHandler) -> None:
        assert handler.handler_id == HandlerID.LONG_RUNNING_COMMAND_GUARD
        assert handler.priority == Priority.LONG_RUNNING_COMMAND_GUARD

    def test_scope_is_main_thread_only(self, handler: LongRunningCommandGuardHandler) -> None:
        assert handler.scope is HandlerScope.MAIN

    def test_not_terminal(self, handler: LongRunningCommandGuardHandler) -> None:
        assert handler.terminal is False

    def test_ships_disabled(self, handler: LongRunningCommandGuardHandler) -> None:
        assert handler.get_default_enabled() is False


class TestMatches:
    @pytest.mark.parametrize("command", [WAIT_COMMAND, QA_COMMAND, PYTEST_COMMAND, "sleep 60"])
    def test_matches_long_foreground_commands(
        self, handler: LongRunningCommandGuardHandler, command: str
    ) -> None:
        assert handler.matches(_input(command)) is True

    @pytest.mark.parametrize("command", ["git status", "ls", "cat x", "git log -3", "sleep 2"])
    def test_short_commands_never_match(
        self, handler: LongRunningCommandGuardHandler, command: str
    ) -> None:
        assert handler.matches(_input(command)) is False

    def test_background_call_is_never_judged(self, handler: LongRunningCommandGuardHandler) -> None:
        assert handler.matches(_input(WAIT_COMMAND, run_in_background=True)) is False

    def test_explicit_false_background_is_judged(
        self, handler: LongRunningCommandGuardHandler
    ) -> None:
        assert handler.matches(_input(WAIT_COMMAND, run_in_background=False)) is True

    def test_shell_backgrounded_command_is_not_judged(
        self, handler: LongRunningCommandGuardHandler
    ) -> None:
        assert handler.matches(_input("timeout 590 pytest tests > out.txt 2>&1 &")) is False

    def test_non_bash_tool_never_matches(self, handler: LongRunningCommandGuardHandler) -> None:
        assert (
            handler.matches({"tool_name": "Read", "tool_input": {"command": "sleep 60"}}) is False
        )

    def test_missing_command_never_matches(self, handler: LongRunningCommandGuardHandler) -> None:
        assert handler.matches({"tool_name": "Bash", "tool_input": {}}) is False

    def test_hatch_with_a_reason_opts_out(self, handler: LongRunningCommandGuardHandler) -> None:
        command = f'MUST_RUN_FOREGROUND_BECAUSE="owner is watching this build live"; {QA_COMMAND}'
        assert handler.matches(_input(command)) is False

    def test_hatch_with_a_placeholder_reason_is_not_honoured(
        self, handler: LongRunningCommandGuardHandler
    ) -> None:
        command = f'MUST_RUN_FOREGROUND_BECAUSE="explain why"; {QA_COMMAND}'
        assert handler.matches(_input(command)) is True

    def test_mode_off_never_matches(self, handler: LongRunningCommandGuardHandler) -> None:
        handler._mode = "off"
        assert handler.matches(_input(WAIT_COMMAND)) is False

    def test_unbounded_command_matches_for_the_advisory(
        self, handler: LongRunningCommandGuardHandler
    ) -> None:
        assert handler.matches(_input("python3 scripts/analyse.py")) is True


class TestDeny:
    def test_wait_loop_is_denied_with_background_form_and_monitor(
        self, handler: LongRunningCommandGuardHandler
    ) -> None:
        result = handler.handle(_input(WAIT_COMMAND))
        assert result.decision == Decision.DENY
        reason = result.reason or ""
        assert RuleID.LONG_RUNNING_WAIT_LOOP in reason
        assert RuleID.LONG_RUNNING_TIMEOUT in reason
        assert "run_in_background" in reason
        assert "Monitor" in reason
        assert "until gh run list" in reason

    def test_slow_command_is_denied(self, handler: LongRunningCommandGuardHandler) -> None:
        result = handler.handle(_input(QA_COMMAND))
        assert result.decision == Decision.DENY
        assert RuleID.LONG_RUNNING_SLOW_COMMAND in (result.reason or "")
        assert "llm_qa.py" in (result.reason or "")

    def test_long_sleep_is_denied(self, handler: LongRunningCommandGuardHandler) -> None:
        result = handler.handle(_input("sleep 120"))
        assert result.decision == Decision.DENY
        assert RuleID.LONG_RUNNING_SLEEP in (result.reason or "")

    def test_reason_names_the_escape_hatch(self, handler: LongRunningCommandGuardHandler) -> None:
        result = handler.handle(_input(PYTEST_COMMAND))
        assert "MUST_RUN_FOREGROUND_BECAUSE" in (result.reason or "")

    def test_reason_is_bounded_for_a_huge_command(
        self, handler: LongRunningCommandGuardHandler
    ) -> None:
        result = handler.handle(_input("pytest " + "tests/unit/x.py " * 500))
        assert len(result.reason or "") < 3000

    def test_deny_text_is_not_itself_judged_as_long(
        self, handler: LongRunningCommandGuardHandler
    ) -> None:
        reason = handler.handle(_input(WAIT_COMMAND)).reason or ""
        denying = [
            finding for finding in classify(reason) if finding.kind is not FindingKind.UNBOUNDED
        ]
        assert denying == []

    def test_advise_mode_allows_with_guidance(
        self, handler: LongRunningCommandGuardHandler
    ) -> None:
        handler._mode = "advise"
        result = handler.handle(_input(QA_COMMAND))
        assert result.decision == Decision.ALLOW
        assert "run_in_background" in (result.guidance or "")


class TestAdvisory:
    def test_unbounded_command_is_allowed_with_advice(
        self, handler: LongRunningCommandGuardHandler
    ) -> None:
        result = handler.handle(_input("python3 scripts/analyse.py"))
        assert result.decision == Decision.ALLOW
        assert RuleID.LONG_RUNNING_NO_TIMEOUT in " ".join(result.context or [])
        assert "timeout" in (result.guidance or "")

    def test_suggested_timeout_is_within_the_threshold(
        self, handler: LongRunningCommandGuardHandler
    ) -> None:
        guidance = handler.handle(_input("python3 scripts/analyse.py")).guidance or ""
        seconds = [int(n) for n in re.findall(r"timeout (\d+)", guidance)]
        assert seconds
        assert all(n <= 30 for n in seconds)

    def test_advisory_never_denies_in_deny_mode(
        self, handler: LongRunningCommandGuardHandler
    ) -> None:
        assert handler.handle(_input("curl -s https://example.com")).decision == Decision.ALLOW


class TestOptions:
    def test_threshold_option_widens_the_limit(
        self, handler: LongRunningCommandGuardHandler
    ) -> None:
        handler._threshold_seconds = 120
        assert handler.matches(_input("sleep 60")) is False

    def test_extra_slow_patterns_option(self, handler: LongRunningCommandGuardHandler) -> None:
        handler._extra_slow_patterns = [r"^deploy\.sh\b"]
        assert handler.matches(_input("./deploy.sh prod")) is True

    def test_exempt_patterns_option(self, handler: LongRunningCommandGuardHandler) -> None:
        handler._exempt_patterns = [r"^pytest tests/unit -q$"]
        assert handler.matches(_input(PYTEST_COMMAND)) is False

    def test_extra_fast_programs_option(self, handler: LongRunningCommandGuardHandler) -> None:
        handler._extra_fast_programs = ["analyse.py"]
        assert handler.matches(_input("python3 scripts/analyse.py")) is False

    def test_malformed_options_fall_back_to_defaults(
        self, handler: LongRunningCommandGuardHandler
    ) -> None:
        handler._threshold_seconds = "soon"
        handler._extra_slow_patterns = "not-a-list"
        handler._exempt_patterns = None
        handler._extra_fast_programs = 5
        assert handler.matches(_input("sleep 60")) is True

    def test_validate_options_accepts_good_config(self) -> None:
        assert (
            LongRunningCommandGuardHandler.validate_options(
                {
                    "mode": "advise",
                    "threshold_seconds": 45,
                    "extra_slow_patterns": [r"^x\b"],
                    "extra_fast_programs": ["tool"],
                    "exempt_patterns": [r"y"],
                }
            )
            == {}
        )

    @pytest.mark.parametrize(
        ("options", "key"),
        [
            ({"mode": "block"}, "mode"),
            ({"threshold_seconds": 0}, "threshold_seconds"),
            ({"threshold_seconds": "x"}, "threshold_seconds"),
            ({"threshold_seconds": True}, "threshold_seconds"),
            ({"extra_slow_patterns": "x"}, "extra_slow_patterns"),
            ({"extra_slow_patterns": ["("]}, "extra_slow_patterns"),
            ({"exempt_patterns": [1]}, "exempt_patterns"),
            ({"extra_fast_programs": "ls"}, "extra_fast_programs"),
        ],
    )
    def test_validate_options_names_each_bad_option(
        self, options: dict[str, Any], key: str
    ) -> None:
        assert key in LongRunningCommandGuardHandler.validate_options(options)

    def test_bad_mode_is_treated_as_deny(self, handler: LongRunningCommandGuardHandler) -> None:
        handler._mode = "block"
        assert handler.handle(_input(QA_COMMAND)).decision == Decision.DENY


class TestDocumentationSurface:
    def test_rules_cover_every_finding(self, handler: LongRunningCommandGuardHandler) -> None:
        ids = {rule.rule_id for rule in handler.get_rules()}
        assert ids == {
            RuleID.LONG_RUNNING_WAIT_LOOP,
            RuleID.LONG_RUNNING_TIMEOUT,
            RuleID.LONG_RUNNING_SLEEP,
            RuleID.LONG_RUNNING_SLOW_COMMAND,
            RuleID.LONG_RUNNING_NO_TIMEOUT,
        }

    def test_claude_md_names_the_form_and_hatch(
        self, handler: LongRunningCommandGuardHandler
    ) -> None:
        text = handler.get_claude_md() or ""
        assert "run_in_background" in text
        assert "Monitor" in text
        assert "MUST_RUN_FOREGROUND_BECAUSE" in text

    def test_acceptance_tests_cover_deny_and_allow(
        self, handler: LongRunningCommandGuardHandler
    ) -> None:
        tests = handler.get_acceptance_tests()
        decisions = {t.expected_decision for t in tests}
        assert decisions == {Decision.DENY, Decision.ALLOW}
        assert all(t.requires_main_thread for t in tests)

    def test_acceptance_tests_declare_the_harness_cannot_stand_for_the_main_thread(
        self, handler: LongRunningCommandGuardHandler
    ) -> None:
        """A playbook-harness event is synthetic, and the scope admits no synthetic
        event as the main thread, so a probe here would observe silence and
        pass or fail for a reason that is not the handler's verdict."""
        for test in handler.get_acceptance_tests():
            assert test.harness_cannot_produce, test.title
            assert "main thread" in test.harness_cannot_produce
