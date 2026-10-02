"""Integration test: the Plan 00479 usage-pause cycle through the daemon chain.

The acceptance run for Task 4.8 drove the three usage-pause handlers directly.
What it could not show is everything between a raw hook request and the wire
JSON: handler scope filtering (main thread vs subagent), priority ordering
against the other handlers on the same event, and the response formatter and
schema that turn a halting deny into top-level ``continue: false`` plus
``stopReason``. Here a controller is built the way daemon startup builds it
(``_build_initialised_controller`` from a real config file with a ``hosts:``
usage ceiling) and every step goes through ``process_request``.

Only the clock the gates read is substituted; the usage reading arrives as a
real Status event so the controller folds it into the snapshot itself.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.response_schemas import validate_response
from claude_code_hooks_daemon.daemon.cli import _build_initialised_controller
from claude_code_hooks_daemon.daemon.controller import DaemonController
from claude_code_hooks_daemon.handlers.pre_tool_use.usage_pause_tool_gate import (
    UsagePauseToolGateHandler,
)
from claude_code_hooks_daemon.handlers.stop.usage_pause_stop_gate import (
    UsagePauseStopGateHandler,
)
from claude_code_hooks_daemon.handlers.user_prompt_submit.usage_pause_gate import (
    UsagePauseGateHandler,
)
from claude_code_hooks_daemon.utils.usage_pause import pause_path
from claude_code_hooks_daemon.utils.usage_pause_gate import (
    RESUME_CRON_SCHEDULE,
    USAGE_RESUME_PROMPT,
    PauseEnvironment,
)

HOST = "p479-chain-host"
SESSION = "chain-0001"
CONTROL_SESSION = "chain-control"
AGENT_ID = "agent-chain-0001"
FIVE_HOURS = 5 * 3600

CONFIG_YAML = f"""\
version: "2.0"
daemon:
  idle_timeout_seconds: 600
  log_level: INFO
handlers: {{}}
hosts:
  chain-host:
    pattern: "{HOST}"
    usage_ceiling:
      max_used_percent: 80
persistent_crons:
  enabled: true
  jobs:
    - id: chain-job
      schedule: "17 * * * *"
      enabled: true
      description: "declared job for the chain test"
      prompt: "[tick:job:chain-job] do the declared thing"
"""

FAILSAFE_CRON = {
    "id": "cron-1",
    "schedule": "7 * * * *",
    "prompt": "[tick:failsafe]\nrecovery check",
    "recurring": True,
}
RESUME_CRON = {
    "id": "cron-2",
    "schedule": RESUME_CRON_SCHEDULE,
    "prompt": USAGE_RESUME_PROMPT,
    "recurring": True,
}


class Clock:
    """A mutable clock the usage-pause gates read instead of ``time.time``."""

    def __init__(self) -> None:
        self.now = time.time()

    def __call__(self) -> float:
        return self.now


class Chain:
    """A real controller plus the helpers every step needs."""

    def __init__(self, controller: DaemonController, project: Path, clock: Clock) -> None:
        self.controller = controller
        self.project = project
        self.clock = clock

    def send(self, event: str, hook_input: dict[str, Any]) -> dict[str, Any]:
        """One hook request through the whole dispatch path; the wire JSON."""
        payload = {"hook_event_name": event, "session_id": SESSION, **hook_input}
        return self.controller.process_request({"event": event, "hook_input": payload})

    def status(self, five_hour: float | None) -> dict[str, Any]:
        """A Status event, with a five_hour reading when given, and no rate_limits otherwise."""
        hook_input: dict[str, Any] = {
            "model": {"id": "x"},
            "workspace": {"current_dir": str(self.project)},
        }
        if five_hour is not None:
            hook_input["rate_limits"] = {
                "five_hour": {
                    "used_percentage": five_hour,
                    "resets_at": int(self.clock.now + FIVE_HOURS),
                }
            }
        return self.send("Status", hook_input)

    def prompt(self, text: str) -> dict[str, Any]:
        return self.send("UserPromptSubmit", {"prompt": text})

    def tool(self, name: str, tool_input: dict[str, Any], **extra: Any) -> dict[str, Any]:
        return self.send("PreToolUse", {"tool_name": name, "tool_input": tool_input, **extra})

    def stop(self, crons: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
        return self.send("Stop", {"stop_hook_active": False, "session_crons": crons, **extra})

    def record_exists(self, session_id: str = SESSION) -> bool:
        return pause_path(ProjectContext.daemon_untracked_dir(), session_id).exists()


def _git(project: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)


@pytest.fixture()
def chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Chain]:
    """A controller built by the daemon's own startup helper over a scratch project."""
    project = tmp_path / "project"
    (project / ".claude").mkdir(parents=True)
    _git(project, "init", "-q")
    _git(project, "remote", "add", "origin", "git@github.com:test/chain.git")
    config_path = project / ".claude" / "hooks-daemon.yaml"
    config_path.write_text(CONFIG_YAML)
    monkeypatch.setenv("HOOKS_DAEMON_HOSTNAME", HOST)

    reset_data_layer()
    ProjectContext.reset()
    ProjectContext.initialize(config_path)
    controller = _build_initialised_controller(Config.load(config_path), project)

    clock = Clock()
    env = PauseEnvironment(clock=clock)
    seen = 0
    for handlers in controller.get_router().get_all_handlers().values():
        for handler in handlers:
            if isinstance(handler, UsagePauseGateHandler):
                handler._clock = clock
                seen += 1
            elif isinstance(handler, (UsagePauseToolGateHandler, UsagePauseStopGateHandler)):
                handler._env = env
                seen += 1
    assert seen == 3, "the three usage-pause gates must all be registered on the chain"

    yield Chain(controller, project, clock)
    ProjectContext.reset()
    reset_data_layer()


