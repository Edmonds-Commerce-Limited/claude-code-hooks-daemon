"""Tests for plan_qa.model — PlanDoc parser (Plan 00144, Task 1.1).

The parser MUST tolerate mdformat-gfm output because the daemon's
markdown_table_formatter rewrites every written ``.md`` file. Key fixtures
are therefore asserted both raw and after ``format_markdown_text`` round-trip.
"""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.plan_qa.model import (
    TERMINAL_STATUSES,
    PlanDoc,
    PlanLocation,
    PlanStatus,
    PlanTree,
)
from claude_code_hooks_daemon.utils.markdown_format import format_markdown_text

CANONICAL_PLAN = """\
# Plan 00042: Frobnicate The Widget

**Status**: In Progress
**Created**: 2026-07-01
**Owner**: joseph
**Priority**: High

## Overview

Frobnicates the widget so the sprocket aligns.

## Tasks

### Phase 1: Setup

- [ ] ⬜ **Task 1.1**: Do the first thing
- [x] ✅ **Task 1.2**: Done thing
- [ ] 🔄 **Task 1.3**: In-flight thing

## Success Criteria

- [ ] Criterion one
- [x] Criterion two

## Notes & Updates

### 2026-07-01

- Plan scaffolded.
"""

COMPLETE_DATED_PLAN = """\
# Plan 00007: Shipped Work

**Status**: Complete (2026-06-30)
**Created**: 2026-06-01
**Owner**: joseph
**Priority**: Medium

## Tasks

- [x] ✅ **Task 1.1**: Everything
"""

LEGACY_PLAN = """\
# Widget fixes

## Progress

- [✓] first thing done
- [⏳] second thing pending
- [~] third thing partial

ALL DONE!
"""

FENCED_TEMPLATE_PLAN = """\
# Plan 00050: Meta Plan About Plans

**Status**: Not Started
**Created**: 2026-07-07
**Owner**: joseph
**Priority**: Low

## Overview

Documents the template below.

```markdown
**Status**: Complete (2099-01-01)

- [ ] ⬜ **Task 9.9**: template example task
- [x] example ticked box inside a fence
```

## Tasks

- [ ] ⬜ **Task 1.1**: real task
"""


class TestPlanStatusEnum:
    def test_all_expected_tokens_exist(self) -> None:
        tokens = {status.value for status in PlanStatus}
        assert tokens == {
            "Not Started",
            "In Progress",
            "Complete",
            "Blocked",
            "Cancelled",
            "Superseded",
            "Dormant",
        }

    def test_terminal_statuses(self) -> None:
        assert TERMINAL_STATUSES == frozenset(
            {PlanStatus.COMPLETE, PlanStatus.CANCELLED, PlanStatus.SUPERSEDED}
        )

    def test_blocked_and_dormant_are_not_terminal(self) -> None:
        assert PlanStatus.BLOCKED not in TERMINAL_STATUSES
        assert PlanStatus.DORMANT not in TERMINAL_STATUSES


