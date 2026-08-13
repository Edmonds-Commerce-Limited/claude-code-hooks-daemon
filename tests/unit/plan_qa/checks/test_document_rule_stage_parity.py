"""Document-level plan rules must also run over what is already on disk.

Plan 00230. Every single-document check shipped registered at ``Stage.EDIT``
only, and every ``Stage.SWEEP`` check was tree-level (bijection, recount,
collisions). So no check ever read a ``PLAN.md`` that was already on disk, and
CLAUDE.md Standard 15's corollary applied in full: everything predating a
write-time rule was permanently unexamined. Two plans in this repo's own tree
sat on BLOCK-level ``status-enum-and-date`` violations while the sweep reported
the tree clean.

The trap this module also pins: re-registering an EDIT check at SWEEP does
*not* fix it. A sweep context carries no file payload, so ``edit_target()``
returns ``None`` and the check no-matches every folder — registered, never
firing, and indistinguishable from passing. A batch rule must iterate the tree.
"""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pytest

from claude_code_hooks_daemon.plan_qa.checks import common
from claude_code_hooks_daemon.plan_qa.context import sweep_context
from claude_code_hooks_daemon.plan_qa.runner import run_stage
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Stage

_TODAY = date(2026, 8, 13)
_VALID_PLAN = "# Plan 00001: first\n\n**Status**: In Progress\n\n- [ ] ⬜ **Task 1.1**: x\n"


@dataclass(frozen=True)
class _Journal:
    """Duck-typed stand-in for PlanWorkflowQaJournalConfig, switched off.

    The journal rules are a separate concern with their own grandfathering;
    leaving them on would mix their findings into every assertion here.
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


def _tree(tmp_path: Path, plan_body: str) -> Path:
    """A plan tree whose single plan carries ``plan_body`` as its PLAN.md."""
    root = tmp_path / "repo"
    plan_dir = root / "CLAUDE" / "Plan"
    (plan_dir / "Completed").mkdir(parents=True)
    (plan_dir / "Cancelled").mkdir()
    folder = plan_dir / "00001-first"
    folder.mkdir()
    (folder / "PLAN.md").write_text(plan_body)
    (plan_dir / "README.md").write_text(
        "# Plans Index\n\n## Active Plans\n\n- [00001: first](00001-first/PLAN.md) - In Progress\n"
    )
    return root


def _sweep_findings(root: Path) -> list[str]:
    context = sweep_context(root, "CLAUDE/Plan", _Policy(), today=_TODAY)
    return [finding.check_id for finding in run_stage(Stage.SWEEP, context)]


class TestTheSweepReadsWhatIsAlreadyOnDisk:
    """The live failure this plan was filed for."""

    def test_unparseable_status_on_disk_is_reported(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, "# Plan 00001: first\n\n**Status**: Shipped v3.23.0 (done)\n")
        assert "status-enum-and-date" in _sweep_findings(root)

    def test_missing_status_line_on_disk_is_reported(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, "# Plan 00001: first\n\n## Progress\n\n- [x] did things\n")
        assert "status-line-present" in _sweep_findings(root)

    def test_header_contradicting_an_all_done_body_on_disk_is_reported(
        self, tmp_path: Path
    ) -> None:
        root = _tree(
            tmp_path,
            "# Plan 00001: first\n\n**Status**: In Progress\n\n"
            "- [x] ✅ **Task 1.1**: x\n- [x] ✅ **Task 1.2**: y\n",
        )
        assert "header-body-coherence" in _sweep_findings(root)

    def test_a_clean_tree_stays_clean(self, tmp_path: Path) -> None:
        """The guard must not fire on well-formed plans, or it is worthless."""
        root = _tree(tmp_path, _VALID_PLAN)
        assert _sweep_findings(root) == []


class TestNaiveReRegistrationWouldBeASilentNoOp:
    """Why the batch adapter exists at all.

    If this ever starts returning a target, the adapter is no longer needed —
    but until then, an EDIT check re-registered at SWEEP fires on nothing.
    """

    def test_edit_target_is_none_for_a_sweep_context(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, _VALID_PLAN)
        context = sweep_context(root, "CLAUDE/Plan", _Policy(), today=_TODAY)

        assert common.edit_target(context) is None

    def test_tree_targets_is_empty_for_an_edit_context(self) -> None:
        """The mirror image: the batch resolver no-matches a per-edit context."""
        context = CheckContext(
            project_root=Path("/repo"),
            plan_dir_rel="CLAUDE/Plan",
            file_path=Path("/repo/CLAUDE/Plan/00001-first/PLAN.md"),
            file_content=_VALID_PLAN,
        )

        assert common.tree_targets(context) == []


class TestTreeTargets:
    def test_resolves_every_plan_document_in_the_tree(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, _VALID_PLAN)
        archived = root / "CLAUDE/Plan/Completed/00002-second"
        archived.mkdir(parents=True)
        (archived / "PLAN.md").write_text("# Plan 00002: second\n\n**Status**: Complete\n")
        context = sweep_context(root, "CLAUDE/Plan", _Policy(), today=_TODAY)

        targets = {target.plan_number: target for target in common.tree_targets(context)}

        assert set(targets) == {1, 2}
        assert targets[1].rel_path == "CLAUDE/Plan/00001-first/PLAN.md"
        assert targets[1].in_archive is False
        assert targets[2].rel_path == "CLAUDE/Plan/Completed/00002-second/PLAN.md"
        assert targets[2].in_archive is True

    def test_skips_a_folder_with_no_plan_md(self, tmp_path: Path) -> None:
        """A missing PLAN.md is location-status-coherence's finding, not a crash here."""
        root = _tree(tmp_path, _VALID_PLAN)
        (root / "CLAUDE/Plan/00003-empty").mkdir()
        context = sweep_context(root, "CLAUDE/Plan", _Policy(), today=_TODAY)

        assert [target.plan_number for target in common.tree_targets(context)] == [1]


class TestEveryDocumentRuleIsClassified:
    """The actual deliverable: the classification must be TOTAL.

    Adding SWEEP twins fixes today's checks. This guard is what stops check 13
    from being added blind and silently reopening the gap.
    """

    def test_every_edit_check_is_batched_or_recorded_as_write_act_only(self) -> None:
        unclassified = sorted(
            module
            for module in common.document_rule_modules()
            if module not in common.WRITE_ACT_ONLY_RULES
            and module not in common.batched_document_rule_modules()
        )

        assert unclassified == [], (
            "These checks read a single plan document but neither run at SWEEP nor "
            "carry a recorded write-act-only exemption, so anything already on disk "
            "is unexamined. Register them via document_rule_checks(), or add them to "
            "WRITE_ACT_ONLY_RULES with the reason they are about the act of writing."
        )

    def test_every_exemption_records_a_reason(self) -> None:
        assert all(reason.strip() for reason in common.WRITE_ACT_ONLY_RULES.values())

    @pytest.mark.parametrize("module", sorted(common.WRITE_ACT_ONLY_RULES))
    def test_every_exemption_names_a_real_check_module(self, module: str) -> None:
        """An exemption for a check that no longer exists would silently widen."""
        assert module in common.document_rule_modules()
