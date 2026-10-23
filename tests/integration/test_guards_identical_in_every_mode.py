"""Guards judge a tool call the same in every session mode (Plan 00501 Success Criteria).

A session mode turns off work-DRIVING machinery only. This module holds the other
half of that promise: with the default configuration, a canonical set of tool
calls that guards deny is dispatched through the real ``DaemonController``
(mode interceptor, router and the whole discovered handler chain) once with no
mode and once under each mode, and every decision and the handler that made it
must be identical.

``usage-paused`` is the one mode that ADDS a deny: its own gate refuses every
main-thread tool before any guard is consulted. Under it the test asserts no
deny is lost, and that the same chain without that gate is identical to the
baseline, so the guards behind it are unchanged too.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.constants import HandlerID, HookInputField
from claude_code_hooks_daemon.constants.modes import DaemonMode
from claude_code_hooks_daemon.core.event import HookEvent
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.controller import DaemonController
from claude_code_hooks_daemon.utils.autonomy import session_policy
from claude_code_hooks_daemon.utils.session_modes import (
    ModeLabel,
    ModeSource,
    goal_loop_blocked_entry,
    manual_goals_entry,
)
from claude_code_hooks_daemon.utils.usage_pause import (
    WINDOW_FIVE_HOUR,
    UsagePause,
    write_usage_pause,
)
from claude_code_hooks_daemon.utils.usage_pause_gate import hook_is_usage_paused
from tests.support.autonomy import awaiting_human_entry, focus_entry, pin_session_modes

_SESSION: Final[str] = "guards-every-mode"

#: Assembled so this file never carries the suppression the guard under test denies.
_SUPPRESSION: Final[str] = "# type" + ": ignore"


@dataclass(frozen=True)
class Call:
    """One canonical tool call a guard denies."""

    id: str
    tool: str
    tool_input: dict[str, Any]


#: One call per guard family; ``{ROOT}`` is the fixture project.
CALLS: Final[tuple[Call, ...]] = (
    Call("git-reset-hard", "Bash", {"command": "git reset --hard HEAD~1"}),
    Call("sed-in-place", "Bash", {"command": "sed -i 's/a/b/' README.md"}),
    Call("pipe-to-tail", "Bash", {"command": "pytest tests/ 2>&1 | tail -20"}),
    Call("chmod-777", "Bash", {"command": "chmod 777 README.md"}),
    Call(
        "qa-suppression-edit",
        "Edit",
        {
            "file_path": "{ROOT}/src/app.py",
            "old_string": "VALUE = 1",
            "new_string": f"VALUE: int = 'x'  {_SUPPRESSION}",
        },
    ),
)

#: The guard each call must land on with no mode: proves the input is canonical.
EXPECTED_DENIER: Final[dict[str, str]] = {
    "git-reset-hard": HandlerID.DESTRUCTIVE_GIT.display_name,
    "sed-in-place": HandlerID.SED_BLOCKER.display_name,
    "pipe-to-tail": HandlerID.PIPE_BLOCKER.display_name,
    "chmod-777": HandlerID.DANGEROUS_PERMISSIONS.display_name,
    "qa-suppression-edit": HandlerID.QA_SUPPRESSION.display_name,
}

#: An ordinary call no mode but usage-paused may deny (a mode never adds a guard).
ORDINARY: Final[Call] = Call("ls", "Bash", {"command": "ls"})


@dataclass(frozen=True)
class Verdict:
    """What the chain decided and who decided it."""

    decision: Decision
    decided_by: str | None


def _focus(enter: Callable[..., None], untracked: Path, controller: DaemonController) -> None:
    enter(focus_entry(_SESSION))


def _awaiting_human(
    enter: Callable[..., None], untracked: Path, controller: DaemonController
) -> None:
    enter(awaiting_human_entry(_SESSION))


def _goal_blocked(
    enter: Callable[..., None], untracked: Path, controller: DaemonController
) -> None:
    enter(goal_loop_blocked_entry(_SESSION, entered_at=time.time(), ttl_seconds=3600.0))


def _manual_goals(
    enter: Callable[..., None], untracked: Path, controller: DaemonController
) -> None:
    enter(manual_goals_entry(_SESSION, entered_at=time.time(), source=ModeSource.HUMAN))


def _usage_paused(
    enter: Callable[..., None], untracked: Path, controller: DaemonController
) -> None:
    now = time.time()
    write_usage_pause(
        untracked,
        UsagePause(
            session_id=_SESSION,
            paused_at=now - 1.0,
            resume_at=now + 3600.0,
            window=WINDOW_FIVE_HOUR,
            used_percentage=95.0,
            ceiling=90.0,
            reason="test: five-hour window over the ceiling",
        ),
    )


def _unattended(enter: Callable[..., None], untracked: Path, controller: DaemonController) -> None:
    controller.set_mode(DaemonMode.UNATTENDED)


ModeSetter = Callable[[Callable[..., None], Path, DaemonController], None]

#: Every mode the criterion names, by its status-line label.
MODES: Final[dict[str, ModeSetter]] = {
    "focus": _focus,
    "awaiting-human": _awaiting_human,
    "goal-blocked": _goal_blocked,
    "manual-goals": _manual_goals,
    "usage-paused": _usage_paused,
    "unattended": _unattended,
}

_USAGE_PAUSED: Final[str] = "usage-paused"

#: The smallest valid config: every handler at its own default.
_DEFAULT_CONFIG: Final[str] = (
    'version: "1.0"\ndaemon:\n  idle_timeout_seconds: 600\n  log_level: INFO\nhandlers: {}\n'
)


def _build_project(root: Path) -> None:
    """A default-config project: the required sections, no handler named, a git index."""
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "hooks-daemon.yaml").write_text(_DEFAULT_CONFIG, encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "README.md").write_text("# fixture\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)


def _controller(root: Path, handler_config: dict[str, Any] | None = None) -> DaemonController:
    """A controller over ``root`` at the default configuration (plus ``handler_config``)."""
    ProjectContext.reset()
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=f"{root}\n"),
            MagicMock(returncode=0, stdout="git@github.com:user/test-repo.git\n"),
            MagicMock(returncode=0, stdout=f"{root}\n"),
        ]
        ProjectContext.initialize(root / ".claude" / "hooks-daemon.yaml")
    controller = DaemonController()
    controller.initialise(
        handler_config=handler_config,
        workspace_root=root,
        defer_nonessential_startup=True,
    )
    return controller


def _judge(controller: DaemonController, call: Call, root: Path) -> Verdict:
    tool_input = {
        key: value.replace("{ROOT}", str(root)) if isinstance(value, str) else value
        for key, value in call.tool_input.items()
    }
    event = HookEvent.model_validate(
        {
            "event": "PreToolUse",
            "hook_input": {
                "hook_event_name": "PreToolUse",
                "tool_name": call.tool,
                "tool_input": tool_input,
                "session_id": _SESSION,
                "cwd": str(root),
            },
        }
    )
    outcome = controller.process_event(event)
    return Verdict(decision=outcome.result.decision, decided_by=outcome.decided_by)


def _judge_all(controller: DaemonController, root: Path) -> dict[str, Verdict]:
    return {call.id: _judge(controller, call, root) for call in (*CALLS, ORDINARY)}


@pytest.fixture()
def project(tmp_path: Path) -> Iterator[tuple[Path, Path]]:
    """The fixture project and the daemon untracked dir its modes are read from."""
    root = tmp_path / "project"
    root.mkdir()
    _build_project(root)
    untracked = tmp_path / "daemon-untracked"
    untracked.mkdir()
    yield root, untracked
    ProjectContext.reset()


def _verdicts_under(
    mode: str | None,
    root: Path,
    untracked: Path,
    monkeypatch: pytest.MonkeyPatch,
    handler_config: dict[str, Any] | None = None,
) -> dict[str, Verdict]:
    """Every call's verdict from a fresh controller with ``mode`` (None: no mode) active."""
    controller = _controller(root, handler_config)
    # Each run gets its own untracked dir, so the baseline never sees a mode's state.
    untracked = untracked / (mode or "no-mode")
    untracked.mkdir(exist_ok=True)
    registry = pin_session_modes(monkeypatch, untracked)
    if mode is not None:
        MODES[mode](registry.enter, untracked, controller)
        _assert_mode_is_live(mode, controller)
    return _judge_all(controller, root)


