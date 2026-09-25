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
    reset_warned_unresolved_paths,
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

    def test_symlink_loop_never_raises(self) -> None:
        """RV4-n7: a symlink-loop PLAN.md raises RuntimeError from
        Path.resolve() (Python's own maximum-recursion detection) --
        is_inside_project's except clause must catch it alongside
        (ValueError, OSError), not let it escape raw. Pre-existing shape,
        copied from goal_injection's own version."""
        loop_dir = self._project / "CLAUDE" / "Plan" / _PLAN_FOLDER
        loop_dir.mkdir(parents=True)
        looped = loop_dir / "PLAN.md"
        looped.symlink_to(looped)

        assert is_inside_project(str(looped)) is False


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

    def test_a_symlinked_plan_folder_resolves_to_the_targets_number(self) -> None:
        """RV7-m3: a plan reached through a symlinked alias
        (``00301-l -> 00300-c``) must be captured under the TARGET's
        folder, ``00300-c`` -- not the link's own name, ``00301-l``, which
        goal_injection would then ledger under a number that never retires
        (no plan directory ``00301-l`` genuinely exists to complete)."""
        target = self._write_plan("00300-c")
        link_dir = self._project / "CLAUDE" / "Plan" / "00301-l"
        link_dir.symlink_to(target.parent, target_is_directory=True)
        linked_plan = link_dir / "PLAN.md"

        result = matched_plan_write_or_edit(_hook_input(linked_plan), None)

        assert result == (str(linked_plan), "00300-c")

    def test_a_resolved_path_outside_the_pattern_warns_only_once_per_path(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """RV8-n4: `matched_plan_write_or_edit` runs once at PreToolUse and
        once at PostToolUse for the SAME tool call (`plan_status_snapshot`
        and `goal_injection` each call it), so an unchanged resolved-outside-
        pattern path (a symlinked alias) would otherwise log the WARNING
        TWICE per call. It must fire only the first time for a given path."""
        reset_warned_unresolved_paths()
        target = self._project / "CLAUDE" / "Plan" / "Completed" / "00300-c"
        target.mkdir(parents=True)
        (target / "PLAN.md").write_text("# Example\n", encoding="utf-8")
        link_dir = self._project / "CLAUDE" / "Plan" / "00301-l"
        link_dir.symlink_to(target, target_is_directory=True)
        linked_plan = link_dir / "PLAN.md"

        import logging

        with caplog.at_level(logging.WARNING, logger="claude_code_hooks_daemon.utils.plan_trigger"):
            first = matched_plan_write_or_edit(_hook_input(linked_plan), None)
            second = matched_plan_write_or_edit(_hook_input(linked_plan), None)

        assert first is None
        assert second is None
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1

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