def _permission(response: dict[str, Any]) -> str | None:
    output = response.get("hookSpecificOutput")
    return output.get("permissionDecision") if isinstance(output, dict) else None


def _text(response: dict[str, Any]) -> str:
    return json.dumps(response)


def _assert_halting_deny(response: dict[str, Any]) -> None:
    assert validate_response("PreToolUse", response) == []
    assert _permission(response) == "deny", response
    assert response.get("continue") is False, response
    stop_reason = response.get("stopReason")
    assert isinstance(stop_reason, str) and "usage ceiling" in stop_reason, response


def _pause_through_prompt(chain: Chain) -> None:
    chain.status(85.0)
    response = chain.prompt("please do the next thing")
    assert "USAGE CEILING REACHED" in _text(response), response
    assert chain.record_exists()


class TestStep1StatusThenPrompt:
    """Status at 85% against an 80% ceiling: the prompt carries the pause directive."""

    def test_directive_reaches_the_wire(self, chain: Chain) -> None:
        chain.status(85.0)

        response = chain.prompt("please do the next thing")

        assert validate_response("UserPromptSubmit", response) == []
        text = _text(response)
        assert "USAGE CEILING REACHED" in text
        assert "CronDelete" in text
        assert RESUME_CRON_SCHEDULE in text
        assert "five_hour" in text and "85" in text and "80" in text
        assert chain.record_exists()

    def test_second_prompt_while_paused_is_a_wire_block(self, chain: Chain) -> None:
        _pause_through_prompt(chain)

        response = chain.prompt("another prompt")

        assert validate_response("UserPromptSubmit", response) == []
        assert response.get("decision") == "block", response
        assert "Paused on" in _text(response)


class TestStep2PreToolUse:
    """The main thread is halted; the cron tools and subagents are not."""

    @pytest.mark.parametrize(
        "tool_input",
        [
            {"command": "ls"},
            {"command": "git reset --hard HEAD"},
            {"command": "sed -i s/a/b/ somefile"},
        ],
    )
    def test_main_thread_bash_is_a_halting_deny_no_other_handler_drops(
        self, chain: Chain, tool_input: dict[str, Any]
    ) -> None:
        _pause_through_prompt(chain)

        response = chain.tool("Bash", tool_input)

        _assert_halting_deny(response)

    def test_agent_dispatch_is_a_halting_deny(self, chain: Chain) -> None:
        _pause_through_prompt(chain)

        _assert_halting_deny(chain.tool("Agent", {"prompt": "do work"}))

    @pytest.mark.parametrize("tool", ["CronList", "CronDelete", "CronCreate"])
    def test_cron_tools_are_allowed_on_the_wire(self, chain: Chain, tool: str) -> None:
        _pause_through_prompt(chain)

        response = chain.tool(tool, {})

        assert validate_response("PreToolUse", response) == []
        assert _permission(response) != "deny", response
        assert "continue" not in response, response

    def test_subagent_payload_is_not_denied_by_the_pause(self, chain: Chain) -> None:
        _pause_through_prompt(chain)

        response = chain.tool("Bash", {"command": "ls"}, agent_id=AGENT_ID)

        assert validate_response("PreToolUse", response) == []
        assert _permission(response) != "deny", response
        assert "continue" not in response, response
        assert "usage ceiling" not in _text(response)

    def test_entry_by_tool_call_denies_first_without_a_halt_then_halts(self, chain: Chain) -> None:
        chain.status(85.0)

        first = chain.tool("Bash", {"command": "ls"})
        second = chain.tool("Bash", {"command": "ls"})

        assert validate_response("PreToolUse", first) == []
        assert _permission(first) == "deny", first
        assert "continue" not in first, first
        assert "USAGE CEILING REACHED" in _text(first)
        _assert_halting_deny(second)


