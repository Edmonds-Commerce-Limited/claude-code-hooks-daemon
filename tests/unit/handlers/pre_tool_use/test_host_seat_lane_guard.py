"""Tests for HostSeatLaneGuardHandler (Plan 00635).

A session holding a teamchat seat whose duty in ANY held team is ``host``
(owner ruling lts-infra Q62/Q64 D3) runs no test, build, lint or QA command:
host seats are for deployment and triage. An unreadable ``whoami`` means the
duty is unknown and the guard stays armed. No team means no change at all.

Injection seams the handler exposes for these tests:

- ``_mode``: ``off`` | ``advise`` | ``block`` (option ``mode``)
- ``_resolver``: anything with ``resolve(signals) -> SeatContext``; built
  lazily from ``_team_seat`` when None
"""

from __future__ import annotations

import builtins
import os
import subprocess
from typing import Any

import pytest
from tests.support import teamchat as fx

from claude_code_hooks_daemon.constants import HandlerTag, HookInputField
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use import host_seat_lane_guard as module
from claude_code_hooks_daemon.handlers.pre_tool_use.host_seat_lane_guard import (
    HostSeatLaneGuardHandler,
    is_lane_command,
)
from claude_code_hooks_daemon.utils.teamchat_seat import (
    ProbeReason,
    SeatContext,
    SessionSignals,
    parse_whoami,
)

# Plain strings handed to a fake resolver: nothing is created or opened there.
RUNTIME = "/tmp/teamchat/run-a"
KIT = "/opt/teamchat-kit"
PYTEST = "pytest tests/unit"

HOST = parse_whoami(fx.HOST_DUTY)
HOST_AS_COORDINATOR = parse_whoami(fx.HOST_AS_COORDINATOR)
WORKER = parse_whoami(fx.WORKER_ONLY)
COORDINATOR = parse_whoami(fx.COORDINATOR_ONLY)
OTHER_DUTY = parse_whoami(fx.UNKNOWN_DUTY)
MULTI_TEAM = parse_whoami(fx.MULTI_TEAM)
NULL_DUTY = parse_whoami(fx.ROLE_NULL)
WORKER_NULL_DUTY = parse_whoami(fx.whoami(fx.seat("alpha", "worker", duty=None)))
NO_DUTY_KEY = parse_whoami(
    fx.whoami(
        {"team": "alpha", "handle": "@example.1+local.container:alpha.test", "role": "worker"}
    )
)
GARBAGE_DUTY = parse_whoami(fx.whoami(fx.seat("alpha", "worker", duty="ho st!")))
HOST_AND_NULL_DUTY = parse_whoami(
    fx.whoami(fx.seat("alpha", "worker", duty="host"), fx.seat("beta", "worker", duty=None))
)
NOT_JSON = parse_whoami(fx.NOT_JSON)
NO_TEAMS = parse_whoami(fx.NO_TEAMS)
UNRESOLVED = SeatContext.unresolved(ProbeReason.COMMAND_TIMEOUT)
ABSENT = SeatContext.absent(ProbeReason.NO_SESSION)

_NO_ANSWER = "gave no answer"


def bash(
    command: str, *, runtime: str = RUNTIME, session: str = "s1", **extra: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "hook_event_name": "PreToolUse",
        "session_id": session,
        HookInputField.TOOL_NAME: "Bash",
        HookInputField.TOOL_INPUT: {"command": command},
        HookInputField.TEAMCHAT_KIT: KIT,
        **extra,
    }
    if runtime:
        payload[HookInputField.TEAMCHAT_RUNTIME] = runtime
    return payload


def subagent(command: str) -> dict[str, Any]:
    return bash(command, agent_id="a1b2c3d4e5f6a7b8c")


class FakeResolver:
    def __init__(self, context: SeatContext | Exception) -> None:
        self._context = context
        self.calls: list[SessionSignals] = []

    def resolve(self, signals: SessionSignals, **_: Any) -> SeatContext:
        self.calls.append(signals)
        if isinstance(self._context, Exception):
            raise self._context
        return self._context


def make(
    context: SeatContext | Exception = HOST, *, mode: str = "block"
) -> tuple[HostSeatLaneGuardHandler, FakeResolver]:
    handler = HostSeatLaneGuardHandler()
    resolver = FakeResolver(context)
    handler._mode = mode
    handler._resolver = resolver
    return handler, resolver


