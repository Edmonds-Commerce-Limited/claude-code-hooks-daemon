"""Tests for PlanStatusSnapshotHandler (Plan 00466 RV3-n5).

PreToolUse sensor half of the goal-injection snapshot mechanism: records
the plan's disk status just before a Write/Edit runs, keyed by
``tool_use_id``, so the PostToolUse ``goal_injection`` handler can consume
it as ground truth instead of inferring the pre-write status from
``old_string``/``new_string`` or git HEAD. Always ALLOWs; never blocks.
"""

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.plan_status_snapshot import (
    PlanStatusSnapshotHandler,
)
from claude_code_hooks_daemon.plan_qa.model import PlanStatus
from claude_code_hooks_daemon.utils.plan_status_snapshot import plan_status_snapshots

_PLAN_FOLDER = "00269-supervisor-goal-message-injection"


class TestPlanStatusSnapshotHandler:
    @pytest.fixture(autouse=True)
    def mock_project_context(self, tmp_path: Path):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "claude_code_hooks_daemon.utils.plan_trigger.ProjectContext.project_root",
                classmethod(lambda cls: tmp_path),
            )
            self._project = tmp_path
            yield

    @pytest.fixture
    def handler(self) -> PlanStatusSnapshotHandler:
        return PlanStatusSnapshotHandler()

    def _plan_path(self, folder: str = _PLAN_FOLDER) -> Path:
        plan_dir = self._project / "CLAUDE" / "Plan" / folder
        plan_dir.mkdir(parents=True, exist_ok=True)
        return plan_dir / "PLAN.md"

    def _write_plan(self, status: str, folder: str = _PLAN_FOLDER) -> Path:
        plan = self._plan_path(folder)
        plan.write_text(f"# Example\n\n**Status**: {status}\n", encoding="utf-8")
        return plan

    def _hook_input(
        self, file_path: Path, tool: str = "Edit", *, tool_use_id: str = "tu-1"
    ) -> dict[str, Any]:
        hook_input: dict[str, Any] = {
            "tool_name": tool,
            "tool_input": {"file_path": str(file_path)},
        }
        if tool_use_id:
            hook_input["tool_use_id"] = tool_use_id
        return hook_input

    # ---- metadata ---------------------------------------------------------

    def test_init_identity(self, handler: PlanStatusSnapshotHandler) -> None:
        assert handler.name == HandlerID.PLAN_STATUS_SNAPSHOT.display_name
        assert handler.priority == Priority.PLAN_STATUS_SNAPSHOT
        assert handler.terminal is False

    def test_default_disabled(self, handler: PlanStatusSnapshotHandler) -> None:
        assert handler.get_default_enabled() is False

    # ---- matches ------------------------------------------------------------

    def test_matches_active_plan_write(self, handler: PlanStatusSnapshotHandler) -> None:
        plan = self._write_plan("Not Started")
        assert handler.matches(self._hook_input(plan, tool="Write")) is True

    def test_matches_active_plan_edit(self, handler: PlanStatusSnapshotHandler) -> None:
        plan = self._write_plan("Not Started")
        assert handler.matches(self._hook_input(plan, tool="Edit")) is True

    def test_does_not_match_other_tools(self, handler: PlanStatusSnapshotHandler) -> None:
        plan = self._write_plan("Not Started")
        assert handler.matches(self._hook_input(plan, tool="Read")) is False

    def test_does_not_match_completed_plan(self, handler: PlanStatusSnapshotHandler) -> None:
        plan_dir = self._project / "CLAUDE" / "Plan" / "Completed" / _PLAN_FOLDER
        plan_dir.mkdir(parents=True)
        plan = plan_dir / "PLAN.md"
        plan.write_text("**Status**: Complete\n", encoding="utf-8")
        assert handler.matches(self._hook_input(plan)) is False

    # ---- handle: records the pre-write status ------------------------------

    def test_handle_records_the_pre_write_status(self, handler: PlanStatusSnapshotHandler) -> None:
        plan = self._write_plan("Not Started")

        result = handler.handle(self._hook_input(plan, tool_use_id="tu-record"))

        assert result.decision == Decision.ALLOW
        status, found = plan_status_snapshots.consume("tu-record")
        assert found is True
        assert status == PlanStatus.NOT_STARTED

    def test_handle_records_none_when_no_status_line(
        self, handler: PlanStatusSnapshotHandler
    ) -> None:
        plan = self._plan_path()
        plan.write_text("# Example\n\nNo status line here.\n", encoding="utf-8")

        result = handler.handle(self._hook_input(plan, tool_use_id="tu-nostatus"))

        assert result.decision == Decision.ALLOW
        status, found = plan_status_snapshots.consume("tu-nostatus")
        assert found is True
        assert status is None

    def test_handle_records_none_for_a_brand_new_plan_file(
        self, handler: PlanStatusSnapshotHandler
    ) -> None:
        """A Write that CREATES PLAN.md for the first time has nothing to
        read pre-write -- None is the correct ground truth, not a skip."""
        plan_dir = self._project / "CLAUDE" / "Plan" / _PLAN_FOLDER
        plan_dir.mkdir(parents=True)
        plan = plan_dir / "PLAN.md"  # deliberately not written yet

        result = handler.handle(self._hook_input(plan, tool="Write", tool_use_id="tu-brandnew"))

        assert result.decision == Decision.ALLOW
        status, found = plan_status_snapshots.consume("tu-brandnew")
        assert found is True
        assert status is None

    def test_handle_is_a_noop_for_a_non_matching_event(
        self, handler: PlanStatusSnapshotHandler
    ) -> None:
        plan = self._write_plan("Not Started")

        result = handler.handle(self._hook_input(plan, tool="Read", tool_use_id="tu-noop"))

        assert result.decision == Decision.ALLOW
        status, found = plan_status_snapshots.consume("tu-noop")
        assert found is False
        assert status is None

    def test_handle_skips_recording_with_no_tool_use_id(
        self, handler: PlanStatusSnapshotHandler
    ) -> None:
        plan = self._write_plan("Not Started")

        result = handler.handle(self._hook_input(plan, tool_use_id=""))

        assert result.decision == Decision.ALLOW
        status, found = plan_status_snapshots.consume("")
        assert found is False
        assert status is None

    def test_get_claude_md_present(self, handler: PlanStatusSnapshotHandler) -> None:
        text = handler.get_claude_md()
        assert text is not None
        assert "plan_status_snapshot" in text