def _assert_mode_is_live(mode: str, controller: DaemonController) -> None:
    """The mode is visible where the daemon reads it, so a comparison is never vacuous."""
    if mode == DaemonMode.UNATTENDED.value:
        assert controller.get_mode()["mode"] == mode
    elif mode == _USAGE_PAUSED:
        assert hook_is_usage_paused({HookInputField.SESSION_ID: _SESSION})
    else:
        labels = session_policy({HookInputField.SESSION_ID: _SESSION}).labels
        assert labels == (ModeLabel(mode),)


def _assert_canonical(baseline: dict[str, Verdict]) -> None:
    """Each call is denied by its own guard and the ordinary call is allowed.

    Without this a degraded daemon (an invalid fixture config) allows everything
    in every mode, and the comparison below would pass on nothing.
    """
    expected = {call_id: Verdict(Decision.DENY, name) for call_id, name in EXPECTED_DENIER.items()}
    assert {call.id: baseline[call.id] for call in CALLS} == expected
    assert baseline[ORDINARY.id].decision is Decision.ALLOW, baseline


class TestBaseline:
    """Vacuity guard: with no mode each call is denied by the guard it was written for."""

    def test_each_call_lands_on_its_guard(
        self, project: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root, untracked = project
        _assert_canonical(_verdicts_under(None, root, untracked, monkeypatch))


class TestEveryMode:
    """The criterion itself: no mode changes a guard's verdict."""

    @pytest.mark.parametrize("mode", sorted(set(MODES) - {_USAGE_PAUSED}))
    def test_verdicts_are_identical_to_the_baseline(
        self, mode: str, project: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root, untracked = project
        baseline = _verdicts_under(None, root, untracked, monkeypatch)
        _assert_canonical(baseline)
        under_mode = _verdicts_under(mode, root, untracked, monkeypatch)
        assert under_mode == baseline

    def test_usage_paused_loses_no_deny(
        self, project: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root, untracked = project
        paused = _verdicts_under(_USAGE_PAUSED, root, untracked, monkeypatch)
        gate = HandlerID.USAGE_PAUSE_TOOL_GATE.display_name
        assert {call.id: paused[call.id] for call in CALLS} == {
            call.id: Verdict(Decision.DENY, gate) for call in CALLS
        }

    def test_usage_paused_leaves_the_guards_behind_its_gate_unchanged(
        self, project: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root, untracked = project
        without_gate = {
            "pre_tool_use": {HandlerID.USAGE_PAUSE_TOOL_GATE.config_key: {"enabled": False}}
        }
        baseline = _verdicts_under(None, root, untracked, monkeypatch, without_gate)
        _assert_canonical(baseline)
        paused = _verdicts_under(_USAGE_PAUSED, root, untracked, monkeypatch, without_gate)
        assert paused == baseline
