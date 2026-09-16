"""Tests for the archive-aware plan-link resolver (Plan 00419 Task 1.4, N2).

Archiving a plan moves its folder one level deeper, so every
``](../00NNN-y/PLAN.md)` it contains stops resolving on disk. The project has
already ruled that an archived record is not rewritten and that a ``JOURNAL/``
day-file structurally cannot be, so the tooling has to learn what
``bin/hooks-daemon find-plan`` already knows: a link names a plan NUMBER, and
the plan is wherever it now lives.
"""

from pathlib import Path

from claude_code_hooks_daemon.plan_links import (
    PlanLinkResolver,
    PlanTreeLayout,
    plan_tree_layout,
    split_plan_reference,
)

_LAYOUT = PlanTreeLayout(plan_dir="CLAUDE/Plan", archive_dirs=("Completed", "Cancelled"))


def _tree(root: Path) -> Path:
    """A plan tree with one active plan and one archived plan."""
    plan_dir = root / "CLAUDE" / "Plan"
    (plan_dir / "00414-active-one").mkdir(parents=True)
    (plan_dir / "00414-active-one" / "PLAN.md").write_text("# 414\n")
    (plan_dir / "Completed" / "00413-archived-one").mkdir(parents=True)
    (plan_dir / "Completed" / "00413-archived-one" / "PLAN.md").write_text("# 413\n")
    (plan_dir / "Completed" / "00413-archived-one" / "NIGGLES.md").write_text("# n\n")
    (plan_dir / "Cancelled" / "00091-cancelled-one").mkdir(parents=True)
    (plan_dir / "Cancelled" / "00091-cancelled-one" / "PLAN.md").write_text("# 91\n")
    return root


class TestSplitPlanReference:
    """Which link targets name a plan folder at all."""

    def test_a_parent_relative_plan_link_is_split(self) -> None:
        assert split_plan_reference("../00414-active-one/PLAN.md") == (
            414,
            "PLAN.md",
        )

    def test_the_rightmost_plan_folder_wins(self) -> None:
        """``Completed/00413-x/...`` names 00413, not whatever precedes it."""
        assert split_plan_reference("../Completed/00413-archived-one/PLAN.md") == (
            413,
            "PLAN.md",
        )

    def test_a_nested_remainder_is_preserved(self) -> None:
        assert split_plan_reference("../00414-x/JOURNAL/00414-Journal-26-09-16.md") == (
            414,
            "JOURNAL/00414-Journal-26-09-16.md",
        )

    def test_a_folder_only_link_has_an_empty_remainder(self) -> None:
        assert split_plan_reference("../00414-active-one") == (414, "")

    def test_a_journal_dayfile_is_not_read_as_a_plan_folder(self) -> None:
        """``00413-Journal-26-09-15.md`` is a FILE; treating it as a folder
        would invent a plan reference out of a day-file name."""
        assert split_plan_reference("JOURNAL/00413-Journal-26-09-15.md") is None

    def test_a_target_naming_no_plan_is_none(self) -> None:
        assert split_plan_reference("../../ARCHITECTURE.md") is None

    def test_a_dated_filename_is_not_a_plan_number(self) -> None:
        assert split_plan_reference("notes/2026-09-16-retro.md") is None


