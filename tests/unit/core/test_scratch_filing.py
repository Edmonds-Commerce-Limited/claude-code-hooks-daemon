"""Filing proposals for the scratch sweep (Plan 00627 Task 2.5, DESIGN.md section 6)."""

from __future__ import annotations

import builtins
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core.scratch_filing import (
    HINT_NO_HOME,
    HINT_REPOSITORY,
    HINT_SCRIPT,
    HINT_TOO_LARGE,
    HINT_TRACKED,
    FilingProposal,
    PlanIndex,
    Protection,
    build_plan_index,
    move_command,
    propose,
)
from claude_code_hooks_daemon.core.scratch_verdict import Verdict
from claude_code_hooks_daemon.core.scratch_walk import NodeKind

_PLAN_DIR = "CLAUDE/Plan"
_MAX = 262_144


def _plan(project: Path, folder: str) -> Path:
    path = project / _PLAN_DIR / folder
    path.mkdir(parents=True)
    (path / "PLAN.md").write_text("# Plan: x\n\n**Status**: In Progress\n")
    return path


def _propose(
    project: Path,
    name: str,
    *,
    plans: PlanIndex | None = None,
    kind: NodeKind = NodeKind.FILE,
    size: int = 10,
    verdict: Verdict = Verdict.UNCERTAIN,
    protection: Protection = Protection.NONE,
    relative_root: str | None = "untracked/scratch",
) -> FilingProposal | None:
    return propose(
        name,
        kind=kind,
        size=size,
        verdict=verdict,
        protection=protection,
        plans=plans or PlanIndex({}),
        project_root=project,
        relative_root=relative_root,
        max_bytes=_MAX,
    )


class TestPlanIndex:
    def test_no_plan_directory_is_an_empty_index(self, tmp_path: Path) -> None:
        assert build_plan_index(tmp_path, None).folders == {}

    def test_an_archived_plan_is_found(self, tmp_path: Path) -> None:
        _plan(tmp_path, "Completed/00412-old")
        index = build_plan_index(tmp_path, _PLAN_DIR)
        assert index.folder(412) == f"{_PLAN_DIR}/Completed/00412-old"

    def test_an_active_plan_beats_an_archived_one(self, tmp_path: Path) -> None:
        _plan(tmp_path, "Completed/00412-old")
        _plan(tmp_path, "00412-new")
        assert build_plan_index(tmp_path, _PLAN_DIR).folder(412) == f"{_PLAN_DIR}/00412-new"

    def test_two_active_plans_with_one_number_are_ambiguous(self, tmp_path: Path) -> None:
        _plan(tmp_path, "00412-a")
        _plan(tmp_path, "00412-b")
        index = build_plan_index(tmp_path, _PLAN_DIR)
        assert index.folder(412) == f"{_PLAN_DIR}/00412-a"
        assert index.ambiguous(412)