def _text(result: Any) -> str:
    return " ".join([str(result.reason or ""), *[str(line) for line in result.context or []]])


# --- identity --------------------------------------------------------------------


class TestIdentity:
    def test_priority_is_in_the_safety_band_before_the_long_running_guard(self) -> None:
        assert 10 <= HostSeatLaneGuardHandler().priority <= 21

    def test_tags_are_workflow_blocking_terminal(self) -> None:
        tags = set(HostSeatLaneGuardHandler().tags)
        assert {HandlerTag.WORKFLOW, HandlerTag.BLOCKING, HandlerTag.TERMINAL} <= tags

    def test_declares_team_seat_for_injection(self) -> None:
        assert hasattr(HostSeatLaneGuardHandler(), "_team_seat")

    def test_ships_in_advise_mode(self) -> None:
        assert HostSeatLaneGuardHandler()._mode == "advise"

    @pytest.mark.parametrize(
        ("options", "key"),
        [({"mode": "loud"}, "mode"), ({"extra_lane_patterns": ["("]}, "extra_lane_patterns")],
    )
    def test_bad_options_are_named(self, options: dict[str, Any], key: str) -> None:
        assert key in HostSeatLaneGuardHandler.validate_options(options)

    def test_good_options_pass(self) -> None:
        options = {"mode": "block", "extra_lane_patterns": [r"^deno\s+test\b"]}
        assert HostSeatLaneGuardHandler.validate_options(options) == {}


# --- lane classification (pure) -----------------------------------------------------


class TestLaneCommands:
    @pytest.mark.parametrize(
        "command",
        [
            "pytest tests/",
            "python3 -m pytest -x",
            "uv run pytest",
            "npm test",
            "npm run test:unit",
            "yarn build",
            "npm run build",
            "npm run lint",
            "npx jest",
            "cargo test",
            "cargo build --release",
            "go test ./...",
            "go vet ./...",
            "tsc -p .",
            "make",
            "make test",
            "make -j4 build",
            "ruff check src",
            "mypy src",
            "eslint .",
            "black --check src",
            "shellcheck x.sh",
            "./scripts/qa/llm_qa.py changed",
            "bash scripts/qa/run_all.sh",
            "./scripts/qa/run_tests.sh",
            "python3 tests/test_thing.py",
            "sh -c 'pytest tests/'",
            "bash -c 'cd x && pytest'",
            "timeout 20 pytest tests/",
            "pytest tests/ &",
            "nice -n 19 pytest tests/",
            "python3 -m unittest discover",
            "echo start; pytest",
            '"pytest" tests/',
            "'pytest' tests/",
            "mvn test",
            "mvn verify",
            "gradle build",
            "./gradlew test",
            "mvn deploy && pytest",
            "./run_tests.sh",
            "./qa.sh",
        ],
    )
    def test_refused_shapes(self, command: str) -> None:
        assert is_lane_command(command) is True

    @pytest.mark.parametrize(
        "command",
        [
            "git status",
            "git pull",
            "ls -la",
            "journalctl -u app --since today",
            "systemctl restart app",
            "docker compose up -d",
            "docker build -t app .",
            "make deploy",
            "npm install",
            "pip install x",
            "apt-get install -y x",
            "gh run watch 1",
            "tail -f /var/log/app.log",
            "./deploy.sh production",
            "kubectl rollout status deploy/app",
            "echo pytest",
            "git commit -m 'run pytest later'",
            "cat latest.sh",
            "mvn deploy",
            "mvn clean deploy -DskipTests",
            "gradle publish",
            "./gradlew publish",
            "./deploy-qa.sh",
            "./deploy_test.sh",
            "./smoke_test.sh",
            "./test-connection.sh",
            "command -v pytest",
            "command -v make",
            "which pytest",
            "type pytest",
            "",
        ],
    )
    def test_untouched_shapes(self, command: str) -> None:
        assert is_lane_command(command) is False

    def test_extra_patterns_extend_the_lane(self) -> None:
        assert is_lane_command("deno test", extra_patterns=(r"^deno\s+test\b",)) is True
        assert is_lane_command("deno test") is False


# --- arming --------------------------------------------------------------------------


