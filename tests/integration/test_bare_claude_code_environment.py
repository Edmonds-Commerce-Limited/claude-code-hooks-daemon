"""A bare Claude Code environment wakes no team handler (Plan 00474 R7).

Bare means: no ``TEAMCHAT_*`` or ``CCY_*`` in the environment, no teamchat
fields on the payload, and a project root with no ``.claude/ccy/``. Every
handler the registry would hand a ``team_seat`` block (the registry criterion:
it declares ``_team_seat``) is called with a payload that WOULD arm it in a
team, and must give no deny, no reason and no context, and spawn nothing.
``auto_continue_stop`` refuses a no-reason stop for every project, so only its
team-only wind-down note is checked.

The second half pins the rule table's cases B and C through a REAL resolver
(the arm-on-evidence logic lives there), with a control showing the same
payloads do speak for a resolved host or coordinator seat.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import pytest

from claude_code_hooks_daemon.config.models import TeamSeatConfig
from claude_code_hooks_daemon.constants import HookInputField
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry
from claude_code_hooks_daemon.utils import human_approval, teamchat_seat
from claude_code_hooks_daemon.utils.teamchat_seat import (
    CommandOutcome,
    CommandStatus,
    SeatContextResolver,
    reset_shared_resolvers,
)
from claude_code_hooks_daemon.utils.wind_down import WIND_DOWN_HEADING
from tests.support import teamchat as fx

#: Every handler carrying ``_team_seat`` today. A new one fails the pin until
#: it is given an arming payload below.
TEAM_HANDLER_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "AutoContinueStopHandler",
        "CiStateReadingHandler",
        "CoordinatorBoardHandler",
        "CoordinatorConductHandler",
        "HostSeatLaneGuardHandler",
        "HumanApprovalCheckHandler",
        "OwnerDirectivesRegisterHandler",
        "OwnerWaitStopGuardHandler",
    }
)
WIND_DOWN_ONLY: Final[str] = "AutoContinueStopHandler"
RUNTIME: Final[str] = "/run/user/1000/teamchat/s1"
KIT: Final[str] = "/opt/teamchat"
WAITING: Final[str] = "STOPPING BECAUSE: waiting on the owner's answers to Q61 and Q64."
NO_REASON: Final[str] = "Done for now."
_SCRUBBED_PREFIXES: Final[tuple[str, ...]] = ("TEAMCHAT_", "CCY_")

PayloadFactory = Callable[[Path], dict[str, Any]]


def _bash(command: str) -> PayloadFactory:
    def build(_root: Path) -> dict[str, Any]:
        return {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            HookInputField.TOOL_NAME: "Bash",
            HookInputField.TOOL_INPUT: {"command": command},
        }

    return build


def _gh_run_list_queued(_root: Path) -> dict[str, Any]:
    row = "\t".join(
        ["queued", "", "Merge", "QA", "main", "push", "1", "1s", "2026-01-01T00:00:00Z"]
    )
    return {
        "hook_event_name": "PostToolUse",
        "session_id": "s1",
        HookInputField.TOOL_NAME: "Bash",
        HookInputField.TOOL_INPUT: {"command": "gh run list --limit 5"},
        "tool_response": {"stdout": row, "stderr": "", "interrupted": False},
    }


def _session_start_resume(_root: Path) -> dict[str, Any]:
    return {"hook_event_name": "SessionStart", "session_id": "s1", "source": "resume"}


def _prompt(_root: Path) -> dict[str, Any]:
    return {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "s1",
        "prompt": "From now on, never push to main without asking me first.",
    }


def _stop(text: str) -> PayloadFactory:
    def build(root: Path) -> dict[str, Any]:
        transcript = root / "transcript.jsonl"
        entry = {
            "type": "message",
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
        }
        transcript.write_text(json.dumps(entry) + "\n", encoding="utf-8")
        return {
            "hook_event_name": "Stop",
            "session_id": "s1",
            "stop_hook_active": False,
            "transcript_path": str(transcript),
            HookInputField.BACKGROUND_TASKS: [{"id": "agent-1", "status": "running"}],
        }

    return build


#: Arming payloads by the handler package's event directory.
PAYLOADS: Final[Mapping[str, tuple[PayloadFactory, ...]]] = {
    "pre_tool_use": (
        _bash("pytest tests/"),
        _bash("git push origin main"),
    ),
    "post_tool_use": (_gh_run_list_queued,),
    "session_start": (_session_start_resume,),
    "user_prompt_submit": (_prompt,),
    #: A waiting stop (owner_wait_stop_guard), a no-reason stop (the wind-down note).
    "stop": (_stop(WAITING), _stop(NO_REASON)),
}
#: owner_directives_register replays only a configured register.
DIRECTIVES: Final[list[dict[str, str]]] = [{"id": "no-squash", "text": "Never squash-merge."}]


def _event_dir(handler: Handler) -> str:
    return type(handler).__module__.split(".")[-2]


def _team_handlers() -> list[Handler]:
    registry = HandlerRegistry()
    registry.discover()
    found: list[Handler] = []
    for name in registry.list_handlers():
        handler_cls = registry.get_handler_class(name)
        assert handler_cls is not None, name
        if "_team_seat" not in handler_cls.__init__.__code__.co_names:
            continue
        handler = handler_cls()
        if hasattr(handler, "_team_seat"):
            handler._team_seat = TeamSeatConfig()
            if hasattr(handler, "_directives"):
                handler._directives = DIRECTIVES
            found.append(handler)
    return found


def _with_teamchat(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        **payload,
        HookInputField.TEAMCHAT_RUNTIME: RUNTIME,
        HookInputField.TEAMCHAT_KIT: KIT,
    }


def _outcome(*, status: CommandStatus, stdout: str = "") -> Callable[..., CommandOutcome]:
    def run(_argv: Sequence[str], _env: Mapping[str, str], _timeout: float) -> CommandOutcome:
        return CommandOutcome(status=status, stdout=stdout, exit_code=None)

    return run


def _speaks(result: Any) -> bool:
    return (
        result.decision != Decision.ALLOW
        or bool(result.reason)
        or bool(getattr(result, "context", None))
    )


def _run(handler: Handler, payload: dict[str, Any]) -> Any | None:
    if not handler.matches(payload):
        return None
    return handler.handle(payload)


@pytest.fixture(autouse=True)
def _bare_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """A tmp project root with no ``.claude/ccy/`` and no team environment."""
    monkeypatch.setattr(ProjectContext, "project_root", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(
        ProjectContext, "daemon_untracked_dir", classmethod(lambda cls: tmp_path / "untracked")
    )
    for key in list(os.environ):
        if key.startswith(_SCRUBBED_PREFIXES):
            monkeypatch.delenv(key)
    reset_shared_resolvers()
    yield
    reset_shared_resolvers()


@pytest.fixture
def spawned(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record (never raise: handlers swallow exceptions) every spawn attempt."""
    calls: list[str] = []

    def record(label: str) -> Callable[..., Any]:
        def fake(*_a: Any, **_k: Any) -> Any:
            calls.append(label)
            return CommandOutcome(status=CommandStatus.NOT_FOUND)

        return fake

    monkeypatch.setattr(teamchat_seat, "run_kit_command", record("teamchat_seat.run_kit_command"))
    monkeypatch.setattr(human_approval, "run_kit_command", record("human_approval.run_kit_command"))
    monkeypatch.setattr(subprocess, "Popen", record("subprocess.Popen"))
    return calls


