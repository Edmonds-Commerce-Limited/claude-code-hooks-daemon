"""Tests for plan_qa.context — CheckContext builders for the three surfaces."""

import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core.project_layout import ProjectLayout
from claude_code_hooks_daemon.plan_qa.context import (
    edit_context,
    staged_context,
    sweep_context,
)
from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level
from claude_code_hooks_daemon.utils.git_commit_parsing import extract_commit_pathspecs


@dataclass(frozen=True)
class _Journal:
    """Duck-typed stand-in for PlanWorkflowQaJournalConfig (Plan 00163)."""

    enabled: bool = True
    mode: str = "advise"
    dir_name: str = "JOURNAL"
    freshness_days: int = 3
    enforce_on_completion: bool = False
    grandfather_before: int = 0
    today_only_mode: str = "block"


@dataclass(frozen=True)
class _Policy:
    """Duck-typed stand-in for PlanWorkflowQaConfig (plan_qa stays decoupled)."""

    enabled: bool = True
    completed_dir: str = "Completed"
    cancelled_dir: str | None = "Cancelled"
    edit_mode: str = "block"
    commit_gate_mode: str = "warn"
    sweep_mode: str = "advise"
    require_terminal_date: bool = False
    staleness_days: int = 30
    legacy_plan_allowlist: tuple[int, ...] = ()
    collision_allowlist: tuple[int, ...] = ()
    extra_root_files: tuple[str, ...] = ()
    journal: _Journal = field(default_factory=_Journal)
    plan_doc_size: "_PlanDocSize" = field(default_factory=lambda: _PlanDocSize())


@dataclass(frozen=True)
class _PlanDocSize:
    """Duck-typed stand-in for PlanWorkflowQaPlanDocSizeConfig (Plan 00190)."""

    enabled: bool = True
    advisory_bytes: int = 18_000
    advisory_lines: int = 350
    warning_bytes: int = 25_000
    warning_lines: int = 500
    block_bytes: int = 35_000
    block_lines: int = 900


def _scaffold(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    plan_dir = root / "CLAUDE" / "Plan"
    (plan_dir / "Completed").mkdir(parents=True)
    (plan_dir / "README.md").write_text("# Plans Index\n\n## Active Plans\n")
    folder = plan_dir / "00001-first"
    folder.mkdir()
    (folder / "PLAN.md").write_text("# Plan 00001: first\n\n**Status**: In Progress\n")
    subprocess.run(
        ["git", "init", str(root)],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )
    return root


def _commit_scaffold(root: Path) -> None:
    """Record the scaffold, so the index (what a commit gate reads) holds the plan tree."""
    for args in (
        ("config", "user.email", "t@example.com"),
        ("config", "user.name", "T"),
        ("add", "-A"),
        ("commit", "-m", "initial"),
    ):
        subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            check=True,
            timeout=Timeout.GIT_CONTEXT,
        )