class TestStep3Stop:
    """A paused stop is accepted only with exactly the resume cron in place."""

    def test_failsafe_plus_resume_blocks_and_only_resume_allows(self, chain: Chain) -> None:
        _pause_through_prompt(chain)

        blocked = chain.stop([FAILSAFE_CRON, RESUME_CRON])
        allowed = chain.stop([RESUME_CRON])

        assert validate_response("Stop", blocked) == []
        assert blocked.get("decision") == "block", blocked
        assert "USAGE PAUSE NOT COMPLETE" in _text(blocked)
        assert validate_response("Stop", allowed) == []
        assert allowed.get("decision") != "block", allowed

    def test_other_stop_handlers_stand_down_while_paused(
        self, chain: Chain, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Should I proceed with Phase 2?"}],
                    },
                }
            )
            + "\n"
        )
        # Control, before any usage reading exists so nothing pauses it: the same stop
        # IS blocked by auto_continue_stop and by cron_stop_enforcer for the declared job.
        control = chain.send(
            "Stop",
            {
                "session_id": CONTROL_SESSION,
                "stop_hook_active": False,
                "session_crons": [],
                "transcript_path": str(transcript),
            },
        )
        assert control.get("decision") == "block", control
        control_text = _text(control)
        assert "AUTO-CONTINUE" in control_text or "chain-job" in control_text, control

        _pause_through_prompt(chain)
        allowed = chain.stop([RESUME_CRON], transcript_path=str(transcript))

        assert validate_response("Stop", allowed) == []
        assert allowed.get("decision") != "block", allowed
        assert "AUTO-CONTINUE" not in _text(allowed)
        assert "chain-job" not in _text(allowed)

    def test_subagent_stop_is_not_blocked_by_the_main_thread_stop_gate(self, chain: Chain) -> None:
        _pause_through_prompt(chain)

        response = chain.send(
            "SubagentStop",
            {
                "agent_id": AGENT_ID,
                "stop_hook_active": False,
                "session_crons": [FAILSAFE_CRON, RESUME_CRON],
            },
        )

        assert validate_response("SubagentStop", response) == []
        assert "USAGE PAUSE" not in _text(response)


class TestStep4ResumeTick:
    """The resume cron's tick is refused before resume_at and lifts after it."""

    def test_early_tick_is_refused_at_zero_cost(self, chain: Chain) -> None:
        _pause_through_prompt(chain)

        response = chain.prompt(USAGE_RESUME_PROMPT)

        assert validate_response("UserPromptSubmit", response) == []
        assert response.get("decision") == "block", response
        assert "the pause holds" in _text(response)
        assert chain.record_exists()

    def test_tick_after_resume_at_with_usage_back_down_lifts(self, chain: Chain) -> None:
        _pause_through_prompt(chain)
        record = json.loads(pause_path(ProjectContext.daemon_untracked_dir(), SESSION).read_text())
        chain.clock.now = record["resume_at"] + 5
        chain.status(20.0)

        response = chain.prompt(USAGE_RESUME_PROMPT)

        assert validate_response("UserPromptSubmit", response) == []
        assert response.get("decision") != "block", response
        text = _text(response)
        assert "USAGE PAUSE LIFTED" in text
        assert "chain-job" in text
        assert not chain.record_exists()
        after = chain.tool("Bash", {"command": "ls"})
        assert "usage ceiling" not in _text(after), after
        assert "continue" not in after, after


class TestStep5NoRateLimits:
    """No usage data, no pause, on any of the three events."""

    def test_nothing_pauses_without_rate_limits(self, chain: Chain) -> None:
        chain.status(None)

        prompt = chain.prompt("hello")
        tool = chain.tool("Bash", {"command": "ls"})
        stop = chain.stop([])

        assert "USAGE CEILING" not in _text(prompt)
        assert prompt.get("decision") != "block", prompt
        assert "continue" not in tool, tool
        assert "usage ceiling" not in _text(tool)
        assert "USAGE PAUSE" not in _text(stop)
        assert not chain.record_exists()
