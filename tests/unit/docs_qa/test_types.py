"""Tests for ``docs_qa.types`` (Plan 00284, Task 3.1a)."""

from pathlib import Path

from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy
from claude_code_hooks_daemon.docs_qa.types import (
    CheckContext,
    CheckSpec,
    CheckStage,
    Finding,
    Severity,
)


class TestCheckStage:
    def test_has_exactly_three_members(self) -> None:
        assert {member.value for member in CheckStage} == {"edit", "staged", "sweep"}


class TestSeverity:
    def test_has_exactly_two_members(self) -> None:
        assert {member.value for member in Severity} == {"block", "advise"}


class TestFinding:
    def test_is_frozen_and_carries_all_fields(self) -> None:
        finding = Finding(
            check_id="pointer-resolves",
            severity=Severity.BLOCK,
            message="broken link",
            remediation="fix the link",
            path="docs/foo.md",
        )
        assert finding.check_id == "pointer-resolves"
        assert finding.severity is Severity.BLOCK
        assert finding.path == "docs/foo.md"

    def test_path_defaults_to_none(self) -> None:
        finding = Finding(check_id="x", severity=Severity.ADVISE, message="m", remediation="r")
        assert finding.path is None


class TestCheckContext:
    def test_edit_stage_fields_default_to_none(self, tmp_path: Path) -> None:
        context = CheckContext(project_root=tmp_path, policy=DocumentationPolicy())
        assert context.file_path is None
        assert context.file_content is None
        assert context.file_exists_before is None
        assert context.file_content_before is None
        assert context.corpus is None

    def test_carries_project_root_and_policy(self, tmp_path: Path) -> None:
        policy = DocumentationPolicy(enabled=True)
        context = CheckContext(project_root=tmp_path, policy=policy)
        assert context.project_root == tmp_path
        assert context.policy is policy


class TestCheckSpec:
    def test_holds_id_stage_and_run_fn(self) -> None:
        def _run(context: CheckContext) -> list[Finding]:
            return []

        spec = CheckSpec(check_id="pointer-resolves", stage=CheckStage.EDIT, run=_run)
        assert spec.check_id == "pointer-resolves"
        assert spec.stage is CheckStage.EDIT
        assert spec.run is _run
