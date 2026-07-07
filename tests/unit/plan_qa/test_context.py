"""Tests for plan_qa.context — CheckContext builders for the three surfaces."""

import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.plan_qa.context import (
    edit_context,
    staged_context,
    sweep_context,
)
from claude_code_hooks_daemon.plan_qa.types import Level


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

    def test_level_type_reexport_sanity(self) -> None:
        # Guard against accidental enum drift between surfaces.
        assert Level.BLOCK.value == "block"
        assert Level.ADVISE.value == "advise"
