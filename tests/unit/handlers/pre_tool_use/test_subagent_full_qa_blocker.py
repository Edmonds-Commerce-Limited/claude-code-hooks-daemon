"""A sub-agent does not start a full QA run (Plan 00463).

The owner's measurement was the whole case for this handler: five
``llm_qa.py all`` runs executing at once, one per worktree, each about 25,700
tests over 15-20 minutes on eight cores. Each agent then re-ran the suite after
every fix round, and the coordinator ran it again before merging. The full gate
stays BEFORE the merge, but it moves to the coordinator, which runs it once per
delivery rather than once per fix round.

Three properties are pinned here, and each is a way the guard could fail
without looking broken:

1. **Parsed, not substring-matched.** A commit message, a ``grep`` or an
   ``echo`` that MENTIONS ``llm_qa.py all`` runs nothing. Denying it would
   teach agents that the guard is noise.
2. **Scoped by the chain, not by the handler.** ``scope=SUB`` carries the whole
   role test. That includes the synthetic guard, which keeps the acceptance
   harness's probes from ever being denied as though they were a sub-agent.
3. **A deny names the way forward.** A refusal with no allowed alternative is
   the Plan 00460 defect, so the reason lists the project's targeted commands
   and says the coordinator runs the full gate.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.handler_scope import HandlerScope, scope_admits
from claude_code_hooks_daemon.daemon.synthetic_traffic import (
    PLAYBOOK_PROBE,
    SYNTHETIC_SOURCE_FIELD,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.subagent_full_qa_blocker import (
    FullQaPattern,
    SubagentFullQaBlockerHandler,
    find_full_qa_invocation,
    parse_full_qa_patterns,
)

#: This repository's own declaration, restated so the unit suite does not
#: depend on the YAML. The dogfood config is checked separately, by the
#: integration suites that load it.
_PYTEST_VALUE_FLAGS = [
    "-k",
    "-m",
    "-n",
    "-p",
    "-c",
    "-o",
    "-W",
    "--maxfail",
    "--deselect",
    "--ignore",
    "--ignore-glob",
    "--rootdir",
    "--tb",
    "--durations",
    "--basetemp",
    "--junitxml",
]

_REPO_PATTERNS: list[dict[str, Any]] = [
    {
        "id": "llm-qa-whole-suite",
        "command": "llm_qa.py",
        "full_args": ["all", "tests"],
        "read_only_flags": ["--read-only", "--help", "-h"],
    },
    {"id": "run-all", "command": "run_all.sh"},
    {"id": "run-tests", "command": "run_tests.sh"},
    {"id": "validate-worktrees", "command": "validate_worktrees.sh"},
    {
        "id": "pytest-whole-suite",
        "command": "pytest",
        "full_args": ["tests", "tests/unit", "."],
        "bare_is_full": True,
        "value_flags": _PYTEST_VALUE_FLAGS,
        "read_only_flags": ["--collect-only", "--co", "--help", "-h", "--version"],
    },
]

_TARGETED = [
    "./scripts/qa/llm_qa.py changed",
    "./scripts/qa/llm_qa.py <tool> [<tool> ...]",
    "pytest <explicit test files or directories>",
]


def _handler(
    patterns: list[dict[str, Any]] | None = None,
    targeted: list[str] | None = None,
) -> SubagentFullQaBlockerHandler:
    handler = SubagentFullQaBlockerHandler()
    handler._full_qa_patterns = _REPO_PATTERNS if patterns is None else patterns
    handler._targeted_qa_commands = _TARGETED if targeted is None else targeted
    return handler


def _bash(command: str, **extra: Any) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        **extra,
    }


def _patterns() -> list[FullQaPattern]:
    patterns, problems = parse_full_qa_patterns(_REPO_PATTERNS)
    assert not problems, problems
    return patterns


# ── What counts as a full run ──────────────────────────────────────────────

_FULL_RUNS: list[tuple[str, str]] = [
    ("./scripts/qa/llm_qa.py all", "llm-qa-whole-suite"),
    ("scripts/qa/llm_qa.py all", "llm-qa-whole-suite"),
    ("python3 scripts/qa/llm_qa.py all", "llm-qa-whole-suite"),
    ("untracked/venv/bin/python ./scripts/qa/llm_qa.py all", "llm-qa-whole-suite"),
    ("./scripts/qa/llm_qa.py tests", "llm-qa-whole-suite"),
    ("./scripts/qa/llm_qa.py lint all", "llm-qa-whole-suite"),
    ("cd /srv/wt && ./scripts/qa/llm_qa.py all", "llm-qa-whole-suite"),
    (
        "set -o pipefail; ./scripts/qa/llm_qa.py all 2>&1 | bin/echd-capture 20",
        "llm-qa-whole-suite",
    ),
    (
        "timeout 3600 ./scripts/qa/llm_qa.py all > untracked/scratch/qa.txt 2>&1",
        "llm-qa-whole-suite",
    ),
    ("nohup ./scripts/qa/llm_qa.py all > qa.log 2>&1 &", "llm-qa-whole-suite"),
    ('./scripts/qa/llm_qa.py all; echo "QA_EXIT=$?"', "llm-qa-whole-suite"),
    ("bash -c './scripts/qa/llm_qa.py all'", "llm-qa-whole-suite"),
    ("(cd /srv/wt && ./scripts/qa/llm_qa.py all)", "llm-qa-whole-suite"),
    ("echo $(./scripts/qa/llm_qa.py all)", "llm-qa-whole-suite"),
    ("./scripts/qa/llm_qa.py \\\n  all", "llm-qa-whole-suite"),
    ("./scripts/qa/run_all.sh", "run-all"),
    ("bash scripts/qa/run_all.sh", "run-all"),
    ("./scripts/qa/run_tests.sh", "run-tests"),
    ("./scripts/validate_worktrees.sh", "validate-worktrees"),
    ("pytest", "pytest-whole-suite"),
    ("pytest -x -q", "pytest-whole-suite"),
    ("pytest tests/", "pytest-whole-suite"),
    ("pytest tests", "pytest-whole-suite"),
    ("pytest ./tests/", "pytest-whole-suite"),
    ("pytest tests/unit", "pytest-whole-suite"),
    ("pytest tests/unit/", "pytest-whole-suite"),
    ("pytest .", "pytest-whole-suite"),
    ("pytest /srv/project/tests", "pytest-whole-suite"),
    ("python -m pytest tests/", "pytest-whole-suite"),
    ("untracked/venv/bin/python -m pytest -q tests/", "pytest-whole-suite"),
    ("pytest -k handler", "pytest-whole-suite"),
    ("pytest tests/ -k handler", "pytest-whole-suite"),
    ("pytest tests/unit/handlers/test_x.py tests/", "pytest-whole-suite"),
    ("FOO=1 pytest tests/", "pytest-whole-suite"),
    ("env PYTHONPATH=src pytest", "pytest-whole-suite"),
    ("uv run pytest", "pytest-whole-suite"),
    ("sudo -E pytest tests/", "pytest-whole-suite"),
]

_NOT_FULL_RUNS: list[str] = [
    "./scripts/qa/llm_qa.py lint type_check",
    "./scripts/qa/llm_qa.py changed",
    "./scripts/qa/llm_qa.py --read-only all",
    "./scripts/qa/llm_qa.py all --read-only",
    "./scripts/qa/llm_qa.py",
    "./scripts/qa/llm_qa.py lint > untracked/scratch/lint.txt 2>&1",
    "./scripts/qa/run_shell_check.sh",
    "./scripts/qa/run_lint.sh",
    "pytest tests/unit/handlers/x.py",
    "pytest tests/unit/handlers/",
    "pytest tests/unit/handlers/pre_tool_use/test_x.py::TestA::test_b -v",
    "python -m pytest tests/unit/core tests/unit/config -q",
    "pytest -k handler tests/unit/handlers",
    "pytest --collect-only -q",
    "pytest --co",
    # Mentions, not invocations: the guard parses, it does not substring-match.
    'grep -rn "llm_qa.py all" CLAUDE/',
    "grep -rn llm_qa.py all",
    'git commit -m "the coordinator runs llm_qa.py all"',
    "git commit -F - <<'EOF'\nrun ./scripts/qa/llm_qa.py all\nEOF",
    'echo "./scripts/qa/llm_qa.py all"',
    "cat scripts/qa/run_all.sh",
    "shellcheck scripts/qa/run_all.sh",
    "git add scripts/qa/run_all.sh scripts/qa/llm_qa.py",
    "git log --oneline -- scripts/qa/run_tests.sh",
    "python3 -c \"print('llm_qa.py all')\"",
    "ls tests/",
    "mypy tests/",
]


class TestWhatCountsAsAFullRun:
    @pytest.mark.parametrize(("command", "pattern_id"), _FULL_RUNS)
    def test_a_full_run_is_found(self, command: str, pattern_id: str) -> None:
        match = find_full_qa_invocation(command, _patterns())
        assert match is not None, command
        assert match.pattern_id == pattern_id

    @pytest.mark.parametrize("command", _NOT_FULL_RUNS)
    def test_a_targeted_run_or_a_mention_is_not(self, command: str) -> None:
        assert find_full_qa_invocation(command, _patterns()) is None, command

    def test_no_patterns_find_nothing(self) -> None:
        """Inert until configured: there is no built-in notion of 'full'."""
        assert find_full_qa_invocation("./scripts/qa/llm_qa.py all", []) is None


class TestThePatternShapes:
    def test_an_absent_full_args_makes_every_invocation_full(self) -> None:
        patterns, _ = parse_full_qa_patterns([{"id": "x", "command": "make-check"}])
        assert find_full_qa_invocation("make-check --fast", patterns) is not None

    def test_bare_is_not_full_unless_declared(self) -> None:
        patterns, _ = parse_full_qa_patterns(
            [{"id": "x", "command": "runner", "full_args": ["everything"]}]
        )
        assert find_full_qa_invocation("runner", patterns) is None
        assert find_full_qa_invocation("runner everything", patterns) is not None

    def test_a_read_only_flag_given_as_key_equals_value_still_counts(self) -> None:
        patterns, _ = parse_full_qa_patterns(
            [{"id": "x", "command": "runner", "read_only_flags": ["--report"]}]
        )
        assert find_full_qa_invocation("runner --report=json", patterns) is None

    def test_a_value_flag_does_not_swallow_a_key_equals_value_form(self) -> None:
        """``--ignore=path`` carries its value; the next word is still a path."""
        patterns, _ = parse_full_qa_patterns(
            [
                {
                    "id": "x",
                    "command": "pytest",
                    "full_args": ["tests"],
                    "bare_is_full": True,
                    "value_flags": ["--ignore"],
                }
            ]
        )
        assert (
            find_full_qa_invocation("pytest --ignore=tests/slow tests/unit/x.py", patterns) is None
        )


class TestConfigParsing:
    def test_the_repo_patterns_parse_cleanly(self) -> None:
        patterns, problems = parse_full_qa_patterns(_REPO_PATTERNS)
        assert problems == []
        assert [p.pattern_id for p in patterns] == [p["id"] for p in _REPO_PATTERNS]

    @pytest.mark.parametrize(
        "entry",
        [
            {"command": "pytest"},
            {"id": "x"},
            {"id": "", "command": "pytest"},
            {"id": "x", "command": "pytest", "full_args": "tests"},
            {"id": "x", "command": "pytest", "bare_is_full": "yes"},
            {"id": "x", "command": "pytest", "surprise": True},
            "pytest",
        ],
    )
    def test_a_malformed_entry_is_reported_and_skipped(self, entry: Any) -> None:
        valid = {"id": "ok", "command": "run_all.sh"}
        patterns, problems = parse_full_qa_patterns([entry, valid])
        assert [p.pattern_id for p in patterns] == ["ok"]
        assert len(problems) == 1

    def test_a_non_list_is_reported(self) -> None:
        patterns, problems = parse_full_qa_patterns({"id": "x", "command": "pytest"})
        assert patterns == []
        assert problems

    def test_none_is_an_empty_declaration(self) -> None:
        assert parse_full_qa_patterns(None) == ([], [])

    def test_duplicate_ids_are_reported(self) -> None:
        entry = {"id": "x", "command": "pytest"}
        patterns, problems = parse_full_qa_patterns([entry, dict(entry)])
        assert len(patterns) == 1
        assert problems


# ── The handler ────────────────────────────────────────────────────────────


class TestTheScopeCarriesTheRoleTest:
    """Main thread vs sub-agent is decided by the chain, never re-derived here."""

    def test_the_handler_is_scoped_to_sub(self) -> None:
        assert SubagentFullQaBlockerHandler().scope is HandlerScope.SUB

    def test_a_subagent_event_is_admitted(self) -> None:
        event = _bash("./scripts/qa/llm_qa.py all", agent_id="aplan463-impl-84165102c3e9edf0")
        assert scope_admits(SubagentFullQaBlockerHandler().scope, event) is True

    def test_a_main_thread_event_is_not_admitted(self) -> None:
        """The coordinator's full gate must draw nothing at all."""
        event = _bash("./scripts/qa/llm_qa.py all")
        assert scope_admits(SubagentFullQaBlockerHandler().scope, event) is False

    def test_a_synthetic_event_is_not_admitted_even_with_an_agent_id(self) -> None:
        event = _bash(
            "./scripts/qa/llm_qa.py all",
            agent_id="a-probe",
            **{SYNTHETIC_SOURCE_FIELD: PLAYBOOK_PROBE},
        )
        assert scope_admits(SubagentFullQaBlockerHandler().scope, event) is False

    def test_the_handler_does_not_read_agent_id_itself(self) -> None:
        """No agent_id in the payload, and it still matches: admission is not its job."""
        assert _handler().matches(_bash("./scripts/qa/llm_qa.py all")) is True


