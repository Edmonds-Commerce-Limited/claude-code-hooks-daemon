"""Plan 00416 Task 2.3 — the SessionStart sensor for the supervisor directive.

Layer 2 of the plan: after session start the supervisor types ONE turn-level
directive telling the agent to action every `ACTION_REQUIRED` item. This
handler is the sensor that decides whether there is anything to say, and
drops the signal the supervisor consumes.

Two properties are load-bearing, and both are tested here rather than left to
review:

- **It adds NOTHING to the SessionStart block.** The plan's Non-Goals rule out
  "saying it louder" by construction; a handler that both wrote the signal and
  appended a line would be doing exactly that. The whole value is the CHANNEL,
  so the block must be left alone.
- **It counts what `session-actions` would list**, via the same collector the
  CLI verb uses. The directive sends the agent to that command; a directive
  that fires while the command prints "no items" would teach the agent to
  ignore the next one — the precise failure this plan exists to fix.

It carries no verifier of its own, so it can never compute `ACTION_REQUIRED`
for itself. A nudge about a must-do list is not a must-do item.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.session_start_tiers import (
    SessionTier,
    compute_tier,
    has_verifier,
)
from claude_code_hooks_daemon.handlers.session_start import session_actions_directive
from claude_code_hooks_daemon.handlers.session_start.session_actions_directive import (
    SessionActionsDirectiveHandler,
)
from claude_code_hooks_daemon.utils.session_actions_signal import (
    FIELD_COUNT,
    SIGNAL_SUBDIR,
    SIGNAL_SUFFIX,
)

_SESSION = "directive-sess-1"


def _hook_input(session_id: str = _SESSION) -> dict[str, Any]:
    return {"session_id": session_id, "source": "startup"}


def _install(
    monkeypatch: Any, untracked: Path, *, count: int, supervisor_live: bool = True
) -> SessionActionsDirectiveHandler:
    """A handler wired to a fake project root and a fixed ACTION_REQUIRED count."""
    handler = SessionActionsDirectiveHandler()
    monkeypatch.setattr(handler, "_untracked_dir", lambda: untracked)
    monkeypatch.setattr(handler, "_project_root", lambda: untracked)
    monkeypatch.setattr(
        session_actions_directive,
        "armed_supervisor_live",
        lambda _project_root: supervisor_live,
    )
    monkeypatch.setattr(
        session_actions_directive,
        "collect_session_action_items",
        lambda _project_root: [object()] * count,
    )
    return handler


def _signal(untracked: Path, session_id: str = _SESSION) -> Path:
    return untracked / SIGNAL_SUBDIR / f"{session_id}{SIGNAL_SUFFIX}"


class TestItNeverSpeaksInTheBlock:
    def test_it_emits_no_context_when_there_is_something_to_action(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        handler = _install(monkeypatch, tmp_path, count=2)
        result = handler.handle(_hook_input())
        assert result.decision is Decision.ALLOW
        assert result.context == []

    def test_it_emits_no_context_when_there_is_not(self, tmp_path: Path, monkeypatch: Any) -> None:
        handler = _install(monkeypatch, tmp_path, count=0)
        result = handler.handle(_hook_input())
        assert result.decision is Decision.ALLOW
        assert result.context == []


class TestTheSignal:
    def test_it_is_written_with_the_count(self, tmp_path: Path, monkeypatch: Any) -> None:
        handler = _install(monkeypatch, tmp_path, count=3)
        handler.handle(_hook_input())
        payload = json.loads(_signal(tmp_path).read_text(encoding="utf-8"))
        assert payload[FIELD_COUNT] == 3

    def test_nothing_to_action_writes_nothing(self, tmp_path: Path, monkeypatch: Any) -> None:
        handler = _install(monkeypatch, tmp_path, count=0)
        handler.handle(_hook_input())
        assert not _signal(tmp_path).exists()

    def test_nothing_to_action_clears_a_stale_signal(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        # A resumed session whose problem was fixed in between must not be
        # nudged about it: the directive is keyed on the CURRENT verifiers.
        handler = _install(monkeypatch, tmp_path, count=2)
        handler.handle(_hook_input())
        assert _signal(tmp_path).exists()

        monkeypatch.setattr(
            session_actions_directive, "collect_session_action_items", lambda _root: []
        )
        handler.handle(_hook_input())
        assert not _signal(tmp_path).exists()

    def test_a_session_without_an_id_writes_nothing(self, tmp_path: Path, monkeypatch: Any) -> None:
        # The supervisor matches signals to its OWN sessions by the file stem;
        # a signal with no session to name could be delivered to any terminal
        # sharing this project's untracked directory.
        handler = _install(monkeypatch, tmp_path, count=2)
        handler.handle({"source": "startup"})
        assert not (tmp_path / SIGNAL_SUBDIR).exists()


class TestFailures:
    def test_an_unwritable_untracked_dir_does_not_break_session_start(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        # Best-effort sensor: a SessionStart handler that raises would cost
        # the agent every other handler's output too.
        handler = _install(monkeypatch, tmp_path, count=1)
        monkeypatch.setattr(handler, "_untracked_dir", lambda: tmp_path / "nope" / "\0bad")
        result = handler.handle(_hook_input())
        assert result.decision is Decision.ALLOW

    def test_a_collector_that_raises_does_not_break_session_start(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        def _boom(_root: Any) -> Any:
            raise RuntimeError("registry exploded")

        handler = _install(monkeypatch, tmp_path, count=1)
        monkeypatch.setattr(session_actions_directive, "collect_session_action_items", _boom)
        result = handler.handle(_hook_input())
        assert result.decision is Decision.ALLOW
        assert not _signal(tmp_path).exists()


class TestItOnlyActsWhereSomethingWillReadTheSignal:
    """A signal nobody consumes is litter, not a nudge.

    The actuator is the ccy PTY supervisor. Where none is armed and live,
    writing the file changes nothing a human or an agent would ever see, so
    the handler stands down — the same gate `standing_authorisations` applies
    before routing to its own supervisor channel.
    """

    def test_no_armed_supervisor_writes_nothing(self, tmp_path: Path, monkeypatch: Any) -> None:
        handler = _install(monkeypatch, tmp_path, count=2, supervisor_live=False)
        handler.handle(_hook_input())
        assert not _signal(tmp_path).exists()

    def test_it_is_opt_in(self) -> None:
        # Types into a human's terminal, so a project enables it deliberately
        # — the stance every supervisor-actuated handler takes.
        assert SessionActionsDirectiveHandler().get_default_enabled() is False


class TestItIsNotItselfAnActionItem:
    def test_it_declares_no_verifier(self) -> None:
        assert not has_verifier(SessionActionsDirectiveHandler())

    def test_it_can_never_compute_action_required(self) -> None:
        assert compute_tier(SessionActionsDirectiveHandler()) is not SessionTier.ACTION_REQUIRED
