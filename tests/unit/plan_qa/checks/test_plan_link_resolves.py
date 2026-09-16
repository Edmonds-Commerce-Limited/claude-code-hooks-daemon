"""Tests for check ``plan-link-resolves`` (Plan 00419 Task 1.4, N2).

The sweep reported the tree CLEAN with eight dead plan links in it, because no
plan-QA check resolved links at all. This check closes that gap at SWEEP and at
ADVISE only: docs-QA's ``pointer-resolves`` already blocks a link that is NEW in
an edit or a commit, and a second blocking gate on the same fact is the
double-gate shape the same ledger's N3 is about.
"""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from claude_code_hooks_daemon.plan_qa.checks import all_checks
from claude_code_hooks_daemon.plan_qa.checks.plan_link_resolves import CHECK_ID, CHECKS
from claude_code_hooks_daemon.plan_qa.context import sweep_context
from claude_code_hooks_daemon.plan_qa.runner import run_stage
from claude_code_hooks_daemon.plan_qa.types import Finding, Level, Stage

_TODAY = date(2026, 9, 16)
_ACTIVE = "# Plan 00419: live\n\n**Status**: In Progress\n\n- [ ] ⬜ **Task 1.1**: x\n"
_ARCHIVED = "# Plan 00413: done\n\n**Status**: Complete\n"


@dataclass(frozen=True)
class _Journal:
    """Duck-typed stand-in for PlanWorkflowQaJournalConfig, switched off.

    The journal rules are a separate concern; leaving them on would mix their
    findings into every assertion here.
    """

    enabled: bool = False
    mode: str = "off"
    dir_name: str = "JOURNAL"
    freshness_days: int = 3
    enforce_on_completion: bool = False
    grandfather_before: int = 0
    today_only_mode: str = "off"


@dataclass(frozen=True)
class _PlanDocSize:
    """Duck-typed stand-in for PlanWorkflowQaPlanDocSizeConfig."""

    enabled: bool = True
    advisory_bytes: int = 18_000
    advisory_lines: int = 350
    warning_bytes: int = 25_000
    warning_lines: int = 500
    block_bytes: int = 35_000
    block_lines: int = 900


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
    plan_doc_size: _PlanDocSize = field(default_factory=_PlanDocSize)


def _plan_tree(tmp_path: Path) -> Path:
    """A tree with one live plan and one archived plan that links to it."""
    root = tmp_path / "repo"
    plan_dir = root / "CLAUDE" / "Plan"
    (plan_dir / "Cancelled").mkdir(parents=True)
    (plan_dir / "00419-live").mkdir(parents=True)
    (plan_dir / "00419-live" / "PLAN.md").write_text(_ACTIVE)
    (plan_dir / "Completed" / "00413-done").mkdir(parents=True)
    (plan_dir / "Completed" / "00413-done" / "PLAN.md").write_text(_ARCHIVED)
    (plan_dir / "README.md").write_text(
        "# Plans Index\n\n## Active Plans\n\n"
        "- [00419: live](00419-live/PLAN.md) - In Progress\n\n"
        "## Completed Plans\n\n"
        "- [00413: done](Completed/00413-done/PLAN.md) - Complete\n"
    )
    return root


def _findings(root: Path) -> list[Finding]:
    context = sweep_context(root, "CLAUDE/Plan", _Policy(), today=_TODAY)
    return [f for f in run_stage(Stage.SWEEP, context) if f.check_id == CHECK_ID]


class TestRegistration:
    def test_registers_at_sweep_only(self) -> None:
        assert {spec.stage for spec in CHECKS} == {Stage.SWEEP}

    def test_never_registers_at_block(self) -> None:
        """The edit under judgement did not move the target."""
        assert {spec.level for spec in CHECKS} == {Level.ADVISE}

    def test_is_in_the_catalogue(self) -> None:
        assert CHECK_ID in {spec.check_id for spec in all_checks()}


class TestALivePlanLinkingToAnArchivedSibling:
    def test_is_reported_at_advise(self, tmp_path: Path) -> None:
        root = _plan_tree(tmp_path)
        (root / "CLAUDE/Plan/00419-live/PLAN.md").write_text(
            _ACTIVE + "\nSee [00413](../00413-done/PLAN.md).\n"
        )

        findings = _findings(root)

        assert len(findings) == 1
        assert findings[0].level is Level.ADVISE
        assert findings[0].path == "CLAUDE/Plan/00419-live/PLAN.md"

    def test_the_remediation_names_the_new_path(self, tmp_path: Path) -> None:
        root = _plan_tree(tmp_path)
        (root / "CLAUDE/Plan/00419-live/PLAN.md").write_text(
            _ACTIVE + "\nSee [00413](../00413-done/PLAN.md).\n"
        )

        assert "../Completed/00413-done/PLAN.md" in _findings(root)[0].remediation


class TestTheHistoricalRecordIsNotNagged:
    def test_an_archived_plan_linking_via_the_archive_is_not_a_finding(
        self, tmp_path: Path
    ) -> None:
        """Truth is enforced on LIVE plans, never on the historical record."""
        root = _plan_tree(tmp_path)
        (root / "CLAUDE/Plan/Completed/00413-done/PLAN.md").write_text(
            _ARCHIVED + "\nSee [00419](../00419-live/PLAN.md).\n"
        )

        assert _findings(root) == []


class TestAGenuinelyDeadLinkStaysDead:
    def test_a_link_to_a_plan_that_never_existed_is_reported(self, tmp_path: Path) -> None:
        root = _plan_tree(tmp_path)
        (root / "CLAUDE/Plan/00419-live/PLAN.md").write_text(
            _ACTIVE + "\nSee [gone](../00999-never-was/PLAN.md).\n"
        )

        findings = _findings(root)

        assert len(findings) == 1
        assert "00999-never-was" in findings[0].message

    def test_a_dead_link_from_an_archived_plan_is_not_reported(self, tmp_path: Path) -> None:
        """An archived record is left exactly as written, dead links and all."""
        root = _plan_tree(tmp_path)
        (root / "CLAUDE/Plan/Completed/00413-done/PLAN.md").write_text(
            _ARCHIVED + "\nSee [gone](../00999-never-was/PLAN.md).\n"
        )

        assert _findings(root) == []


class TestLinksThatAreFine:
    def test_a_resolving_link_is_not_reported(self, tmp_path: Path) -> None:
        root = _plan_tree(tmp_path)
        (root / "CLAUDE/Plan/00419-live/PLAN.md").write_text(
            _ACTIVE + "\nSee [00413](../Completed/00413-done/PLAN.md).\n"
        )

        assert _findings(root) == []

    def test_an_external_url_is_not_reported(self, tmp_path: Path) -> None:
        root = _plan_tree(tmp_path)
        (root / "CLAUDE/Plan/00419-live/PLAN.md").write_text(
            _ACTIVE + "\nSee [docs](https://example.com/a.md).\n"
        )

        assert _findings(root) == []

    def test_a_template_placeholder_is_not_reported(self, tmp_path: Path) -> None:
        root = _plan_tree(tmp_path)
        (root / "CLAUDE/Plan/00419-live/PLAN.md").write_text(
            _ACTIVE + "\nSee [tmpl](../NNNNN-name/PLAN.md).\n"
        )

        assert _findings(root) == []

    def test_a_clean_tree_produces_nothing(self, tmp_path: Path) -> None:
        assert _findings(_plan_tree(tmp_path)) == []