class TestArming:
    def test_no_runtime_is_silent_and_runs_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spawned: list[Any] = []
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: spawned.append(a))
        handler = HostSeatLaneGuardHandler()
        handler._mode = "block"
        assert handler.matches(bash(PYTEST, runtime="")) is False
        assert spawned == []

    def test_no_runtime_never_asks_the_resolver(self) -> None:
        handler, resolver = make()
        assert handler.matches(bash(PYTEST, runtime="")) is False
        assert resolver.calls == []

    @pytest.mark.parametrize("context", [HOST, HOST_AS_COORDINATOR])
    def test_host_duty_in_any_team_is_armed(self, context: SeatContext) -> None:
        handler, _ = make(context)
        assert handler.matches(bash(PYTEST)) is True

    @pytest.mark.parametrize("context", [WORKER, COORDINATOR, MULTI_TEAM, OTHER_DUTY])
    def test_other_duties_are_silent(self, context: SeatContext) -> None:
        handler, _ = make(context)
        assert handler.matches(bash(PYTEST)) is False

    @pytest.mark.parametrize("context", [ABSENT, NO_TEAMS])
    def test_no_team_is_silent(self, context: SeatContext) -> None:
        handler, _ = make(context)
        assert handler.matches(bash(PYTEST)) is False

    @pytest.mark.parametrize("context", [UNRESOLVED, NOT_JSON])
    def test_an_unreadable_probe_stays_armed(self, context: SeatContext) -> None:
        handler, _ = make(context)
        assert handler.matches(bash(PYTEST)) is True

    @pytest.mark.parametrize(
        "context",
        [NULL_DUTY, WORKER_NULL_DUTY, NO_DUTY_KEY, GARBAGE_DUTY],
        ids=["role-null", "worker-null-duty", "no-duty-key", "garbage-duty"],
    )
    def test_a_seat_with_no_declared_duty_is_silent(self, context: SeatContext) -> None:
        """Duty is a teams-only concept and may be null: only an explicit host arms."""
        handler, _ = make(context)
        assert handler.matches(bash(PYTEST)) is False
        result = handler.handle(bash(PYTEST))
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_host_in_one_team_and_null_duty_in_another_is_armed(self) -> None:
        """A null duty elsewhere must never disarm an explicit host."""
        handler, _ = make(HOST_AND_NULL_DUTY)
        assert handler.matches(bash(PYTEST)) is True
        text = _text(handler.handle(bash(PYTEST)))
        assert "holds a teamchat seat with duty host" in text
        assert "the guard stays armed" not in text

    def test_subagent_is_silent(self) -> None:
        handler, _ = make(HOST)
        assert handler.matches(subagent(PYTEST)) is False

    def test_non_lane_command_is_silent_for_a_host_seat(self) -> None:
        handler, _ = make(HOST)
        assert handler.matches(bash("systemctl restart app")) is False

    def test_not_bash_is_silent(self) -> None:
        handler, _ = make()
        payload = bash(PYTEST)
        payload[HookInputField.TOOL_NAME] = "Read"
        assert handler.matches(payload) is False

    def test_exception_before_arming_is_silent(self) -> None:
        handler, _ = make(RuntimeError("probe crashed"))
        assert handler.matches(bash(PYTEST)) is False

    def test_classify_failure_for_an_armed_seat_counts_as_lane(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(*_a: Any, **_k: Any) -> bool:
            raise RuntimeError("classifier crashed")

        monkeypatch.setattr(module, "is_lane_command", explode)
        handler, _ = make(HOST)
        assert handler.matches(bash(PYTEST)) is True
        result = handler.handle(bash(PYTEST))
        assert result.decision == Decision.DENY
        assert "classifier crashed" not in _text(result)

    def test_classify_failure_for_an_unarmed_seat_is_silent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(*_a: Any, **_k: Any) -> bool:
            raise RuntimeError("classifier crashed")

        monkeypatch.setattr(module, "is_lane_command", explode)
        handler, _ = make(WORKER)
        assert handler.matches(bash(PYTEST)) is False

    def test_mode_off_is_dormant(self) -> None:
        handler, resolver = make(mode="off")
        assert handler.is_dormant() is True
        assert handler.matches(bash(PYTEST)) is False
        assert resolver.calls == []

    @pytest.mark.parametrize("mode", ["advise", "block"])
    def test_mode_on_is_not_dormant(self, mode: str) -> None:
        handler, _ = make(mode=mode)
        assert handler.is_dormant() is False


# --- the decision --------------------------------------------------------------------


class TestDecision:
    def test_block_denies_and_names_the_lane(self) -> None:
        handler, _ = make(HOST)
        result = handler.handle(bash(PYTEST))
        assert result.decision == Decision.DENY
        assert "worker seat" in _text(result)
        assert "R-HOST-SEAT-LANE" in _text(result)

    def test_advise_allows_with_the_refusal_as_context(self) -> None:
        handler, _ = make(HOST, mode="advise")
        result = handler.handle(bash(PYTEST))
        assert result.decision == Decision.ALLOW
        assert "worker seat" in _text(result)

    def test_non_lane_command_passes_plainly(self) -> None:
        handler, _ = make(HOST)
        result = handler.handle(bash("systemctl restart app"))
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_unknown_duty_reports_no_answer_once_per_session(self) -> None:
        handler, _ = make(UNRESOLVED)
        first = handler.handle(bash(PYTEST))
        second = handler.handle(bash(PYTEST))
        other_session = handler.handle(bash(PYTEST, session="s2"))
        assert first.decision == second.decision == Decision.DENY
        assert _NO_ANSWER in _text(first)
        assert _NO_ANSWER not in _text(second)
        assert _NO_ANSWER in _text(other_session)

    def test_unknown_duty_refusal_never_claims_duty_host(self) -> None:
        handler, _ = make(UNRESOLVED)
        for _ in range(2):
            text = _text(handler.handle(bash(PYTEST)))
            # The rule's own summary names both cases; the situation line must not claim host.
            assert "holds a teamchat seat with duty host" not in text
            assert "cannot be read" in text
            assert "worker seat" in text

    def test_a_resolved_unknown_duty_is_never_refused(self) -> None:
        handler, _ = make(NULL_DUTY)
        for _ in range(2):
            result = handler.handle(bash(PYTEST))
            assert result.decision == Decision.ALLOW
            assert not result.context

    def test_lazy_resolver_is_built_from_team_seat(self) -> None:
        handler = HostSeatLaneGuardHandler()
        assert handler._resolver is None
        assert handler._seat_resolver() is handler._seat_resolver()

    def test_noted_sessions_are_bounded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(module, "_MAX_NOTED_SESSIONS", 2)
        handler, _ = make(UNRESOLVED)
        for session in ("a", "b", "c"):
            handler.handle(bash(PYTEST, session=session))
        assert len(handler._noted_sessions) <= 2

    def test_non_list_extra_patterns_are_named(self) -> None:
        problems = HostSeatLaneGuardHandler.validate_options({"extra_lane_patterns": "x"})
        assert "extra_lane_patterns" in problems

    def test_declared_host_never_reports_no_answer(self) -> None:
        handler, _ = make(HOST)
        assert _NO_ANSWER not in _text(handler.handle(bash(PYTEST)))

    def test_refusal_never_echoes_the_command(self) -> None:
        marker = "marker-0042-xyz"
        handler, _ = make(HOST)
        result = handler.handle(bash(f"pytest {marker}"))
        assert marker not in _text(result)

    def test_exception_after_arming_advises_in_advise(self) -> None:
        handler, _ = make(HOST, mode="advise")
        handler._resolver = FakeResolver(RuntimeError("resolver crashed"))
        result = handler.handle(bash(PYTEST))
        assert result.decision == Decision.ALLOW
        assert result.context
        assert "resolver crashed" not in _text(result)


# --- invariants --------------------------------------------------------------------


class TestInvariants:
    def test_nothing_under_the_run_dir_or_kit_is_opened(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        touched: list[str] = []

        def record(real: Any) -> Any:
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                path = str(args[0]) if args else ""
                if path.startswith((RUNTIME, KIT)):
                    touched.append(path)
                return real(*args, **kwargs)

            return wrapper

        monkeypatch.setattr(builtins, "open", record(builtins.open))
        monkeypatch.setattr(os, "stat", record(os.stat))
        monkeypatch.setattr(os, "scandir", record(os.scandir))
        for context in (HOST, UNRESOLVED, WORKER):
            handler, _ = make(context)
            payload = bash(PYTEST)
            if handler.matches(payload):
                handler.handle(payload)
        assert touched == []

    def test_acceptance_tests_are_declared(self) -> None:
        assert HostSeatLaneGuardHandler().get_acceptance_tests()

    def test_claude_md_guidance_names_the_lane(self) -> None:
        guidance = HostSeatLaneGuardHandler().get_claude_md() or ""
        assert "host" in guidance
        assert "worker seat" in guidance