class TestResolveAcrossTheWholeTree:
    def test_a_link_to_an_archived_plan_resolves_from_the_archive(self, tmp_path: Path) -> None:
        root = _tree(tmp_path)
        resolver = PlanLinkResolver(root, _LAYOUT)

        relocated = resolver.resolve(
            root / "CLAUDE" / "Plan" / "00414-active-one",
            "../00413-archived-one/PLAN.md",
        )

        assert relocated is not None
        assert relocated.plan_number == 413
        assert relocated.rel_path == "CLAUDE/Plan/Completed/00413-archived-one/PLAN.md"

    def test_a_link_out_of_the_archive_resolves_to_the_active_root(self, tmp_path: Path) -> None:
        """The N2 case: an archived plan's outbound link to a live sibling."""
        root = _tree(tmp_path)
        resolver = PlanLinkResolver(root, _LAYOUT)

        relocated = resolver.resolve(
            root / "CLAUDE" / "Plan" / "Completed" / "00413-archived-one",
            "../00414-active-one/PLAN.md",
        )

        assert relocated is not None
        assert relocated.rel_path == "CLAUDE/Plan/00414-active-one/PLAN.md"

    def test_a_cancelled_plan_is_searched_too(self, tmp_path: Path) -> None:
        root = _tree(tmp_path)
        resolver = PlanLinkResolver(root, _LAYOUT)

        relocated = resolver.resolve(root / "CLAUDE" / "Plan", "00091-cancelled-one/PLAN.md")

        assert relocated is not None
        assert relocated.rel_path == "CLAUDE/Plan/Cancelled/00091-cancelled-one/PLAN.md"

    def test_the_folder_name_need_not_match_only_the_number(self, tmp_path: Path) -> None:
        """A renamed folder is still the same plan — this is find-plan's rule."""
        root = _tree(tmp_path)
        resolver = PlanLinkResolver(root, _LAYOUT)

        relocated = resolver.resolve(root / "CLAUDE" / "Plan", "../00413-old-name/PLAN.md")

        assert relocated is not None
        assert relocated.plan_number == 413

    def test_a_plan_that_never_existed_does_not_resolve(self, tmp_path: Path) -> None:
        """The constraint that keeps the check honest: a genuinely dead link
        stays dead."""
        root = _tree(tmp_path)
        resolver = PlanLinkResolver(root, _LAYOUT)

        assert resolver.resolve(root / "CLAUDE" / "Plan", "../00999-never-was/PLAN.md") is None

    def test_a_file_missing_inside_a_found_plan_does_not_resolve(self, tmp_path: Path) -> None:
        root = _tree(tmp_path)
        resolver = PlanLinkResolver(root, _LAYOUT)

        assert resolver.resolve(root / "CLAUDE" / "Plan", "../00413-x/DESIGN.md") is None

    def test_a_supporting_document_inside_the_archive_resolves(self, tmp_path: Path) -> None:
        root = _tree(tmp_path)
        resolver = PlanLinkResolver(root, _LAYOUT)

        relocated = resolver.resolve(root / "CLAUDE" / "Plan", "../00413-x/NIGGLES.md")

        assert relocated is not None
        assert relocated.rel_path == "CLAUDE/Plan/Completed/00413-archived-one/NIGGLES.md"

    def test_a_target_naming_no_plan_is_not_resolved(self, tmp_path: Path) -> None:
        root = _tree(tmp_path)
        resolver = PlanLinkResolver(root, _LAYOUT)

        assert resolver.resolve(root / "CLAUDE", "../README.md") is None

    def test_an_escaping_remainder_is_contained(self, tmp_path: Path) -> None:
        """The remainder is AUTHORED text; a plain join would answer about the
        host filesystem."""
        root = _tree(tmp_path)
        resolver = PlanLinkResolver(root, _LAYOUT)

        assert resolver.resolve(root, "../00413-x/../../../../../etc/passwd") is None

    def test_an_absent_plan_directory_resolves_nothing(self, tmp_path: Path) -> None:
        resolver = PlanLinkResolver(tmp_path, _LAYOUT)

        assert resolver.resolve(tmp_path, "../00413-x/PLAN.md") is None

    def test_the_active_root_wins_over_an_archive_copy(self, tmp_path: Path) -> None:
        """Two folders with one number is `no-new-collisions`' finding; the
        resolver must still answer, and the LIVE plan is the better answer."""
        root = _tree(tmp_path)
        stale = root / "CLAUDE" / "Plan" / "Completed" / "00414-active-one"
        stale.mkdir(parents=True)
        (stale / "PLAN.md").write_text("# stale 414\n")
        resolver = PlanLinkResolver(root, _LAYOUT)

        relocated = resolver.resolve(root / "CLAUDE" / "Plan", "../00414-x/PLAN.md")

        assert relocated is not None
        assert relocated.rel_path == "CLAUDE/Plan/00414-active-one/PLAN.md"