class TestPlanDocHeader:
    def test_parses_plan_number_and_title(self) -> None:
        doc = PlanDoc.parse(CANONICAL_PLAN)
        assert doc.plan_number == 42
        assert doc.title == "Frobnicate The Widget"

    def test_parses_status_token(self) -> None:
        doc = PlanDoc.parse(CANONICAL_PLAN)
        assert doc.status_line_present is True
        assert doc.status == PlanStatus.IN_PROGRESS
        assert doc.status_date is None

    def test_parses_terminal_status_with_date(self) -> None:
        doc = PlanDoc.parse(COMPLETE_DATED_PLAN)
        assert doc.status == PlanStatus.COMPLETE
        assert doc.status_date == "2026-06-30"
        assert doc.is_terminal is True

    def test_terminal_status_without_date_still_parses(self) -> None:
        # THIS repo's convention: no completion dates (git is the SSoT for
        # "when"). The parser stays neutral; date policy lives in checks.
        text = CANONICAL_PLAN.replace("**Status**: In Progress", "**Status**: Complete")
        doc = PlanDoc.parse(text)
        assert doc.status == PlanStatus.COMPLETE
        assert doc.status_date is None
        assert doc.is_terminal is True

    def test_status_with_freeform_qualifier(self) -> None:
        text = CANONICAL_PLAN.replace(
            "**Status**: In Progress",
            "**Status**: Cancelled (superseded by Plan 00110)",
        )
        doc = PlanDoc.parse(text)
        assert doc.status == PlanStatus.CANCELLED
        assert doc.status_raw == "Cancelled (superseded by Plan 00110)"

    def test_unknown_status_token_yields_none_status(self) -> None:
        text = CANONICAL_PLAN.replace("**Status**: In Progress", "**Status**: Doneish")
        doc = PlanDoc.parse(text)
        assert doc.status_line_present is True
        assert doc.status is None
        assert doc.status_raw == "Doneish"

    def test_missing_status_line(self) -> None:
        doc = PlanDoc.parse(LEGACY_PLAN)
        assert doc.status_line_present is False
        assert doc.status is None
        assert doc.status_raw is None
        assert doc.is_terminal is False

    def test_longest_token_wins_not_prefix(self) -> None:
        # "Not Started" must not be mis-read via any shorter token logic.
        text = CANONICAL_PLAN.replace("**Status**: In Progress", "**Status**: Not Started")
        doc = PlanDoc.parse(text)
        assert doc.status == PlanStatus.NOT_STARTED

    def test_parses_template_metadata(self) -> None:
        doc = PlanDoc.parse(CANONICAL_PLAN)
        assert doc.created == "2026-07-01"
        assert doc.owner == "joseph"
        assert doc.priority == "High"

    def test_missing_metadata_is_none(self) -> None:
        doc = PlanDoc.parse(LEGACY_PLAN)
        assert doc.created is None
        assert doc.owner is None
        assert doc.priority is None
        assert doc.plan_number is None
        assert doc.title is None

    def test_only_first_status_line_counts(self) -> None:
        text = CANONICAL_PLAN + "\n**Status**: Complete\n"
        doc = PlanDoc.parse(text)
        assert doc.status == PlanStatus.IN_PROGRESS


class TestPlanDocTasks:
    def test_counts_checkboxes(self) -> None:
        doc = PlanDoc.parse(CANONICAL_PLAN)
        assert doc.tasks.unchecked == 3  # Task 1.1, Task 1.3, criterion one
        assert doc.tasks.checked == 2  # Task 1.2, criterion two

    def test_counts_status_icons_on_list_items(self) -> None:
        doc = PlanDoc.parse(CANONICAL_PLAN)
        assert doc.tasks.icons_todo == 1
        assert doc.tasks.icons_done == 1
        assert doc.tasks.icons_in_progress == 1
        assert doc.tasks.icons_blocked == 0
        assert doc.tasks.icons_cancelled == 0

    def test_total_and_all_checked_properties(self) -> None:
        doc = PlanDoc.parse(COMPLETE_DATED_PLAN)
        assert doc.tasks.total_checkboxes == 1
        assert doc.tasks.all_checked is True
        incomplete = PlanDoc.parse(CANONICAL_PLAN)
        assert incomplete.tasks.total_checkboxes == 5
        assert incomplete.tasks.all_checked is False

    def test_no_checkboxes_means_not_all_checked(self) -> None:
        doc = PlanDoc.parse("# Plan 00001: Empty\n\n**Status**: Not Started\n")
        assert doc.tasks.total_checkboxes == 0
        assert doc.tasks.all_checked is False

    def test_uppercase_x_counts_as_checked(self) -> None:
        doc = PlanDoc.parse("# t\n\n- [X] shouted done\n")
        assert doc.tasks.checked == 1

    def test_detects_legacy_task_grammar(self) -> None:
        doc = PlanDoc.parse(LEGACY_PLAN)
        assert doc.tasks.legacy_marker_lines == 3

    def test_canonical_grammar_has_no_legacy_lines(self) -> None:
        doc = PlanDoc.parse(CANONICAL_PLAN)
        assert doc.tasks.legacy_marker_lines == 0

    def test_fenced_code_blocks_are_ignored(self) -> None:
        doc = PlanDoc.parse(FENCED_TEMPLATE_PLAN)
        # Header status (outside fence) wins; fenced Complete line ignored.
        assert doc.status == PlanStatus.NOT_STARTED
        # Only the real task outside the fence is counted.
        assert doc.tasks.unchecked == 1
        assert doc.tasks.checked == 0
        assert doc.tasks.icons_todo == 1


