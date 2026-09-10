"""Tests for SelfMatchingProcessProbeHandler (Plan 00363).

The handler denies a process probe whose literal pattern matches the argv of
the shell running it — wherever it appears, because an advisory inside a
background waiter is read by nobody. Two advisory rules sit beside it: an
uncapped `while`/`until` wait on a process, and a pattern built by expansion
that the daemon cannot read.

The deny and allow corpora below are the ones in the imported incident report
(`CLAUDE/Plan/00363-…/INCIDENT-REPORT.md`), verbatim.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority, ToolName
from claude_code_hooks_daemon.constants.priority import PriorityRange
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, TestType
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.relevance import RelevanceContext
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.pre_tool_use.self_matching_process_probe import (
    SelfMatchingProcessProbeHandler,
)

_INCIDENT = 'until ! pgrep -f "provision.bash target-host" >/dev/null; do sleep 20; done'

_DENY_CORPUS = [
    _INCIDENT,
    "while pgrep -af 'provisioner playbooks/' ; do sleep 5; done",
    'pkill -f "my-long-job"',
    'ps aux | grep "provisioner" | wc -l',
]

_ALLOW_CORPUS = [
    "pgrep -f '[p]rovision.bash'",
    "pgrep -x provisioner",
    "ps aux | grep '[p]rovision'",
    "ps aux | grep provision | grep -v grep",
    'until grep -q "PLAY RECAP" run.log; do sleep 10; done',
]


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker() -> Iterator[None]:
    """get_data_layer() is a process-wide singleton (Plan 00116, Decision G)."""
    reset_data_layer()
    yield
    reset_data_layer()


@pytest.fixture
def handler() -> SelfMatchingProcessProbeHandler:
    return SelfMatchingProcessProbeHandler()


def _bash(command: str, transcript_path: str | None = None) -> dict[str, Any]:
    hook_input: dict[str, Any] = {"tool_name": ToolName.BASH, "tool_input": {"command": command}}
    if transcript_path is not None:
        hook_input["transcript_path"] = transcript_path
    return hook_input


class TestRegistration:
    def test_uses_the_shared_handler_id(self, handler: SelfMatchingProcessProbeHandler) -> None:
        assert handler.name == HandlerID.SELF_MATCHING_PROCESS_PROBE.display_name

    def test_priority_is_in_the_safety_band(self, handler: SelfMatchingProcessProbeHandler) -> None:
        assert handler.priority == Priority.SELF_MATCHING_PROCESS_PROBE
        assert PriorityRange.SAFETY_MIN <= handler.priority <= PriorityRange.SAFETY_MAX

    def test_is_terminal_because_it_denies(self, handler: SelfMatchingProcessProbeHandler) -> None:
        assert handler.terminal is True

    def test_declares_its_behaviour_in_tags(self, handler: SelfMatchingProcessProbeHandler) -> None:
        assert HandlerTag.SAFETY in handler.tags
        assert HandlerTag.BLOCKING in handler.tags


class TestMatches:
    @pytest.mark.parametrize("command", _DENY_CORPUS)
    def test_matches_the_deny_corpus(
        self, handler: SelfMatchingProcessProbeHandler, command: str
    ) -> None:
        assert handler.matches(_bash(command)) is True

    @pytest.mark.parametrize(
        "command",
        [
            "pgrep -f run_02",
            "watch pgrep -f run_02",
            "pgrep -f run_02 | xargs kill",
        ],
    )
    def test_matches_other_self_matching_shapes(
        self, handler: SelfMatchingProcessProbeHandler, command: str
    ) -> None:
        assert handler.matches(_bash(command)) is True

    @pytest.mark.parametrize(
        "command",
        [
            *_ALLOW_CORPUS,
            "ps -o pid= -p 1234",
            "ls -la",
            "git status",
            # An unresolvable pattern OUTSIDE a wait or a kill is not worth a
            # word: nothing can hang and nothing can be signalled.
            'pgrep -f "$pattern"',
        ],
    )
    def test_does_not_match_a_safe_command(
        self, handler: SelfMatchingProcessProbeHandler, command: str
    ) -> None:
        assert handler.matches(_bash(command)) is False

    def test_matches_an_uncapped_pid_wait_for_the_advisory(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        command = './job.bash > j.log 2>&1 & pid=$!; until ! kill -0 "$pid"; do sleep 5; done'
        assert handler.matches(_bash(command)) is True

    def test_does_not_match_prose_naming_the_incident(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        assert handler.matches(_bash(f'echo "{_INCIDENT}"')) is False

    def test_does_not_match_another_tool(self, handler: SelfMatchingProcessProbeHandler) -> None:
        hook_input = {"tool_name": "Write", "tool_input": {"file_path": "/x", "content": _INCIDENT}}
        assert handler.matches(hook_input) is False

    def test_does_not_match_an_empty_command(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        assert handler.matches(_bash("")) is False


class TestDenies:
    @pytest.mark.parametrize("command", _DENY_CORPUS)
    def test_the_deny_corpus_is_denied(
        self, handler: SelfMatchingProcessProbeHandler, command: str
    ) -> None:
        assert handler.handle(_bash(command)).decision == Decision.DENY

    def test_a_one_shot_self_match_is_denied_too(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        """Deny, do not advise: the report has an agent believing a hand-run probe twice."""
        assert handler.handle(_bash("pgrep -f run_02")).decision == Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            "watch pgrep -f run_02",
            "timeout 600 bash -c 'until ! pgrep -f run_02; do sleep 5; done'",
            "pgrep -f run_02 | xargs kill",
        ],
    )
    def test_other_self_matching_shapes_are_denied(
        self, handler: SelfMatchingProcessProbeHandler, command: str
    ) -> None:
        assert handler.handle(_bash(command)).decision == Decision.DENY

    def test_deny_names_the_rule(self, handler: SelfMatchingProcessProbeHandler) -> None:
        result = handler.handle(_bash(_INCIDENT))
        assert result.reason is not None
        assert RuleID.PGREP_SELF_MATCH in result.reason

    def test_deny_shows_the_concrete_rewrite(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        result = handler.handle(_bash(_INCIDENT))
        assert result.reason is not None
        assert 'pgrep -f "[p]rovision.bash target-host"' in result.reason

    @pytest.mark.parametrize(
        "expected",
        ["PLAY RECAP", "pgrep -x", "kill -0", "ps -o pid=", "run_in_background", "grep -v grep"],
    )
    def test_deny_names_every_documented_remedy(
        self, handler: SelfMatchingProcessProbeHandler, expected: str
    ) -> None:
        result = handler.handle(_bash(_INCIDENT))
        assert result.reason is not None
        assert expected in result.reason

    def test_pkill_deny_says_it_would_kill_this_shell(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        result = handler.handle(_bash('pkill -f "my-long-job"'))
        assert result.reason is not None
        assert "kill the shell running it" in result.reason
        assert 'pkill -f "[m]y-long-job"' in result.reason

    def test_ps_grep_deny_offers_the_grep_v_grep_remedy(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        result = handler.handle(_bash('ps aux | grep "provisioner" | wc -l'))
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "grep -v grep" in result.reason
        assert 'grep "[p]rovisioner"' in result.reason

    def test_repeat_fire_is_terse_but_still_carries_the_rewrite(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        transcript = "/tmp/transcript-00363.jsonl"
        first = handler.handle(_bash(_INCIDENT, transcript))
        second = handler.handle(_bash(_INCIDENT, transcript))
        assert first.reason is not None
        assert second.reason is not None
        assert len(second.reason) < len(first.reason)
        assert 'pgrep -f "[p]rovision.bash target-host"' in second.reason

    def test_a_pattern_with_no_mechanical_rewrite_still_denies(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        """A leading metacharacter has no bracket trick, so the advice falls back."""
        result = handler.handle(_bash('until ! pgrep -f ".*run_02"; do sleep 5; done'))
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "pgrep -x" in result.reason

    def test_a_deny_beats_an_advisory_in_the_same_command(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        """The incident is BOTH a self-match and an uncapped loop; the deny wins."""
        result = handler.handle(_bash(_INCIDENT))
        assert result.decision == Decision.DENY
        assert not result.context

    def test_bracket_tricked_probe_stays_denied_via_its_own_fallback_echo(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        """Reported bug, verbatim: bracketing the pattern is NOT sufficient here.

        Confirmed against a real `pgrep`: this shape is a genuine self-match,
        not a false positive — `pgrep -f '[p]ytest'` is not the tail of the
        statement (it has a real `|| echo` after it), so bash never
        exec-optimises it away, and the calling shell's own cmdline still
        spells "pytest" unescaped inside its own fallback message. The deny
        must stand; only the explanation should improve.
        """
        command = (
            "set -euo pipefail; kill 377690 405703; sleep 3; "
            "pgrep -f '[l]lm_qa' || echo \"no QA processes\"; "
            "pgrep -f '[p]ytest' || echo \"no pytest\""
        )
        result = handler.handle(_bash(command))
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert RuleID.PGREP_SELF_MATCH in result.reason
        # Names the ACTUAL offending text instead of silently offering
        # nothing: the probe's own pattern is already bracketed, so the
        # ordinary "REWRITE THIS COMMAND AS" rewrite has nothing left to say.
        assert "pytest" in result.reason
        assert "FIX THE OTHER TEXT" in result.reason
        assert 'REWRITE THIS COMMAND AS: pgrep -f "[p]ytest"' not in result.reason

    def test_bracket_tricked_probe_with_a_reworded_fallback_is_allowed(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        """The counterpart ALLOW: a fallback message that avoids the pattern."""
        command = 'pgrep -f "[p]ytest" || echo "no match"'
        result = handler.handle(_bash(command))
        assert result.decision == Decision.ALLOW


class TestAdvises:
    def test_an_uncapped_pid_wait_is_advisory(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        command = './job.bash > j.log 2>&1 & pid=$!; until ! kill -0 "$pid"; do sleep 5; done'
        result = handler.handle(_bash(command))
        assert result.decision == Decision.ALLOW
        assert result.context
        assert any(RuleID.UNBOUNDED_LIVENESS_LOOP in entry for entry in result.context)

    def test_the_loop_advisory_offers_a_bound(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        result = handler.handle(_bash('until ! kill -0 "$pid"; do sleep 5; done'))
        assert result.guidance is not None
        assert "timeout 3600" in result.guidance

    def test_a_capped_loop_says_nothing(self, handler: SelfMatchingProcessProbeHandler) -> None:
        command = 'until ! kill -0 "$pid"; do sleep 5; i=$((i+1)); done'
        assert handler.matches(_bash(command)) is False

    def test_a_bracket_tricked_probe_in_an_uncapped_loop_gets_the_loop_advisory_only(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        """Rule A is satisfied by the rewrite; Rule C is about the loop, not the probe."""
        result = handler.handle(_bash('until ! pgrep -f "[r]un_02" >/dev/null; do sleep 30; done'))
        assert result.decision == Decision.ALLOW
        assert [RuleID.UNBOUNDED_LIVENESS_LOOP in entry for entry in result.context] == [True]

    def test_an_unresolvable_pattern_in_a_loop_advises_rather_than_denies(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        """The daemon cannot read what `$job` expands to, so it must not deny."""
        result = handler.handle(_bash('until ! pgrep -f "$job"; do sleep 30; done'))
        assert result.decision == Decision.ALLOW
        assert any(RuleID.PGREP_UNRESOLVED_PATTERN in entry for entry in result.context)

    def test_an_unresolvable_pkill_pattern_advises(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        result = handler.handle(_bash('pkill -f "$job"'))
        assert result.decision == Decision.ALLOW
        assert result.context

    def test_two_advisory_rules_are_both_taught_once_each(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        result = handler.handle(_bash('until ! pgrep -f "$job"; do sleep 30; done'))
        assert result.guidance is not None
        assert RuleID.PGREP_UNRESOLVED_PATTERN in result.guidance
        assert RuleID.UNBOUNDED_LIVENESS_LOOP in result.guidance
        assert result.guidance.count(RuleID.UNBOUNDED_LIVENESS_LOOP) == 1


class TestWrapperPidWaits:
    """Rule B: `$!` after a forking wrapper names the wrapper, not the job.

    The incident's FIRST waiter, which fired immediately and reported the job
    finished while it was in its fourth minute. `setsid` denies: its parent
    exits at once, so the wait is over before it starts. The rest advise —
    whether they hand the pid on or keep it turns on what they were asked to
    run, and the command text does not say which.
    """

    _SETSID = (
        "setsid nohup ./job.bash > j.log 2>&1 & sleep 1; " "until ! kill -0 $! ; do sleep 5; done"
    )

    def test_the_setsid_waiter_is_denied(self, handler: SelfMatchingProcessProbeHandler) -> None:
        assert handler.handle(_bash(self._SETSID)).decision == Decision.DENY

    def test_the_setsid_waiter_matches(self, handler: SelfMatchingProcessProbeHandler) -> None:
        assert handler.matches(_bash(self._SETSID)) is True

    def test_the_deny_names_the_rule_and_the_wrapper(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        result = handler.handle(_bash(self._SETSID))
        assert result.reason is not None
        assert RuleID.WAIT_ON_WRAPPER_PID in result.reason
        assert "setsid" in result.reason

    @pytest.mark.parametrize(
        "expected",
        ["echo $! > job.pid", "pgrep -P", "MARKER", "run_in_background"],
    )
    def test_the_deny_names_every_remedy(
        self, handler: SelfMatchingProcessProbeHandler, expected: str
    ) -> None:
        result = handler.handle(_bash(self._SETSID))
        assert result.reason is not None
        assert expected in result.reason

    @pytest.mark.parametrize(
        "command",
        [
            "nohup sh -c './job.bash > j.log 2>&1' & wait $!",
            "nohup bash -c './job.bash' & wait $!",
            "timeout 600 ./job.bash & wait $!",
            "env FOO=1 ./job.bash & wait $!",
        ],
    )
    def test_a_non_detaching_wrapper_advises_rather_than_denies(
        self, handler: SelfMatchingProcessProbeHandler, command: str
    ) -> None:
        result = handler.handle(_bash(command))
        assert result.decision == Decision.ALLOW
        assert any(RuleID.WAIT_ON_WRAPPER_PID in entry for entry in result.context)

    def test_the_advisory_teaches_the_remedies_too(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        result = handler.handle(_bash("timeout 600 ./job.bash & wait $!"))
        assert result.guidance is not None
        assert "pgrep -P" in result.guidance

    @pytest.mark.parametrize(
        "command",
        [
            # The allow corpus: no wrapper, so `$!` is the job's own pid.
            './job.bash > j.log 2>&1 & pid=$!; until ! kill -0 "$pid"; do sleep 5; done',
            # `nohup` handed a command execs in place and keeps the pid.
            "nohup ./job.bash & pid=$!",
            # `setsid -w` waits for its child, so the wrapper outlives the job.
            "setsid -w ./job.bash & wait $!",
        ],
    )
    def test_a_pid_that_really_is_the_job_is_never_flagged_by_rule_b(
        self, handler: SelfMatchingProcessProbeHandler, command: str
    ) -> None:
        result = handler.handle(_bash(command))
        assert result.decision == Decision.ALLOW
        assert not any(RuleID.WAIT_ON_WRAPPER_PID in entry for entry in result.context or [])

    def test_a_captured_wrapper_pid_is_followed_through_its_variable(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        command = 'setsid ./job.bash & pid=$!; until ! kill -0 "$pid"; do sleep 5; done'
        result = handler.handle(_bash(command))
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "$pid" in result.reason

    def test_the_self_match_deny_still_wins_when_both_fire(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        """Rule A names a concrete rewrite, so it is the more useful denial."""
        command = "setsid ./job.bash & pgrep -f job.bash; kill -0 $!"
        result = handler.handle(_bash(command))
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert RuleID.PGREP_SELF_MATCH in result.reason


class TestAllows:
    @pytest.mark.parametrize("command", _ALLOW_CORPUS)
    def test_the_allow_corpus_is_allowed_silently(
        self, handler: SelfMatchingProcessProbeHandler, command: str
    ) -> None:
        result = handler.handle(_bash(command))
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_waiting_on_a_log_marker_is_never_flagged(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        """This is the remedy the deny message recommends; flagging it would be absurd."""
        result = handler.handle(_bash('until grep -q "PLAY RECAP" run.log; do sleep 10; done'))
        assert result.decision == Decision.ALLOW
        assert not result.context


class TestDeclaredSurface:
    def test_get_rules_declares_every_rule_id(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        rules = handler.get_rules()
        assert all(isinstance(rule, Rule) for rule in rules)
        assert {rule.rule_id for rule in rules} == {
            RuleID.PGREP_SELF_MATCH,
            RuleID.UNBOUNDED_LIVENESS_LOOP,
            RuleID.PGREP_UNRESOLVED_PATTERN,
            RuleID.WAIT_ON_WRAPPER_PID,
        }

    def test_claude_md_guidance_teaches_the_wrapper_pid_trap(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "setsid" in guidance
        assert "job.pid" in guidance

    def test_claude_md_guidance_teaches_the_bracket_trick(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert HandlerID.SELF_MATCHING_PROCESS_PROBE.config_key in guidance
        assert "[p]rovision.bash" in guidance
        assert "PLAY RECAP" in guidance

    def test_acceptance_tests_cover_deny_advisory_and_allow(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        tests = handler.get_acceptance_tests()
        assert any(
            test.test_type == TestType.BLOCKING and test.expected_decision == Decision.DENY
            for test in tests
        )
        assert any(
            test.expected_decision == Decision.ALLOW and test.expected_message_patterns
            for test in tests
        )
        assert any(
            test.expected_decision == Decision.ALLOW and not test.expected_message_patterns
            for test in tests
        )

    def test_acceptance_tests_declare_a_bash_payload(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        for test in handler.get_acceptance_tests():
            assert test.tool_payload is not None
            assert test.tool_payload.tool_name == ToolName.BASH

    def test_every_acceptance_test_produces_its_declared_verdict(
        self, handler: SelfMatchingProcessProbeHandler
    ) -> None:
        """The same contract `tests/integration/test_acceptance_contract.py` enforces."""
        for test in handler.get_acceptance_tests():
            assert test.tool_payload is not None
            hook_input = _bash(test.tool_payload.tool_input["command"])
            if not handler.matches(hook_input):
                assert test.expected_decision == Decision.ALLOW, test.title
                assert not test.expected_message_patterns, test.title
                continue
            result = handler.handle(hook_input)
            assert result.decision == test.expected_decision, test.title
            haystack = "\n".join(
                part for part in [result.reason, result.guidance, *(result.context or [])] if part
            )
            for pattern in test.expected_message_patterns:
                assert re.search(pattern, haystack), f"{test.title}: {pattern}"

    def test_relevance_is_universal(self, handler: SelfMatchingProcessProbeHandler) -> None:
        relevance = handler.get_relevance(
            RelevanceContext(project_root=Path("/nonexistent"), languages=frozenset())
        )
        assert relevance.applicable is True
        assert relevance.reason
