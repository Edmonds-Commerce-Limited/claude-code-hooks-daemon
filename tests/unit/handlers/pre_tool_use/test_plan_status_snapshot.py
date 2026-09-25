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
        """RV5-M2: ``would_be_content`` needs a real, present ``old_string``
        to predict anything for an Edit, so this reads whatever is
        currently on disk and builds a no-op-shaped edit (replace the
        first line with itself) -- these tests are about the STATUS/found
        recording, not the prediction mechanics, which get their own
        dedicated tests below. The read is best-effort: a test that
        monkeypatches ``Path.read_text`` to raise (the EACCES pin) must
        still be able to build SOME hook input, so an unreadable file
        here falls back to empty content rather than failing the helper
        itself -- the handler under test does its own independent read
        and is what actually exercises that failure."""
        try:
            current = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            current = ""
        tool_input: dict[str, Any] = {"file_path": str(file_path)}
        if tool == "Write":
            tool_input["content"] = current
        elif tool == "Edit":
            first_line = current.splitlines()[0] if current else " "
            tool_input["old_string"] = first_line
            tool_input["new_string"] = first_line
        hook_input: dict[str, Any] = {"tool_name": tool, "tool_input": tool_input}
        if tool_use_id:
            hook_input["tool_use_id"] = tool_use_id
        return hook_input

    # ---- metadata ---------------------------------------------------------

    def test_init_identity(self, handler: PlanStatusSnapshotHandler) -> None:
        assert handler.name == HandlerID.PLAN_STATUS_SNAPSHOT.display_name
        assert handler.priority == Priority.PLAN_STATUS_SNAPSHOT
        assert handler.terminal is False

    def test_default_enabled(self, handler: PlanStatusSnapshotHandler) -> None:
        """RV4-m4: opt-OUT -- see the module docstring."""
        assert handler.get_default_enabled() is True

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

    def test_handle_logs_a_warning_for_an_unreadable_plan_and_records_nothing(
        self, handler: PlanStatusSnapshotHandler, caplog: pytest.LogCaptureFixture
    ) -> None:
        """team-lead review-4-prep: _read_plan raises PlanUnreadable for a
        genuinely corrupt/non-UTF-8 file; handle() catches it explicitly,
        logs a WARNING, and records nothing -- goal_injection then falls
        back to its own inference for this tool_use_id."""
        plan = self._plan_path()
        plan.write_bytes(b"\xff\xfe\x00\x01not valid utf-8")

        with caplog.at_level("WARNING"):
            result = handler.handle(self._hook_input(plan, tool_use_id="tu-badbytes"))

        assert result.decision == Decision.ALLOW
        status, found = plan_status_snapshots.consume("tu-badbytes")
        assert found is False
        assert status is None
        assert "plan_status_snapshot" in caplog.text

    def test_handle_raises_via_domain_exception_on_eacces_from_is_file(
        self, handler: PlanStatusSnapshotHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RV4-m3: ``Path.is_file()`` itself can raise (``EACCES`` on an
        unreadable parent directory) -- reverting the existence check to
        run OUTSIDE ``_read_plan``'s try (as a pre-check) let that escape
        as a raw, unwrapped ``PermissionError`` instead of the documented
        ``PlanUnreadable`` -> WARNING -> no-snapshot fail-open contract.

        An unreadable parent directory blocks EVERY traversal through it,
        so both ``is_file`` and ``read_text`` are patched here -- the same
        real-world failure would raise from both, and ``path_is_file``'s
        ``unreadable_means=True`` fallback (eacces_safe_predicates) means
        the stat failure alone does not stop this method; it is the
        SUBSEQUENT read hitting the identical permission error that this
        test pins as still reaching ``PlanUnreadable``."""
        plan = self._write_plan("Not Started")

        def _boom(self: Path, *args: object, **kwargs: object) -> str:
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(Path, "is_file", _boom)
        monkeypatch.setattr(Path, "read_text", _boom)

        result = handler.handle(self._hook_input(plan, tool_use_id="tu-eacces"))

        assert result.decision == Decision.ALLOW
        status, found = plan_status_snapshots.consume("tu-eacces")
        assert found is False
        assert status is None

    def test_get_claude_md_present(self, handler: PlanStatusSnapshotHandler) -> None:
        text = handler.get_claude_md()
        assert text is not None
        assert "plan_status_snapshot" in text