class TestSweepContext:
    def test_builds_tree_readme_gitfacts(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        context = sweep_context(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            policy=_Policy(),
            today=date(2026, 7, 7),
        )
        assert context.tree is not None
        assert {folder.number for folder in context.tree.folders} == {1}
        assert context.readme is not None
        assert context.gitfacts is not None
        assert context.today == date(2026, 7, 7)
        assert context.staleness_days == 30

    def test_policy_values_carried(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        policy = _Policy(
            completed_dir="Completed",
            cancelled_dir=None,
            require_terminal_date=True,
            staleness_days=7,
            legacy_plan_allowlist=(23, 24),
            collision_allowlist=(23,),
        )
        context = sweep_context(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            policy=policy,
            today=date(2026, 7, 7),
        )
        assert context.cancelled_dir is None
        assert context.require_terminal_date is True
        assert context.staleness_days == 7
        assert context.legacy_plan_allowlist == frozenset({23, 24})
        assert context.collision_allowlist == frozenset({23})

    def test_extra_root_files_threaded_into_scan(self, tmp_path: Path) -> None:
        # A configured extra_root_files entry must suppress the stray-file
        # classification for that exact filename (Plan 00153).
        root = _scaffold(tmp_path)
        (root / "CLAUDE/Plan/_planlib.bash").write_text("# sourced helper\n")
        # Without the allowlist it is a stray file.
        without = sweep_context(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            policy=_Policy(),
            today=date(2026, 7, 7),
        )
        assert without.tree is not None
        assert any(p.name == "_planlib.bash" for p in without.tree.stray_files)
        # With the allowlist it is accepted.
        with_allow = sweep_context(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            policy=_Policy(extra_root_files=("_planlib.bash",)),
            today=date(2026, 7, 7),
        )
        assert with_allow.tree is not None
        assert all(p.name != "_planlib.bash" for p in with_allow.tree.stray_files)

    def test_missing_readme_yields_none_readme(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        (root / "CLAUDE/Plan/README.md").unlink()
        context = sweep_context(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            policy=_Policy(),
            today=date(2026, 7, 7),
        )
        assert context.readme is None
        assert context.tree is not None

    def test_missing_plan_dir_raises(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        with pytest.raises(FileNotFoundError):
            sweep_context(
                project_root=root,
                plan_dir_rel="does/not/exist",
                policy=_Policy(),
                today=date(2026, 7, 7),
            )


class TestCompletedArchiveMerge:
    """Plan 00310: rows aged out to Completed/README.md still count as indexed."""

    def test_archive_rows_merge_into_readme_numbers(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        completed = root / "CLAUDE/Plan/Completed"
        (completed / "00099-archived").mkdir()
        (completed / "00099-archived" / "PLAN.md").write_text(
            "# Plan 00099: archived\n\n**Status**: Complete\n"
        )
        (completed / "README.md").write_text(
            "# Completed Plans Archive\n\n"
            "## Completed Plans (Archive)\n\n"
            "- [00099: archived](00099-archived/PLAN.md) - Complete\n"
        )
        context = sweep_context(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            policy=_Policy(),
            today=date(2026, 7, 7),
        )
        assert context.readme is not None
        assert 99 in context.readme.numbers()

    def test_archive_row_link_resolves_relative_to_plan_dir(self, tmp_path: Path) -> None:
        # The archive file's own links are relative to the completed dir, not
        # plan_dir — the merge must rewrite them so row-folder-bijection's
        # link check (relative to plan_dir) still finds the real folder.
        root = _scaffold(tmp_path)
        completed = root / "CLAUDE/Plan/Completed"
        (completed / "00099-archived").mkdir()
        (completed / "00099-archived" / "PLAN.md").write_text(
            "# Plan 00099: archived\n\n**Status**: Complete\n"
        )
        (completed / "README.md").write_text(
            "# Completed Plans Archive\n\n"
            "## Completed Plans (Archive)\n\n"
            "- [00099: archived](00099-archived/PLAN.md) - Complete\n"
        )
        context = sweep_context(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            policy=_Policy(),
            today=date(2026, 7, 7),
        )
        assert context.readme is not None
        rows = context.readme.rows_for(99)
        assert len(rows) == 1
        assert rows[0].link == "Completed/00099-archived/PLAN.md"

    def test_missing_archive_readme_is_a_no_op(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        context = sweep_context(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            policy=_Policy(),
            today=date(2026, 7, 7),
        )
        assert context.readme is not None
        assert context.readme.numbers() == frozenset()


class TestStagedContext:
    def test_includes_gitfacts_and_commit_message(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        _commit_scaffold(root)
        context = staged_context(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            policy=_Policy(),
            commit_message="Plan 00001: do things",
        )
        assert context.gitfacts is not None
        assert context.commit_message == "Plan 00001: do things"
        assert context.tree is not None
        assert context.readme is not None

    def test_pathspecs_scope_gitfacts_to_working_tree(self, tmp_path: Path) -> None:
        """Plan 00200 (Task 3.5): pathspecs thread through to GitFacts so a
        `git commit <pathspec>` sees an UNSTAGED change to that pathspec.
        """

        def _git(repo: Path, *args: str) -> None:
            subprocess.run(
                ["git", "-C", str(repo), *args],
                capture_output=True,
                check=True,
                timeout=Timeout.GIT_CONTEXT,
            )

        root = _scaffold(tmp_path)
        _git(root, "init")
        _git(root, "config", "user.email", "t@example.com")
        _git(root, "config", "user.name", "T")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "initial")

        plan_md = root / "CLAUDE/Plan/00001-first/PLAN.md"
        plan_md.write_text("# Plan 00001: first\n\n**Status**: Complete\n")
        # Deliberately NOT staged — only named as a commit pathspec.

        context = staged_context(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            policy=_Policy(),
            commit_message="Plan 00001: done",
            pathspecs=("CLAUDE/Plan/00001-first/PLAN.md",),
        )

        assert context.gitfacts is not None
        paths = {c.path for c in context.gitfacts.staged_changes()}
        assert paths == {"CLAUDE/Plan/00001-first/PLAN.md"}

    def test_no_pathspecs_is_index_based_as_before(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        _commit_scaffold(root)
        context = staged_context(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            policy=_Policy(),
        )
        assert context.gitfacts is not None
        assert context.gitfacts.staged_changes() == ()


class TestEditContext:
    def test_carries_file_slot_values(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        target = root / "CLAUDE/Plan/00002-new/PLAN.md"
        context = edit_context(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            policy=_Policy(legacy_plan_allowlist=(1,)),
            file_path=target,
            file_content="# Plan 00002: new\n",
            file_exists_before=False,
        )
        assert context.file_path == target
        assert context.file_content == "# Plan 00002: new\n"
        assert context.file_exists_before is False
        assert context.legacy_plan_allowlist == frozenset({1})
        # Edit contexts stay cheap: no tree scan, no git subprocess.
        assert context.tree is None
        assert context.gitfacts is None

    def test_carries_file_content_before(self, tmp_path: Path) -> None:
        # Plan 00163: the append-only journal check needs the pre-edit content.
        root = _scaffold(tmp_path)
        target = root / "CLAUDE/Plan/00163-j/JOURNAL/00163-Journal-26-07-14.md"
        context = edit_context(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            policy=_Policy(),
            file_path=target,
            file_content="prior\nnew\n",
            file_exists_before=True,
            file_content_before="prior\n",
        )
        assert context.file_content_before == "prior\n"

    def test_journal_policy_threaded(self, tmp_path: Path) -> None:
        # Plan 00163: journal knobs reach every surface as flat values.
        root = _scaffold(tmp_path)
        policy = _Policy(
            journal=_Journal(
                mode="block",
                dir_name="LOG",
                freshness_days=7,
                grandfather_before=163,
                today_only_mode="advise",
            )
        )
        context = edit_context(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            policy=policy,
            file_path=root / "CLAUDE/Plan/00163-j/PLAN.md",
            file_content="# Plan 00163: j\n",
            file_exists_before=False,
        )
        assert context.journal_mode == "block"
        assert context.journal_dir_name == "LOG"
        assert context.journal_freshness_days == 7
        assert context.journal_grandfather_before == 163
        assert context.journal_today_only_mode == "advise"

    def test_plan_doc_size_policy_threaded(self, tmp_path: Path) -> None:
        # Plan 00190: size thresholds must be configurable, not hardcoded.
        root = _scaffold(tmp_path)
        policy = _Policy(
            plan_doc_size=_PlanDocSize(
                enabled=False,
                advisory_bytes=1_000,
                advisory_lines=10,
                warning_bytes=2_000,
                warning_lines=20,
                block_bytes=3_000,
                block_lines=30,
            )
        )
        context = edit_context(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            policy=policy,
            file_path=root / "CLAUDE/Plan/00190-s/PLAN.md",
            file_content="# Plan 00190: s\n",
            file_exists_before=False,
        )
        assert context.plan_doc_size.enabled is False
        assert context.plan_doc_size.advisory_bytes == 1_000
        assert context.plan_doc_size.warning_lines == 20
        assert context.plan_doc_size.block_bytes == 3_000

    def test_plan_doc_size_defaults_are_the_documented_tiers(self, tmp_path: Path) -> None:
        """An unconfigured policy yields the Decision 2 read-cost tiers."""
        root = _scaffold(tmp_path)
        context = edit_context(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            policy=_Policy(),
            file_path=root / "CLAUDE/Plan/00190-s/PLAN.md",
            file_content="# Plan 00190: s\n",
            file_exists_before=False,
        )
        limits = context.plan_doc_size
        assert (limits.advisory_bytes, limits.advisory_lines) == (18_000, 350)
        assert (limits.warning_bytes, limits.warning_lines) == (25_000, 500)
        assert (limits.block_bytes, limits.block_lines) == (35_000, 900)

    def test_level_type_reexport_sanity(self) -> None:
        # Guard against accidental enum drift between surfaces.
        assert Level.BLOCK.value == "block"


class TestLayoutThreading:
    """Plan 00288: `layout` is threaded through onto the context, unchanged."""

    def _layout(self) -> ProjectLayout:
        return ProjectLayout(
            source_dirs=(),
            test_dirs=(),
            config_dirs=(),
            vendor_dirs=frozenset(),
            agent_docs_dir="CLAUDE",
            human_docs_dir="docs",
            plan_dir="CLAUDE/Plan",
            plan_archive_dirs=("Completed", "Cancelled"),
        )

    def test_sweep_context_carries_layout(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        layout = self._layout()
        context = sweep_context(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            policy=_Policy(),
            today=date(2026, 7, 7),
            layout=layout,
        )
        assert context.layout is layout

    def test_staged_context_carries_layout(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        _commit_scaffold(root)
        layout = self._layout()
        context = staged_context(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            policy=_Policy(),
            layout=layout,
        )
        assert context.layout is layout

    def test_edit_context_carries_layout(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        layout = self._layout()
        context = edit_context(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            policy=_Policy(),
            file_path=root / "CLAUDE/Plan/00002-new/PLAN.md",
            file_content="# Plan 00002: new\n",
            file_exists_before=False,
            layout=layout,
        )
        assert context.layout is layout

    def test_layout_defaults_to_none(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        context = edit_context(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            policy=_Policy(),
            file_path=root / "CLAUDE/Plan/00002-new/PLAN.md",
            file_content="# Plan 00002: new\n",
            file_exists_before=False,
        )
        assert context.layout is None
        assert Level.ADVISE.value == "advise"


class TestProjectExcludePaths:
    """Plan 00362 Task 2.9: the project-wide ``daemon.exclude_paths`` reaches
    every surface's context, and an excluded plan folder leaves the tree."""

    def test_default_is_nothing_excluded(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        context = sweep_context(root, "CLAUDE/Plan", _Policy(), today=date(2026, 1, 1))
        assert context.exclude_paths == ()

    def test_patterns_are_carried_on_every_surface(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        _commit_scaffold(root)
        patterns = ["CLAUDE/Plan/fixtures/**"]
        sweep = sweep_context(
            root, "CLAUDE/Plan", _Policy(), today=date(2026, 1, 1), exclude_paths=patterns
        )
        staged = staged_context(root, "CLAUDE/Plan", _Policy(), exclude_paths=patterns)
        edit = edit_context(
            root,
            "CLAUDE/Plan",
            _Policy(),
            file_path=root / "CLAUDE/Plan/00001-first/PLAN.md",
            file_content="# Plan 00001: first\n",
            file_exists_before=True,
            exclude_paths=patterns,
        )
        assert sweep.exclude_paths == ("CLAUDE/Plan/fixtures/**",)
        assert staged.exclude_paths == ("CLAUDE/Plan/fixtures/**",)
        assert edit.exclude_paths == ("CLAUDE/Plan/fixtures/**",)

    def test_the_tree_stays_complete_and_only_the_findings_are_dropped(
        self, tmp_path: Path
    ) -> None:
        """Removing the folder from the tree would make the index look wrong
        (a row with no folder), so the exclusion acts on findings, not facts."""
        from claude_code_hooks_daemon.plan_qa.runner import run_stage
        from claude_code_hooks_daemon.plan_qa.types import Stage

        root = _scaffold(tmp_path)
        rogue = root / "CLAUDE" / "Plan" / "00002-rogue"
        rogue.mkdir()
        (rogue / "PLAN.md").write_text("# Plan 00002: rogue\n\n**Status**: Complete\n")

        included = sweep_context(root, "CLAUDE/Plan", _Policy(), today=date(2026, 1, 1))
        excluded = sweep_context(
            root,
            "CLAUDE/Plan",
            _Policy(),
            today=date(2026, 1, 1),
            exclude_paths=["CLAUDE/Plan/00002-rogue/**"],
        )

        assert included.tree is not None and excluded.tree is not None
        assert [folder.name for folder in excluded.tree.folders] == ["00001-first", "00002-rogue"]
        assert any("00002-rogue" in (f.path or "") for f in run_stage(Stage.SWEEP, included))
        assert not any("00002-rogue" in (f.path or "") for f in run_stage(Stage.SWEEP, excluded))


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )


class TestStagedContextReadsTheCommittedTree:
    """Ledger 00474 N244: a bare commit records the index, so the gate reads it."""

    def _committed(self, tmp_path: Path) -> Path:
        root = _scaffold(tmp_path)
        _commit_scaffold(root)
        return root

    def test_a_folder_untracked_from_the_index_leaves_the_tree(self, tmp_path: Path) -> None:
        root = self._committed(tmp_path)
        _git(root, "rm", "-r", "--cached", "-q", "CLAUDE/Plan/00001-first")

        staged = staged_context(root, "CLAUDE/Plan", _Policy())
        sweep = sweep_context(root, "CLAUDE/Plan", _Policy(), today=date(2026, 7, 7))

        assert staged.tree is not None and sweep.tree is not None
        assert staged.tree.folders == ()
        assert [folder.number for folder in sweep.tree.folders] == [1]

    def test_a_folder_deleted_on_disk_but_still_indexed_stays_in_the_tree(
        self, tmp_path: Path
    ) -> None:
        root = self._committed(tmp_path)
        (root / "CLAUDE/Plan/00001-first/PLAN.md").unlink()
        (root / "CLAUDE/Plan/00001-first").rmdir()

        context = staged_context(root, "CLAUDE/Plan", _Policy())

        assert context.tree is not None
        assert [folder.number for folder in context.tree.folders] == [1]
        assert context.tree.folders[0].doc is not None

    def test_documents_are_the_staged_text_not_the_working_tree_text(self, tmp_path: Path) -> None:
        root = self._committed(tmp_path)
        (root / "CLAUDE/Plan/00001-first/PLAN.md").write_text(
            "# Plan 00001: first\n\n**Status**: Complete\n"
        )
        (root / "CLAUDE/Plan/README.md").write_text(
            "# Plans Index\n\n## Active Plans\n\n- [00001: first](00001-first/PLAN.md) - x\n"
        )

        context = staged_context(root, "CLAUDE/Plan", _Policy())

        assert context.tree is not None and context.readme is not None
        assert context.tree.folders[0].doc is not None
        assert context.tree.folders[0].doc.status_raw == "In Progress"
        assert context.readme.rows == ()

    def test_an_archive_directory_kept_empty_is_still_there(self, tmp_path: Path) -> None:
        root = self._committed(tmp_path)

        context = staged_context(root, "CLAUDE/Plan", _Policy())

        assert context.tree is not None
        assert context.tree.has_completed_dir
        assert not context.tree.has_cancelled_dir

    def test_the_archive_index_is_merged_from_the_index(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        (root / "CLAUDE/Plan/Completed/README.md").write_text(
            "## Completed Plans\n\n- [00009: old](00009-old/PLAN.md) - Complete\n"
        )
        _commit_scaffold(root)

        context = staged_context(root, "CLAUDE/Plan", _Policy())

        assert context.readme is not None
        assert 9 in context.readme.numbers()

    def test_a_pathspec_commit_keeps_reading_the_disk(self, tmp_path: Path) -> None:
        root = self._committed(tmp_path)
        _git(root, "rm", "-r", "--cached", "-q", "CLAUDE/Plan/00001-first")

        context = staged_context(
            root, "CLAUDE/Plan", _Policy(), pathspecs=("CLAUDE/Plan/README.md",)
        )

        assert context.tree is not None
        assert [folder.number for folder in context.tree.folders] == [1]

    @staticmethod
    def _statuses(context: CheckContext) -> list[str | None]:
        assert context.tree is not None
        return [f.doc.status_raw if f.doc else None for f in context.tree.folders]

    def test_a_pathspec_relative_to_a_cd_still_reads_the_disk(self, tmp_path: Path) -> None:
        root = self._committed(tmp_path)
        plan = root / "CLAUDE/Plan/00001-first/PLAN.md"
        plan.write_text("# Plan 00001: first\n\n**Status**: Blocked\n")
        command = "cd CLAUDE/Plan && git commit -m x 00001-first/PLAN.md"

        context = staged_context(
            root, "CLAUDE/Plan", _Policy(), pathspecs=extract_commit_pathspecs(command)
        )

        assert self._statuses(context) == ["Blocked"]

    def test_a_pathspec_under_git_dash_c_still_reads_the_disk(self, tmp_path: Path) -> None:
        root = self._committed(tmp_path)
        plan = root / "CLAUDE/Plan/00001-first/PLAN.md"
        plan.write_text("# Plan 00001: first\n\n**Status**: Blocked\n")
        command = "git -C CLAUDE/Plan commit -m x 00001-first/PLAN.md"

        context = staged_context(
            root, "CLAUDE/Plan", _Policy(), pathspecs=extract_commit_pathspecs(command)
        )

        assert self._statuses(context) == ["Blocked"]

    def test_a_pathspec_commit_followed_by_a_bare_one_reads_the_disk(self, tmp_path: Path) -> None:
        root = self._committed(tmp_path)
        plan = root / "CLAUDE/Plan/00001-first/PLAN.md"
        plan.write_text("# Plan 00001: first\n\n**Status**: Blocked\n")
        _git(root, "add", str(plan))
        command = "git commit -m x CLAUDE/Plan/README.md && git commit -m y"

        context = staged_context(
            root, "CLAUDE/Plan", _Policy(), pathspecs=extract_commit_pathspecs(command)
        )

        assert self._statuses(context) == ["Blocked"]

    def test_a_plan_directory_the_commit_does_not_record_is_missing(self, tmp_path: Path) -> None:
        root = self._committed(tmp_path)
        _git(root, "rm", "-r", "--cached", "-q", "CLAUDE/Plan")

        with pytest.raises(FileNotFoundError):
            staged_context(root, "CLAUDE/Plan", _Policy())

    def test_an_unreadable_index_falls_back_to_the_disk(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = self._committed(tmp_path)
        _git(root, "rm", "-r", "--cached", "-q", "CLAUDE/Plan/00001-first")
        monkeypatch.setattr(GitFacts, "index_listing", lambda self, prefix: None)

        context = staged_context(root, "CLAUDE/Plan", _Policy())

        assert context.tree is not None
        assert [folder.number for folder in context.tree.folders] == [1]

    def test_unreadable_documents_fall_back_to_the_disk(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = self._committed(tmp_path)
        _git(root, "rm", "-r", "--cached", "-q", "CLAUDE/Plan/00001-first")
        monkeypatch.setattr(GitFacts, "index_texts", lambda self, listing, paths: None)

        context = staged_context(root, "CLAUDE/Plan", _Policy())

        assert context.tree is not None
        assert [folder.number for folder in context.tree.folders] == [1]

    def test_the_whole_tree_costs_one_listing_and_one_batch_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from claude_code_hooks_daemon.utils.git_repo import read_blobs as real_read_blobs
        from claude_code_hooks_daemon.utils.git_repo import run_git as real_run_git

        root = _scaffold(tmp_path)
        for number in range(2, 12):
            folder = root / "CLAUDE/Plan" / f"{number:05d}-more"
            folder.mkdir()
            (folder / "PLAN.md").write_text(
                f"# Plan {number:05d}: more\n\n**Status**: Not Started\n"
            )
        _commit_scaffold(root)
        listings: list[tuple[str, ...]] = []
        batches: list[int] = []

        def run_git(
            cwd: Path, *args: str, timeout: float = Timeout.GIT_CONTEXT
        ) -> "subprocess.CompletedProcess[str]":
            if args[0] == "ls-files":
                listings.append(args)
            return real_run_git(cwd, *args, timeout=timeout)

        def read_blobs(cwd: Path, shas: "list[str]") -> "dict[str, bytes] | None":
            batches.append(len(shas))
            return real_read_blobs(cwd, shas)

        monkeypatch.setattr("claude_code_hooks_daemon.utils.git_facts.run_git", run_git)
        monkeypatch.setattr("claude_code_hooks_daemon.utils.git_facts.read_blobs", read_blobs)

        context = staged_context(root, "CLAUDE/Plan", _Policy())

        assert context.tree is not None and len(context.tree.folders) == 11
        assert len(listings) == 1
        assert len(batches) == 1
