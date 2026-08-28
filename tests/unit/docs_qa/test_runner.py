"""Tests for ``docs_qa.runner`` (Plan 00284, Task 3.1a)."""

from pathlib import Path

from claude_code_hooks_daemon.docs_qa.context import edit_context
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy
from claude_code_hooks_daemon.docs_qa.runner import run_stage
from claude_code_hooks_daemon.docs_qa.types import CheckSpec, CheckStage, Finding, Severity


def _fake_spec(check_id: str, stage: CheckStage, finding: Finding | None) -> CheckSpec:
    def _run(context: object) -> list[Finding]:
        return [] if finding is None else [finding]

    return CheckSpec(check_id=check_id, stage=stage, run=_run)


class TestRunStage:
    def test_runs_only_checks_registered_for_the_stage(self, tmp_path: Path) -> None:
        edit_finding = Finding(check_id="a", severity=Severity.BLOCK, message="m", remediation="r")
        sweep_finding = Finding(
            check_id="b", severity=Severity.ADVISE, message="m", remediation="r"
        )
        registry = (
            _fake_spec("a", CheckStage.EDIT, edit_finding),
            _fake_spec("b", CheckStage.SWEEP, sweep_finding),
        )
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "X.md",
            file_content="x",
            file_exists_before=False,
        )
        findings = run_stage(CheckStage.EDIT, context, registry=registry)
        assert findings == [edit_finding]

    def test_accumulates_findings_from_multiple_checks_at_the_same_stage(
        self, tmp_path: Path
    ) -> None:
        finding_a = Finding(check_id="a", severity=Severity.BLOCK, message="m", remediation="r")
        finding_b = Finding(check_id="b", severity=Severity.ADVISE, message="m", remediation="r")
        registry = (
            _fake_spec("a", CheckStage.EDIT, finding_a),
            _fake_spec("b", CheckStage.EDIT, finding_b),
        )
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "X.md",
            file_content="x",
            file_exists_before=False,
        )
        findings = run_stage(CheckStage.EDIT, context, registry=registry)
        assert findings == [finding_a, finding_b]

    def test_no_registry_defaults_to_full_catalogue(self, tmp_path: Path) -> None:
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "X.md",
            file_content="no links here",
            file_exists_before=False,
        )
        assert run_stage(CheckStage.EDIT, context) == []