class TestWhatTheHandlerMatches:
    def test_a_full_run_matches(self) -> None:
        assert _handler().matches(_bash("./scripts/qa/llm_qa.py all")) is True

    def test_a_targeted_run_does_not_match(self) -> None:
        assert _handler().matches(_bash("./scripts/qa/llm_qa.py lint type_check")) is False

    def test_a_non_bash_tool_does_not_match(self) -> None:
        event = {"tool_name": "Write", "tool_input": {"content": "./scripts/qa/llm_qa.py all"}}
        assert _handler().matches(event) is False

    def test_an_empty_command_does_not_match(self) -> None:
        assert _handler().matches(_bash("")) is False

    def test_an_unconfigured_handler_matches_nothing(self) -> None:
        assert _handler(patterns=[]).matches(_bash("./scripts/qa/llm_qa.py all")) is False

    def test_a_config_change_after_first_use_is_honoured(self) -> None:
        """Options arrive by setattr after construction; parsing must not freeze the first view."""
        handler = _handler(patterns=[])
        assert handler.matches(_bash("./scripts/qa/run_all.sh")) is False
        handler._full_qa_patterns = _REPO_PATTERNS
        assert handler.matches(_bash("./scripts/qa/run_all.sh")) is True


class TestTheDenial:
    def _reason(self, command: str, targeted: list[str] | None = None) -> str:
        result = _handler(targeted=targeted).handle(_bash(command))
        assert result.decision is Decision.DENY
        return result.reason or ""

    def test_it_denies_with_the_rule_id(self) -> None:
        assert RuleID.SUBAGENT_FULL_QA in self._reason("./scripts/qa/llm_qa.py all")

    def test_the_reason_says_the_coordinator_runs_the_full_gate(self) -> None:
        assert "coordinator" in self._reason("./scripts/qa/llm_qa.py all").lower()

    def test_the_reason_names_every_configured_targeted_form(self) -> None:
        reason = self._reason("./scripts/qa/llm_qa.py all")
        for command in _TARGETED:
            assert command in reason

    def test_the_reason_names_the_pattern_that_matched(self) -> None:
        assert "pytest-whole-suite" in self._reason("pytest tests/")

    def test_without_declared_targeted_forms_it_still_names_a_way_forward(self) -> None:
        reason = self._reason("./scripts/qa/llm_qa.py all", targeted=[])
        assert "explicit" in reason.lower()

    def test_handle_on_a_command_it_does_not_match_allows(self) -> None:
        """handle() re-derives the match rather than trusting a stale matches() call."""
        result = _handler().handle(_bash("./scripts/qa/llm_qa.py lint"))
        assert result.decision is Decision.ALLOW

    def test_get_rules_declares_the_rule(self) -> None:
        assert [rule.rule_id for rule in _handler().get_rules()] == [RuleID.SUBAGENT_FULL_QA]


