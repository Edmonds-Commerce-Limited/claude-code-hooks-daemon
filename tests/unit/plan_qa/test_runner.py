"""Tests for plan_qa types, runner, and report (Plan 00144, Task 1.5)."""

from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.plan_qa.runner import run_stage
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)


def _context() -> CheckContext:
    return CheckContext(
        project_root=Path("/tmp/example"),
        plan_dir_rel="CLAUDE/Plan",
    )


def _finding(check_id: str = "test-check", level: Level = Level.BLOCK) -> Finding:
    return Finding(
        check_id=check_id,
        level=level,
        message="the invariant that was violated",
        remediation="the exact fix to apply",
        path="CLAUDE/Plan/00001-x/PLAN.md",
    )


def _spec(check_id: str, stage: Stage, findings: list[Finding]) -> CheckSpec:
    return CheckSpec(
        check_id=check_id,
        stage=stage,
        level=Level.BLOCK,
        sins=("A1",),
        run=lambda context: findings,
    )


class TestRunStage:
    def test_runs_only_matching_stage(self) -> None:
        edit_finding = _finding("edit-check")
        sweep_finding = _finding("sweep-check")
        registry = (
            _spec("edit-check", Stage.EDIT, [edit_finding]),
            _spec("sweep-check", Stage.SWEEP, [sweep_finding]),
        )
        result = run_stage(Stage.EDIT, _context(), registry=registry)
        assert result == [edit_finding]

    def test_accumulates_findings_across_checks(self) -> None:
        registry = (
            _spec("one", Stage.COMMIT, [_finding("one")]),
            _spec("two", Stage.COMMIT, [_finding("two")]),
            _spec("clean", Stage.COMMIT, []),
        )
        result = run_stage(Stage.COMMIT, _context(), registry=registry)
        assert [finding.check_id for finding in result] == ["one", "two"]

    def test_default_registry_is_used_when_none_given(self) -> None:
        # The real registry must at least be loadable and filterable.
        result = run_stage(Stage.EDIT, _context())
        assert isinstance(result, list)

    def test_context_is_frozen(self) -> None:
        context = _context()
        # Aliased through Any: see test_types.py's TestFinding.test_is_frozen
        # for why -- the assignment itself is what raises FrozenInstanceError.
        mutable_context: Any = context
        with pytest.raises(FrozenInstanceError):
            mutable_context.plan_dir_rel = "elsewhere"

    def test_plan_dir_property(self) -> None:
        context = CheckContext(project_root=Path("/repo"), plan_dir_rel="CLAUDE/Plan")
        assert context.plan_dir == Path("/repo/CLAUDE/Plan")