class TestSuggestedLink:
    """The remediation has to name the path the author should write."""

    def test_names_a_relative_path_from_the_source_document(self, tmp_path: Path) -> None:
        root = _tree(tmp_path)
        resolver = PlanLinkResolver(root, _LAYOUT)
        source_dir = root / "CLAUDE" / "Plan" / "00414-active-one"
        relocated = resolver.resolve(source_dir, "../00413-archived-one/PLAN.md")

        assert relocated is not None
        assert resolver.suggested_link(source_dir, relocated) == (
            "../Completed/00413-archived-one/PLAN.md"
        )


class TestPlanTreeLayoutFromConfig:
    """Every name the resolver needs already has a config home.

    ``plan_workflow.directory``, ``qa.completed_dir``, ``qa.cancelled_dir``
    and ``qa.journal.dir_name`` — so the resolver introduces NO new key, and
    a project that renamed its archive is not silently held to ``Completed``.
    """

    def test_reads_every_name_from_the_plan_workflow_config(self) -> None:
        from claude_code_hooks_daemon.config.models import Config

        config = Config()
        config.plan_workflow.directory = "docs/plans"
        config.plan_workflow.qa.completed_dir = "Done"
        config.plan_workflow.qa.cancelled_dir = "Dropped"
        config.plan_workflow.qa.journal.dir_name = "Diary"

        layout = plan_tree_layout(config.plan_workflow)

        assert layout.plan_dir == "docs/plans"
        assert layout.archive_dirs == ("Done", "Dropped")
        assert layout.journal_dir == "Diary"

    def test_a_project_with_no_cancelled_dir_keeps_one_archive(self) -> None:
        from claude_code_hooks_daemon.config.models import Config

        config = Config()
        config.plan_workflow.qa.cancelled_dir = None

        assert plan_tree_layout(config.plan_workflow).archive_dirs == ("Completed",)

    def test_the_stock_defaults_are_the_config_defaults(self) -> None:
        from claude_code_hooks_daemon.config.models import Config

        layout = plan_tree_layout(Config().plan_workflow)

        assert layout == PlanTreeLayout()


class TestLayoutPredicates:
    def test_a_path_under_the_plan_dir_is_in_the_tree(self) -> None:
        assert _LAYOUT.contains("CLAUDE/Plan/00414-x/PLAN.md") is True

    def test_a_path_outside_the_plan_dir_is_not(self) -> None:
        assert _LAYOUT.contains("CLAUDE/ARCHITECTURE.md") is False

    def test_an_archived_path_is_archived(self) -> None:
        assert _LAYOUT.is_archived("CLAUDE/Plan/Completed/00413-x/PLAN.md") is True
        assert _LAYOUT.is_archived("CLAUDE/Plan/Cancelled/00091-x/PLAN.md") is True

    def test_an_active_path_is_not_archived(self) -> None:
        assert _LAYOUT.is_archived("CLAUDE/Plan/00414-x/PLAN.md") is False

    def test_a_directory_merely_named_like_an_archive_elsewhere_is_not(self) -> None:
        assert _LAYOUT.is_archived("CLAUDE/Completed/x.md") is False

    def test_a_journal_dayfile_is_journal_territory(self) -> None:
        assert _LAYOUT.is_journal("CLAUDE/Plan/00419-x/JOURNAL/00419-Journal-26-09-16.md") is True

    def test_a_plan_document_is_not_journal_territory(self) -> None:
        assert _LAYOUT.is_journal("CLAUDE/Plan/00419-x/PLAN.md") is False

    def test_a_journal_named_directory_outside_the_plan_tree_is_not(self) -> None:
        assert _LAYOUT.is_journal("docs/JOURNAL/notes.md") is False

    def test_a_plan_document_is_recognised(self) -> None:
        assert _LAYOUT.is_plan_document("CLAUDE/Plan/00419-x/PLAN.md") is True
        assert _LAYOUT.is_plan_document("CLAUDE/Plan/00419-x/NIGGLES.md") is False
        assert _LAYOUT.is_plan_document("CLAUDE/PLAN.md") is False
