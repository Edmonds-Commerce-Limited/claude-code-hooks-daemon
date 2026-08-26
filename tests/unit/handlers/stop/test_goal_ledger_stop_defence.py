"""Plan 00276 Phase 4: Stop-time defence of every still-live ledgered goal.

When the goal ledger records goals for plans that are still ``In Progress``,
a Stop lacking ``STOPPING BECAUSE:`` must be challenged with a message naming
EVERY live ledgered plan — not just the newest one, whose goal is the only
one the upstream ``/goal`` slot still remembers. A missing, empty, or
unreadable ledger degrades to the unchanged default message (fail-open).
"""

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import (
    AutoContinueStopHandler,
)
from claude_code_hooks_daemon.utils.goal_ledger import LEDGER_FILENAME, GoalLedger

_SESSION = "sess-stop-1"
_PLAN_A = "00274"
_PLAN_B = "00275"


def _make_plan(plan_dir: Path, number: str, status: str) -> Path:
    folder = plan_dir / f"{number}-example-plan"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "PLAN.md").write_text(
        f"# Plan {number}: example plan\n\n**Status**: {status}\n", encoding="utf-8"
    )
    return folder


class TestGoalLedgerStopDefence:
    @pytest.fixture(autouse=True)
    def mock_project_context(self, tmp_path: Path):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "claude_code_hooks_daemon.handlers.stop.auto_continue_stop."
                "ProjectContext.daemon_untracked_dir",
                classmethod(lambda cls: tmp_path / "untracked"),
            )
            mp.setattr(
                "claude_code_hooks_daemon.handlers.stop.auto_continue_stop."
                "ProjectContext.project_root",
                classmethod(lambda cls: tmp_path),
            )
            self._untracked = tmp_path / "untracked"
            self._plan_dir = tmp_path / "CLAUDE" / "Plan"
            yield

    @pytest.fixture
    def handler(self) -> AutoContinueStopHandler:
        return AutoContinueStopHandler()

    def _ledger(self) -> GoalLedger:
        return GoalLedger(self._untracked / LEDGER_FILENAME)

    def _record(self, number: str) -> None:
        self._ledger().record_emission(_SESSION, number, "goal line", self._plan_dir)

    def test_default_deny_names_every_live_ledgered_plan(
        self, handler: AutoContinueStopHandler
    ) -> None:
        _make_plan(self._plan_dir, _PLAN_A, "In Progress")
        _make_plan(self._plan_dir, _PLAN_B, "In Progress")
        self._record(_PLAN_A)
        self._record(_PLAN_B)
        hook_input: dict[str, Any] = {}
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert _PLAN_A in result.reason
        assert _PLAN_B in result.reason
        assert "ledger" in result.reason.lower()

    def test_retired_plan_is_not_named(self, handler: AutoContinueStopHandler) -> None:
        folder = _make_plan(self._plan_dir, _PLAN_A, "In Progress")
        _make_plan(self._plan_dir, _PLAN_B, "In Progress")
        self._record(_PLAN_A)
        self._record(_PLAN_B)
        (folder / "PLAN.md").write_text("**Status**: Complete\n", encoding="utf-8")
        result = handler.handle({})
        assert result.reason is not None
        assert _PLAN_A not in result.reason
        assert _PLAN_B in result.reason

    def test_empty_ledger_leaves_default_reason_unchanged(
        self, handler: AutoContinueStopHandler
    ) -> None:
        from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import (
            _EXPLAIN_OR_CONTINUE_REASON,
        )

        result = handler.handle({})
        assert result.decision == Decision.DENY
        assert result.reason == _EXPLAIN_OR_CONTINUE_REASON

    def test_uninitialised_project_context_fails_open(
        self, handler: AutoContinueStopHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(cls: object) -> Path:
            raise RuntimeError("not initialised")

        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.stop.auto_continue_stop."
            "ProjectContext.daemon_untracked_dir",
            classmethod(_boom),
        )
        result = handler.handle({})
        assert result.decision == Decision.DENY
        assert result.reason is not None

    def test_corrupt_ledger_fails_open(self, handler: AutoContinueStopHandler) -> None:
        self._untracked.mkdir(parents=True, exist_ok=True)
        (self._untracked / LEDGER_FILENAME).write_text("{broken", encoding="utf-8")
        result = handler.handle({})
        assert result.decision == Decision.DENY
        assert result.reason is not None