class TestPlanDocDoneMarkers:
    def test_detects_all_done_marker(self) -> None:
        doc = PlanDoc.parse(LEGACY_PLAN)
        assert doc.done_marker_count >= 1

    def test_detects_all_tasks_complete_marker(self) -> None:
        doc = PlanDoc.parse("# t\n\nAll tasks complete, shipping it.\n")
        assert doc.done_marker_count == 1

    def test_no_done_markers_in_canonical_plan(self) -> None:
        doc = PlanDoc.parse(CANONICAL_PLAN)
        assert doc.done_marker_count == 0

    def test_done_marker_inside_fence_ignored(self) -> None:
        doc = PlanDoc.parse('# t\n\n```\necho "ALL DONE"\n```\n')
        assert doc.done_marker_count == 0


class TestMdformatRoundTrip:
    """Parsing must be stable across the markdown_table_formatter rewrite."""

    def test_canonical_plan_round_trip(self) -> None:
        raw = PlanDoc.parse(CANONICAL_PLAN)
        formatted = PlanDoc.parse(format_markdown_text(CANONICAL_PLAN))
        assert formatted.plan_number == raw.plan_number
        assert formatted.status == raw.status
        assert formatted.created == raw.created
        assert formatted.tasks == raw.tasks
        assert formatted.done_marker_count == raw.done_marker_count

    def test_complete_dated_plan_round_trip(self) -> None:
        formatted = PlanDoc.parse(format_markdown_text(COMPLETE_DATED_PLAN))
        assert formatted.status == PlanStatus.COMPLETE
        assert formatted.status_date == "2026-06-30"
        assert formatted.tasks.all_checked is True

    def test_fenced_plan_round_trip(self) -> None:
        formatted = PlanDoc.parse(format_markdown_text(FENCED_TEMPLATE_PLAN))
        assert formatted.status == PlanStatus.NOT_STARTED
        assert formatted.tasks.unchecked == 1

    def test_real_plan_00144_parses(self) -> None:
        # Live dogfooding fixture: this repo's own plan for this work.
        plan_path = Path(__file__).parents[3] / "CLAUDE/Plan/00144-plan-qa-system/PLAN.md"
        doc = PlanDoc.parse(plan_path.read_text())
        assert doc.plan_number == 144
        assert doc.status == PlanStatus.IN_PROGRESS
        assert doc.tasks.total_checkboxes > 10
        assert doc.tasks.legacy_marker_lines == 0


def _write_plan(folder: Path, number: int, name: str, status: str) -> Path:
    """Create ``folder/NNNNN-name/PLAN.md`` with a minimal valid document."""
    plan_folder = folder / f"{number:05d}-{name}"
    plan_folder.mkdir(parents=True)
    (plan_folder / "PLAN.md").write_text(
        f"# Plan {number:05d}: {name}\n\n**Status**: {status}\n\n- [ ] ⬜ **Task 1.1**: x\n"
    )
    return plan_folder