def test_the_team_handler_set_is_pinned() -> None:
    names = {type(handler).__name__ for handler in _team_handlers()}
    assert names == TEAM_HANDLER_CLASSES


def test_every_team_handler_has_an_arming_payload() -> None:
    for handler in _team_handlers():
        assert PAYLOADS.get(_event_dir(handler)), type(handler).__name__


def test_bare_environment_has_no_ccy_directory(tmp_path: Path) -> None:
    assert not (tmp_path / ".claude" / "ccy").exists()


@pytest.mark.parametrize("handler_name", sorted(TEAM_HANDLER_CLASSES))
def test_bare_environment_wakes_no_team_handler(
    tmp_path: Path, spawned: list[str], handler_name: str
) -> None:
    (handler,) = [h for h in _team_handlers() if type(h).__name__ == handler_name]
    for build in PAYLOADS[_event_dir(handler)]:
        result = _run(handler, build(tmp_path))
        if result is None:
            continue
        if handler_name == WIND_DOWN_ONLY:
            assert WIND_DOWN_HEADING not in (result.reason or "")
        else:
            assert not _speaks(result), (handler_name, result)
    assert spawned == []


# --- cases B and C, through a real resolver ------------------------------------


def _lane_guard() -> Handler:
    (handler,) = [h for h in _team_handlers() if type(h).__name__ == "HostSeatLaneGuardHandler"]
    return handler


def _approval_check() -> Handler:
    (handler,) = [h for h in _team_handlers() if type(h).__name__ == "HumanApprovalCheckHandler"]
    return handler


def _resolved(handler: Handler, runner: Callable[..., CommandOutcome]) -> Handler:
    handler._resolver = SeatContextResolver(runner=runner)
    return handler


@pytest.mark.parametrize("status", [CommandStatus.NOT_FOUND, CommandStatus.TIMEOUT])
@pytest.mark.parametrize("handler_name", sorted(TEAM_HANDLER_CLASSES))
def test_case_b_runtime_only_never_resolved_is_silent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, status: CommandStatus, handler_name: str
) -> None:
    """Every team handler, advisories and owner_wait_stop_guard included."""
    bus_calls: list[str] = []

    def record(*_a: Any, **_k: Any) -> CommandOutcome:
        bus_calls.append("spawn")
        return CommandOutcome(status=CommandStatus.NOT_FOUND)

    # Not the ``spawned`` fixture: it would replace the probe the runner feeds.
    monkeypatch.setattr(human_approval, "run_kit_command", record)
    monkeypatch.setattr(subprocess, "Popen", record)
    (handler,) = [h for h in _team_handlers() if type(h).__name__ == handler_name]
    _resolved(handler, _outcome(status=status))
    for build in PAYLOADS[_event_dir(handler)]:
        result = _run(handler, _with_teamchat(build(tmp_path)))
        if result is None:
            continue
        if handler_name == WIND_DOWN_ONLY:
            assert WIND_DOWN_HEADING not in (result.reason or "")
        else:
            assert not _speaks(result), (handler_name, result)
    assert bus_calls == []


