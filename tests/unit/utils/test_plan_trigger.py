"""Tests for the shared PLAN.md Write/Edit trigger matcher (Plan 00466 RV3-n5).

Both `goal_injection` (PostToolUse) and `plan_status_snapshot` (PreToolUse)
must agree on exactly what counts as "a Write/Edit landing on an active
plan's PLAN.md" -- a snapshot recorded under one definition of the trigger,
consumed under a DIFFERENT one, would silently break the Pre/Post pairing.
This file tests the shared matcher in isolation; `goal_injection`'s own
matches()/handle() delegate to it (see test_goal_injection.py for those).
"""

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core.project_layout import ProjectLayout
from claude_code_hooks_daemon.utils.plan_trigger import (
    FALLBACK_PLAN_DIR,
    is_inside_project,
    matched_plan_write_or_edit,
    plan_dir_for,
    plan_path_pattern,
)

_PLAN_FOLDER = "00123-example"


def _hook_input(file_path: Path, tool: str = "Write") -> dict[str, Any]:
    return {"tool_name": tool, "tool_input": {"file_path": str(file_path)}}


class TestPlanDirFor:
    def test_none_layout_falls_back(self) -> None:
        assert plan_dir_for(None) == FALLBACK_PLAN_DIR

    def test_layout_plan_dir_is_honoured(self) -> None:
        layout = ProjectLayout(
            source_dirs=(),
            test_dirs=(),
            config_dirs=("config",),
            vendor_dirs=frozenset(),
            agent_docs_dir="CLAUDE",
            human_docs_dir="docs",
            plan_dir="Plans",
            plan_archive_dirs=("Completed",),
        )
        assert plan_dir_for(layout) == "Plans"


class TestPlanPathPattern:
    def test_matches_the_shape(self) -> None:
        pattern = plan_path_pattern(FALLBACK_PLAN_DIR)
        assert pattern.search(f"/repo/{FALLBACK_PLAN_DIR}/{_PLAN_FOLDER}/PLAN.md") is not None

    def test_rejects_a_different_filename(self) -> None:
        pattern = plan_path_pattern(FALLBACK_PLAN_DIR)
        assert pattern.search(f"/repo/{FALLBACK_PLAN_DIR}/{_PLAN_FOLDER}/README.md") is None


class TestIsInsideProject:
    @pytest.fixture(autouse=True)
    def mock_project_root(self, tmp_path: Path):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "claude_code_hooks_daemon.utils.plan_trigger.ProjectContext.project_root",
                classmethod(lambda cls: tmp_path),
            )
            self._project = tmp_path
            yield

    def test_path_inside_project_is_true(self) -> None:
        inside = self._project / "CLAUDE" / "Plan" / _PLAN_FOLDER / "PLAN.md"
        inside.parent.mkdir(parents=True)
        inside.write_text("x", encoding="utf-8")
        assert is_inside_project(str(inside)) is True

    def test_path_outside_project_is_false(self, tmp_path_factory: pytest.TempPathFactory) -> None:
        outside = tmp_path_factory.mktemp("outside") / "PLAN.md"
        outside.write_text("x", encoding="utf-8")
        assert is_inside_project(str(outside)) is False


class TestMatchedPlanWriteOrEdit:
    @pytest.fixture(autouse=True)
    def mock_project_root(self, tmp_path: Path):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "claude_code_hooks_daemon.utils.plan_trigger.ProjectContext.project_root",
                classmethod(lambda cls: tmp_path),
            )
            self._project = tmp_path
            yield

    def _write_plan(self, folder: str = _PLAN_FOLDER) -> Path:
        plan_dir = self._project / "CLAUDE" / "Plan" / folder
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "PLAN.md"
        plan_file.write_text("# Example\n", encoding="utf-8")
        return plan_file

    def test_write_on_active_plan_matches(self) -> None:
        plan = self._write_plan()
        result = matched_plan_write_or_edit(_hook_input(plan), None)
        assert result == (str(plan), _PLAN_FOLDER)

    def test_edit_on_active_plan_matches(self) -> None:
        plan = self._write_plan()
        result = matched_plan_write_or_edit(_hook_input(plan, tool="Edit"), None)
        assert result == (str(plan), _PLAN_FOLDER)

    def test_non_write_edit_tool_is_none(self) -> None:
        plan = self._write_plan()
        result = matched_plan_write_or_edit(_hook_input(plan, tool="Read"), None)
        assert result is None

    def test_completed_segment_is_excluded(self) -> None:
        plan_dir = self._project / "CLAUDE" / "Plan" / "Completed" / _PLAN_FOLDER
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "PLAN.md"
        plan_file.write_text("# Example\n", encoding="utf-8")
        result = matched_plan_write_or_edit(_hook_input(plan_file), None)
        assert result is None

    def test_non_plan_md_file_is_none(self) -> None:
        plan_dir = self._project / "CLAUDE" / "Plan" / _PLAN_FOLDER
        plan_dir.mkdir(parents=True)
        other = plan_dir / "NOTES.md"
        other.write_text("x", encoding="utf-8")
        result = matched_plan_write_or_edit(_hook_input(other), None)
        assert result is None

    def test_honours_a_non_default_plan_dir_from_the_layout(self) -> None:
        layout = ProjectLayout(
            source_dirs=(),
            test_dirs=(),
            config_dirs=("config",),
            vendor_dirs=frozenset(),
            agent_docs_dir="CLAUDE",
            human_docs_dir="docs",
            plan_dir="Plans",
            plan_archive_dirs=("Completed",),
        )
        plan_dir = self._project / "Plans" / _PLAN_FOLDER
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "PLAN.md"
        plan_file.write_text("# Example\n", encoding="utf-8")
        result = matched_plan_write_or_edit(_hook_input(plan_file), layout)
        assert result == (str(plan_file), _PLAN_FOLDER)