class TestPlanTreeScan:
    @pytest.fixture
    def plan_root(self, tmp_path: Path) -> Path:
        root = tmp_path / "CLAUDE" / "Plan"
        (root / "Completed").mkdir(parents=True)
        (root / "README.md").write_text("# Plans Index\n")
        return root

    def test_empty_root_scans_clean(self, plan_root: Path) -> None:
        tree = PlanTree.scan(plan_root)
        assert tree.folders == ()
        assert tree.stray_files == ()
        assert tree.has_readme is True
        assert tree.has_completed_dir is True

    def test_missing_structure_is_reported(self, tmp_path: Path) -> None:
        bare = tmp_path / "Plan"
        bare.mkdir()
        tree = PlanTree.scan(bare)
        assert tree.has_readme is False
        assert tree.has_completed_dir is False
        assert tree.has_cancelled_dir is False

    def test_scans_root_plans_with_docs(self, plan_root: Path) -> None:
        _write_plan(plan_root, 1, "first", "In Progress")
        _write_plan(plan_root, 2, "second", "Not Started")
        tree = PlanTree.scan(plan_root)
        assert len(tree.folders) == 2
        by_number = {folder.number: folder for folder in tree.folders}
        assert by_number[1].location == PlanLocation.ROOT
        assert by_number[1].doc is not None
        assert by_number[1].doc.status == PlanStatus.IN_PROGRESS
        assert by_number[2].has_plan_md is True

    def test_scans_completed_and_cancelled_dirs(self, plan_root: Path) -> None:
        (plan_root / "Cancelled").mkdir()
        _write_plan(plan_root / "Completed", 3, "done-thing", "Complete")
        _write_plan(plan_root / "Cancelled", 4, "dead-thing", "Cancelled")
        tree = PlanTree.scan(plan_root)
        by_number = {folder.number: folder for folder in tree.folders}
        assert by_number[3].location == PlanLocation.COMPLETED
        assert by_number[4].location == PlanLocation.CANCELLED
        assert tree.has_cancelled_dir is True

    def test_plan_folder_without_plan_md(self, plan_root: Path) -> None:
        (plan_root / "00005-empty-shell").mkdir()
        tree = PlanTree.scan(plan_root)
        folder = tree.folders[0]
        assert folder.has_plan_md is False
        assert folder.doc is None

    def test_detects_number_collisions_across_locations(self, plan_root: Path) -> None:
        _write_plan(plan_root, 7, "alpha", "In Progress")
        _write_plan(plan_root / "Completed", 7, "beta", "Complete")
        _write_plan(plan_root, 8, "unique", "Not Started")
        tree = PlanTree.scan(plan_root)
        collisions = tree.collisions()
        assert set(collisions) == {7}
        assert {folder.name for folder in collisions[7]} == {"00007-alpha", "00007-beta"}

    def test_no_collisions_returns_empty_dict(self, plan_root: Path) -> None:
        _write_plan(plan_root, 1, "only", "In Progress")
        assert PlanTree.scan(plan_root).collisions() == {}

    def test_stray_files_at_root_detected(self, plan_root: Path) -> None:
        (plan_root / "idempotent-chasing-wadler.md").write_text("orphan notes\n")
        tree = PlanTree.scan(plan_root)
        assert [path.name for path in tree.stray_files] == ["idempotent-chasing-wadler.md"]

    def test_expected_root_files_are_not_stray(self, plan_root: Path) -> None:
        (plan_root / "CLAUDE.md").write_text("lifecycle\n")
        (plan_root / "mkplan.bash").write_text("#!/usr/bin/env bash\n")
        (plan_root / "_TEMPLATE_.md").write_text("# Plan {{PLAN_NUMBER}}\n")
        (plan_root / ".plan-template-default.md").write_text("# snapshot\n")
        tree = PlanTree.scan(plan_root)
        assert tree.stray_files == ()

    def test_plan_folders_in_other_subdir_flagged_as_other(self, plan_root: Path) -> None:
        _write_plan(plan_root / "archive", 9, "old-thing", "Complete")
        tree = PlanTree.scan(plan_root)
        folder = tree.folders[0]
        assert folder.number == 9
        assert folder.location == PlanLocation.OTHER

    def test_date_named_dirs_are_not_plans(self, plan_root: Path) -> None:
        nested = plan_root / "2026-01-12"
        nested.mkdir()
        (nested / "notes.md").write_text("scratch\n")
        tree = PlanTree.scan(plan_root)
        assert tree.folders == ()

    def test_hidden_dirs_ignored(self, plan_root: Path) -> None:
        (plan_root / ".mkplan.lock").mkdir()
        tree = PlanTree.scan(plan_root)
        assert tree.folders == ()
        assert tree.stray_files == ()

    def test_missing_root_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            PlanTree.scan(tmp_path / "nope")

    def test_custom_archive_dir_names(self, tmp_path: Path) -> None:
        root = tmp_path / "Plans"
        (root / "Done").mkdir(parents=True)
        _write_plan(root / "Done", 12, "shipped", "Complete")
        tree = PlanTree.scan(root, completed_dir="Done", cancelled_dir=None)
        assert tree.folders[0].location == PlanLocation.COMPLETED
        assert tree.has_completed_dir is True
        assert tree.has_cancelled_dir is False

    def test_real_repo_plan_tree_scans(self) -> None:
        # Live dogfooding fixture: this repo's actual plan tree.
        root = Path(__file__).parents[3] / "CLAUDE/Plan"
        tree = PlanTree.scan(root)
        numbers = {folder.number for folder in tree.folders}
        assert 144 in numbers
        assert any(folder.location == PlanLocation.COMPLETED for folder in tree.folders)
