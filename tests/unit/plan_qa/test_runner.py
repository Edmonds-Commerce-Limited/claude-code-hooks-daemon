"""Tests for plan_qa types, runner, and report (Plan 00144, Task 1.5)."""

from dataclasses import FrozenInstanceError
from pathlib import Path

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
        with pytest.raises(FrozenInstanceError):
            context.plan_dir_rel = "elsewhere"

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
        assert len(by_stage[Stage.EDIT]) == 14
        # 5 commit-only + 5 dual tree checks + 2 journal COMMIT checks (Plan 00163)
        # + plan-shrink-without-journal (Plan 00190) + index-row-length (Plan 00218)
        # + index-no-log + archived-status-coherence (Plan 00286)
        assert len(by_stage[Stage.COMMIT]) == 16
        # 3 sweep-only + 5 dual tree checks + 2 journal SWEEP checks (Plan 00163)
        # + index-row-length (Plan 00218) + index-no-log + 5 document-rule sweep
        # twins and the journal-dayfile-naming sweep twin (Plan 00230)
        assert len(by_stage[Stage.SWEEP]) == 18

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