def test_case_c_null_duty_does_not_arm_the_lane_guard(tmp_path: Path) -> None:
    handler = _resolved(
        _lane_guard(),
        _outcome(status=CommandStatus.OK, stdout=fx.whoami(fx.seat("alpha", "worker", duty=None))),
    )
    result = _run(handler, _with_teamchat(_bash("pytest tests/")(tmp_path)))
    assert result is None or not _speaks(result)


def test_case_c_coordinator_with_null_duty_is_armed(tmp_path: Path) -> None:
    handler = _resolved(
        _approval_check(),
        _outcome(
            status=CommandStatus.OK, stdout=fx.whoami(fx.seat("alpha", "coordinator", duty=None))
        ),
    )
    result = _run(handler, _with_teamchat(_bash("git push origin main")(tmp_path)))
    assert result is not None and _speaks(result)


@pytest.mark.parametrize("handler_name", sorted(TEAM_HANDLER_CLASSES))
def test_control_the_bare_payloads_do_arm_a_resolved_seat(
    tmp_path: Path, handler_name: str
) -> None:
    """The bare-pass payloads are not silent by construction: a real seat hears them."""
    (handler,) = [h for h in _team_handlers() if type(h).__name__ == handler_name]
    seat = (
        fx.seat("alpha", "worker", duty="host")
        if handler_name == "HostSeatLaneGuardHandler"
        else fx.seat("alpha", "coordinator")
    )
    _resolved(handler, _outcome(status=CommandStatus.OK, stdout=fx.whoami(seat)))
    results = [
        _run(handler, _with_teamchat(build(tmp_path))) for build in PAYLOADS[_event_dir(handler)]
    ]
    if handler_name == WIND_DOWN_ONLY:
        assert any(r is not None and WIND_DOWN_HEADING in (r.reason or "") for r in results)
    else:
        assert any(r is not None and _speaks(r) for r in results), results


# --- R4: every team handler shares ONE probe per session per TTL ------------------


def _count_whoami(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Stub every spawn; count only ``whoami`` probes, answered as a coordinator."""
    count = [0]
    stdout = fx.whoami(fx.seat("alpha", "coordinator"))

    def fake(_signals: Any, args: Sequence[str], *, runner: Any, timeout: float) -> CommandOutcome:
        if tuple(args) == tuple(teamchat_seat.WHOAMI_ARGS):
            count[0] += 1
            return CommandOutcome(status=CommandStatus.OK, stdout=stdout, exit_code=0)
        return CommandOutcome(status=CommandStatus.NOT_FOUND)

    def not_found(*_a: Any, **_k: Any) -> CommandOutcome:
        return CommandOutcome(status=CommandStatus.NOT_FOUND)

    monkeypatch.setattr(teamchat_seat, "run_kit_command", fake)
    monkeypatch.setattr(human_approval, "run_kit_command", not_found)
    monkeypatch.setattr(subprocess, "Popen", not_found)
    return count


def _run_every_team_payload(tmp_path: Path, *, fresh_resolver_each: bool) -> None:
    handlers = _team_handlers()
    assert {type(h).__name__ for h in handlers} == TEAM_HANDLER_CLASSES
    for handler in handlers:
        assert handler._resolver is None, type(handler).__name__
        if fresh_resolver_each:
            reset_shared_resolvers()
        for build in PAYLOADS[_event_dir(handler)]:
            _run(handler, _with_teamchat(build(tmp_path)))


def test_all_eight_team_handlers_share_one_whoami(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    count = _count_whoami(monkeypatch)
    _run_every_team_payload(tmp_path, fresh_resolver_each=False)
    assert count[0] == 1


def test_control_each_team_handler_does_reach_the_probe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without the shared resolver every handler probes: the one-call pin is not vacuous."""
    count = _count_whoami(monkeypatch)
    _run_every_team_payload(tmp_path, fresh_resolver_each=True)
    assert count[0] == len(TEAM_HANDLER_CLASSES)


def test_control_a_resolved_host_seat_speaks(tmp_path: Path) -> None:
    handler = _resolved(
        _lane_guard(),
        _outcome(
            status=CommandStatus.OK, stdout=fx.whoami(fx.seat("alpha", "worker", duty="host"))
        ),
    )
    result = _run(handler, _with_teamchat(_bash("pytest tests/")(tmp_path)))
    assert result is not None and _speaks(result)