class TestRegistryCatalogue:
    """The assembled registry must carry the full Plan 00144 check catalogue."""

    def test_all_check_ids_registered(self) -> None:
        from claude_code_hooks_daemon.plan_qa.checks import all_checks

        ids = {spec.check_id for spec in all_checks()}
        assert ids == {
            # Stage 1 — edit-time
            "status-line-present",
            "status-enum-and-date",
            "header-body-coherence",
            "template-metadata",
            "task-grammar",
            "terminal-placement-hint",
            "archive-immutability",
            "path-existence",
            "journal-dayfile-naming",
            "journal-dayfile-is-today",
            "journal-entry-ordering",
            "journal-entry-future-dated",
            "journal-append-only",
            "plan-doc-size",
            # Cross-file tree checks (dual COMMIT+SWEEP registration)
            "no-new-collisions",
            "row-folder-bijection",
            "stats-recount",
            "structure-archive-dirs",
            "location-status-coherence",
            # Plan-index shape (EDIT + COMMIT + SWEEP registration)
            "index-row-length",
            "index-no-log",
            # Commit-only
            "index-at-birth",
            "counter-sanity",
            "terminal-state-atomic",
            "archived-status-coherence",
            "same-commit-plan-doc",
            "plan-ref-format",
            "journal-entry-with-progress",
            "journal-completion-entry",
            "plan-shrink-without-journal",
            # Sweep-only
            "staleness-nag",
            "dormant-honesty",
            "claim-spotcheck-queue",
            "journal-folder-present",
            "journal-freshness",
        }

    def test_stage_counts(self) -> None:
        from claude_code_hooks_daemon.plan_qa.checks import all_checks

        registry = all_checks()
        by_stage = {stage: [spec for spec in registry if spec.stage == stage] for stage in Stage}
        # 8 original + 2 journal EDIT checks (Plan 00163) + plan-doc-size
        # (Plan 00190) + journal-dayfile-is-today (Plan 00197)
        # + index-row-length (Plan 00218) + index-no-log
        # + journal-entry-ordering (Plan 00377 N1)
        # + journal-entry-future-dated (Plan 00377 N9; EDIT only by design)
        assert len(by_stage[Stage.EDIT]) == 16
        # 5 commit-only + 5 dual tree checks + 2 journal COMMIT checks (Plan 00163)
        # + plan-shrink-without-journal (Plan 00190) + index-row-length (Plan 00218)
        # + index-no-log + archived-status-coherence (Plan 00286)
        assert len(by_stage[Stage.COMMIT]) == 16
        # 3 sweep-only + 5 dual tree checks + 2 journal SWEEP checks (Plan 00163)
        # + index-row-length (Plan 00218) + index-no-log + 5 document-rule sweep
        # twins and the journal-dayfile-naming sweep twin (Plan 00230)
        # + the journal-entry-ordering sweep twin (Plan 00377 N1)
        assert len(by_stage[Stage.SWEEP]) == 19

    def test_dual_stage_checks_share_run_function(self) -> None:
        from claude_code_hooks_daemon.plan_qa.checks import all_checks

        registry = all_checks()
        dual_ids = {
            "no-new-collisions",
            "row-folder-bijection",
            "stats-recount",
            "structure-archive-dirs",
            "location-status-coherence",
        }
        for check_id in dual_ids:
            specs = [spec for spec in registry if spec.check_id == check_id]
            assert {spec.stage for spec in specs} == {Stage.COMMIT, Stage.SWEEP}
            assert specs[0].run is specs[1].run

    def test_every_spec_declares_sins(self) -> None:
        from claude_code_hooks_daemon.plan_qa.checks import all_checks

        # Journal checks (Plan 00163, extended Plan 00197), plan-doc-size
        # (Plan 00190), index-row-length (Plan 00218) and index-no-log are
        # post-audit feature categories — they defend journalling hygiene,
        # plan read-cost, index navigability and index-as-changelog-creep
        # respectively, not one of the original 31-sin audit findings, so they
        # legitimately carry no `sins` provenance.
        post_audit_no_sins = {
            "journal-dayfile-naming",
            "journal-dayfile-is-today",
            "journal-entry-ordering",
            "journal-entry-future-dated",
            "journal-append-only",
            "journal-folder-present",
            "journal-freshness",
            "journal-entry-with-progress",
            "journal-completion-entry",
            "plan-doc-size",
            "plan-shrink-without-journal",
            "index-row-length",
            "index-no-log",
        }
        for spec in all_checks():
            if spec.check_id in post_audit_no_sins:
                assert spec.sins == (), f"{spec.check_id} should declare no sins"
                continue
            assert spec.sins, f"{spec.check_id} declares no sins"


_EXCLUDING = ("CLAUDE/Plan/00001-x/**",)


def _excluding_context(file_path: Path | None = None) -> CheckContext:
    return CheckContext(
        project_root=Path("/tmp/example"),
        plan_dir_rel="CLAUDE/Plan",
        exclude_paths=_EXCLUDING,
        file_path=file_path,
        file_content=None if file_path is None else "x",
    )


class TestExcludePaths:
    """Plan 00362 Task 2.9: findings about an excluded path never leave the runner."""

    def test_finding_on_an_excluded_relative_path_is_dropped(self) -> None:
        kept = Finding("k", Level.BLOCK, "m", "r", path="CLAUDE/Plan/00002-y/PLAN.md")
        dropped = _finding("d")  # path CLAUDE/Plan/00001-x/PLAN.md
        registry = (_spec("c", Stage.SWEEP, [kept, dropped]),)
        assert run_stage(Stage.SWEEP, _excluding_context(), registry=registry) == [kept]

    def test_finding_keyed_by_plan_folder_name_is_dropped(self) -> None:
        # Tree checks (row-folder-bijection, location-status-coherence) key
        # their findings on the bare folder name, not a project-relative path.
        dropped = Finding("d", Level.ADVISE, "m", "r", path="00001-x")
        kept = Finding("k", Level.ADVISE, "m", "r", path="00002-y")
        registry = (_spec("c", Stage.SWEEP, [dropped, kept]),)
        assert run_stage(Stage.SWEEP, _excluding_context(), registry=registry) == [kept]

    def test_finding_without_a_path_is_kept(self) -> None:
        pathless = Finding("p", Level.ADVISE, "m", "r", path=None)
        registry = (_spec("c", Stage.SWEEP, [pathless]),)
        assert run_stage(Stage.SWEEP, _excluding_context(), registry=registry) == [pathless]

    def test_edit_of_an_excluded_file_runs_no_check(self) -> None:
        calls: list[str] = []

        def run(context: CheckContext) -> list[Finding]:
            calls.append("ran")
            return [_finding("d")]

        registry = (CheckSpec("c", Stage.EDIT, Level.BLOCK, ("A1",), run),)
        context = _excluding_context(Path("/tmp/example/CLAUDE/Plan/00001-x/PLAN.md"))
        assert run_stage(Stage.EDIT, context, registry=registry) == []
        assert calls == []

    def test_nothing_configured_changes_nothing(self) -> None:
        finding = _finding("d")
        registry = (_spec("c", Stage.SWEEP, [finding]),)
        assert run_stage(Stage.SWEEP, _context(), registry=registry) == [finding]