class TestDefaultsAndPosture:
    def test_off_by_default(self) -> None:
        """A client's full-QA commands cannot be known from here, so it ships opt-in."""
        assert SubagentFullQaBlockerHandler().get_default_enabled() is False

    def test_an_empty_declaration_is_reported_not_silent(self, tmp_path: Any) -> None:
        status = _handler(patterns=[]).get_enforcement_status(tmp_path)
        assert status
        assert "full_qa_patterns" in status[0]

    def test_a_malformed_entry_is_reported(self, tmp_path: Any) -> None:
        handler = _handler(patterns=[{"id": "x"}, *_REPO_PATTERNS])
        status = handler.get_enforcement_status(tmp_path)
        assert any("command" in line for line in status)

    def test_a_clean_declaration_reports_nothing(self, tmp_path: Any) -> None:
        assert _handler().get_enforcement_status(tmp_path) == []


class TestTheAcceptanceTestsRunInASubagentContext:
    """The live harness marks every probe synthetic, and a SUB-scoped handler
    declines a synthetic event by construction. So the probes are declared as
    raw ``hook_input`` carrying an ``agent_id``: the in-process contract test
    drives the configured handler with them, and the live harness skips them
    rather than observing a vacuous ALLOW."""

    def test_there_is_a_deny_and_a_near_miss_allow(self) -> None:
        decisions = {t.expected_decision for t in _handler().get_acceptance_tests()}
        assert decisions == {Decision.DENY, Decision.ALLOW}

    def test_every_probe_is_a_subagent_payload(self) -> None:
        for test in _handler().get_acceptance_tests():
            assert test.hook_input is not None, test.title
            assert test.hook_input.get("agent_id"), test.title