class TestSignals:
    def test_live_stuck_and_disposable_get_no_proposal(self, tmp_path: Path) -> None:
        for verdict in (Verdict.LIVE, Verdict.STUCK, Verdict.DISPOSABLE):
            assert _propose(tmp_path, "notes.txt", verdict=verdict) is None

    def test_protected_by_a_repository_is_text_only(self, tmp_path: Path) -> None:
        proposal = _propose(
            tmp_path, "clone", verdict=Verdict.PROTECTED, protection=Protection.REPOSITORY
        )
        assert proposal == FilingProposal(HINT_REPOSITORY, "")
        assert "commit and push to a branch on the remote" in HINT_REPOSITORY

    def test_protected_by_a_tracked_file_is_for_a_human(self, tmp_path: Path) -> None:
        proposal = _propose(
            tmp_path, "00627-x.md", verdict=Verdict.PROTECTED, protection=Protection.TRACKED
        )
        assert proposal == FilingProposal(HINT_TRACKED, "")

    def test_too_large_beats_a_plan_number(self, tmp_path: Path) -> None:
        _plan(tmp_path, "00627-x")
        plans = build_plan_index(tmp_path, _PLAN_DIR)
        proposal = _propose(tmp_path, "00627-report.md", plans=plans, size=_MAX + 1)
        assert proposal == FilingProposal(HINT_TOO_LARGE, "")

    def test_a_plan_numbered_file_gets_a_move_command(self, tmp_path: Path) -> None:
        _plan(tmp_path, "00627-x")
        plans = build_plan_index(tmp_path, _PLAN_DIR)
        proposal = _propose(tmp_path, "00627-report.md", plans=plans, verdict=Verdict.REFERENCED)
        assert proposal == FilingProposal(
            f"{_PLAN_DIR}/00627-x/subagent-reports/",
            f"mv -n -- untracked/scratch/00627-report.md {_PLAN_DIR}/00627-x/subagent-reports/",
        )

    def test_the_plan_number_is_compared_as_an_integer(self, tmp_path: Path) -> None:
        _plan(tmp_path, "00007-x")
        plans = build_plan_index(tmp_path, _PLAN_DIR)
        proposal = _propose(tmp_path, "007_notes", plans=plans)
        assert proposal is not None
        assert proposal.destination == f"{_PLAN_DIR}/00007-x/subagent-reports/"

    @pytest.mark.parametrize("name", ["261120-task.md", "12-x.md", "00627x.md"])
    def test_a_name_outside_the_plan_pattern_gets_no_plan(self, tmp_path: Path, name: str) -> None:
        _plan(tmp_path, "00627-x")
        _plan(tmp_path, "00012-x")
        _plan(tmp_path, "261120-x")
        plans = build_plan_index(tmp_path, _PLAN_DIR)
        assert _propose(tmp_path, name, plans=plans) == FilingProposal(HINT_NO_HOME, "")

    def test_a_bare_plan_number_matches(self, tmp_path: Path) -> None:
        _plan(tmp_path, "00627-x")
        proposal = _propose(tmp_path, "00627", plans=build_plan_index(tmp_path, _PLAN_DIR))
        assert proposal is not None
        assert proposal.command.startswith("mv -n -- ")

    def test_a_number_with_no_plan_falls_through(self, tmp_path: Path) -> None:
        plans = build_plan_index(tmp_path, _PLAN_DIR)
        assert _propose(tmp_path, "00999-run.sh", plans=plans) == FilingProposal(HINT_SCRIPT, "")

    def test_a_directory_going_to_a_plan_gets_no_command(self, tmp_path: Path) -> None:
        _plan(tmp_path, "00627-x")
        plans = build_plan_index(tmp_path, _PLAN_DIR)
        proposal = _propose(tmp_path, "00627-run", plans=plans, kind=NodeKind.DIRECTORY)
        assert proposal == FilingProposal(f"{_PLAN_DIR}/00627-x/subagent-reports/", "")

    def test_an_ambiguous_plan_gets_no_command(self, tmp_path: Path) -> None:
        _plan(tmp_path, "00627-a")
        _plan(tmp_path, "00627-b")
        proposal = _propose(tmp_path, "00627-r.md", plans=build_plan_index(tmp_path, _PLAN_DIR))
        assert proposal is not None
        assert proposal.command == ""

    def test_an_existing_destination_gets_no_command(self, tmp_path: Path) -> None:
        plan = _plan(tmp_path, "00627-x")
        (plan / "subagent-reports").mkdir()
        (plan / "subagent-reports" / "00627-r.md").write_text("held")
        proposal = _propose(tmp_path, "00627-r.md", plans=build_plan_index(tmp_path, _PLAN_DIR))
        assert proposal is not None
        assert (proposal.destination, proposal.command) == (
            f"{_PLAN_DIR}/00627-x/subagent-reports/",
            "",
        )

    def test_a_dangling_link_at_the_destination_counts_as_existing(self, tmp_path: Path) -> None:
        plan = _plan(tmp_path, "00627-x")
        (plan / "subagent-reports").mkdir()
        (plan / "subagent-reports" / "00627-r.md").symlink_to(tmp_path / "nowhere")
        proposal = _propose(tmp_path, "00627-r.md", plans=build_plan_index(tmp_path, _PLAN_DIR))
        assert proposal is not None
        assert proposal.command == ""

    def test_an_unprintable_name_gets_no_command(self, tmp_path: Path) -> None:
        _plan(tmp_path, "00627-x")
        proposal = _propose(tmp_path, "00627-a\nb", plans=build_plan_index(tmp_path, _PLAN_DIR))
        assert proposal is not None
        assert proposal.command == ""

    def test_a_root_outside_the_project_gets_no_command(self, tmp_path: Path) -> None:
        _plan(tmp_path, "00627-x")
        proposal = _propose(
            tmp_path,
            "00627-r.md",
            plans=build_plan_index(tmp_path, _PLAN_DIR),
            relative_root=None,
        )
        assert proposal is not None
        assert proposal.command == ""

    @pytest.mark.parametrize("name", ["run.py", "go.sh", "x.bash"])
    def test_a_script_is_hinted_without_a_command(self, tmp_path: Path, name: str) -> None:
        assert _propose(tmp_path, name) == FilingProposal(HINT_SCRIPT, "")

    def test_a_script_beats_release_wording(self, tmp_path: Path) -> None:
        assert _propose(tmp_path, "release.sh") == FilingProposal(HINT_SCRIPT, "")

    @pytest.mark.parametrize("name", ["release-notes.md", "UPGRADE_x.txt"])
    def test_release_wording_in_the_name(self, tmp_path: Path, name: str) -> None:
        assert _propose(tmp_path, name) == FilingProposal("CLAUDE/UPGRADES/UNRELEASED/", "")

    def test_otherwise_no_tracked_home(self, tmp_path: Path) -> None:
        assert _propose(tmp_path, "notes.txt") == FilingProposal(HINT_NO_HOME, "")

    def test_no_file_is_opened(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _plan(tmp_path, "00627-x")
        plans = build_plan_index(tmp_path, _PLAN_DIR)

        def refuse(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("a file was opened")

        monkeypatch.setattr(builtins, "open", refuse)
        monkeypatch.setattr(Path, "open", refuse)
        for name in ("00627-r.md", "run.py", "release.md", "notes.txt"):
            assert _propose(tmp_path, name, plans=plans) is not None


class TestMoveCommand:
    def test_both_sides_are_quoted_and_the_slash_is_kept(self) -> None:
        assert (
            move_command("untracked/scratch", "00627 a.md", "CLAUDE/Plan/00627 x/subagent-reports")
            == "mv -n -- 'untracked/scratch/00627 a.md' 'CLAUDE/Plan/00627 x/subagent-reports/'"
        )

    @pytest.mark.parametrize("name", ["-rf", "a\tb", "a\x1bb", ""])
    def test_an_unsafe_name_gets_none(self, name: str) -> None:
        assert move_command("untracked/scratch", name, "CLAUDE/Plan/1-x/subagent-reports") == ""

    def test_an_unprintable_destination_gets_none(self) -> None:
        assert move_command("untracked/scratch", "a.md", "CLAUDE/Plan/1-\nx/subagent-reports") == ""


class TestNoRemoval:
    def test_no_hint_or_command_names_a_removal(self) -> None:
        texts = [
            HINT_REPOSITORY,
            HINT_TRACKED,
            HINT_TOO_LARGE,
            HINT_SCRIPT,
            HINT_NO_HOME,
            "CLAUDE/UPGRADES/UNRELEASED/",
            move_command("untracked/scratch", "00627-a.md", "CLAUDE/Plan/00627-x/subagent-reports"),
        ]
        for text in texts:
            for word in ("rm ", "delete", "--apply", "unlink"):
                assert word not in text.lower()
