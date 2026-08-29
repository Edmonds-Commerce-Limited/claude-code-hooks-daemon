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
from claude_code_hooks_daemon.plan_qa.types import Level


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


class TestStagedContext:
    def test_includes_gitfacts_and_commit_message(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
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
