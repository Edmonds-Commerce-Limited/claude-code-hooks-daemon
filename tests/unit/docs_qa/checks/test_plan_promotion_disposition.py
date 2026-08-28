"""Tests for check ``plan-promotion-disposition`` (Plan 00284, Task 3.1e)."""

import subprocess
from pathlib import Path

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.docs_qa.checks.plan_promotion_disposition import CHECK_ID, CHECKS
from claude_code_hooks_daemon.docs_qa.context import staged_context
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy
from claude_code_hooks_daemon.docs_qa.types import CheckContext, CheckStage, Finding, Severity


def _run_staged(context: CheckContext) -> list[Finding]:
    for spec in CHECKS:
        if spec.stage is CheckStage.STAGED:
            return spec.run(context)
    raise AssertionError("no STAGED check registered")


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")


_PLAN_FOLDER = "CLAUDE/Plan/00001-widget"


class TestRegistration:
    def test_registers_staged_only(self) -> None:
        stages = {spec.stage for spec in CHECKS}
        assert stages == {CheckStage.STAGED}
        assert all(spec.check_id == CHECK_ID for spec in CHECKS)


class TestPromotionDisposition:
    def test_terminal_flip_with_undispositioned_supporting_doc_advises(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "repo"
        folder = root / _PLAN_FOLDER
        folder.mkdir(parents=True)
        (folder / "RESEARCH.md").write_text("# research notes\n")
        _init_repo(root)
        (folder / "PLAN.md").write_text("# Plan 00001: widget\n\n**Status**: Complete\n")
        (folder / "JOURNAL").mkdir()
        (folder / "JOURNAL" / "00001-Journal-26-01-01.md").write_text(
            "## 2026-01-01\n\nWrapped up the plan.\n"
        )
        _git(root, "add", "-A")

        context = staged_context(project_root=root, policy=DocumentationPolicy())
        findings = _run_staged(context)
        assert len(findings) == 1
        assert findings[0].check_id == CHECK_ID
        assert findings[0].severity is Severity.ADVISE
        assert "RESEARCH.md" in findings[0].message
        assert "promote" in findings[0].remediation.lower()
        assert "historical" in findings[0].remediation.lower()
        assert "delete" in findings[0].remediation.lower()

    def test_terminal_flip_with_dispositioned_journal_entry_is_silent(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        folder = root / _PLAN_FOLDER
        folder.mkdir(parents=True)
        (folder / "RESEARCH.md").write_text("# research notes\n")
        _init_repo(root)
        (folder / "PLAN.md").write_text("# Plan 00001: widget\n\n**Status**: Complete\n")
        (folder / "JOURNAL").mkdir()
        (folder / "JOURNAL" / "00001-Journal-26-01-01.md").write_text(
            "## 2026-01-01\n\nRESEARCH.md: promote into CLAUDE/Foo.md.\n"
        )
        _git(root, "add", "-A")

        context = staged_context(project_root=root, policy=DocumentationPolicy())
        assert _run_staged(context) == []

    def test_no_supporting_docs_is_silent(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        folder = root / _PLAN_FOLDER
        folder.mkdir(parents=True)
        _init_repo(root)
        (folder / "PLAN.md").write_text("# Plan 00001: widget\n\n**Status**: Complete\n")
        _git(root, "add", "-A")

        context = staged_context(project_root=root, policy=DocumentationPolicy())
        assert _run_staged(context) == []

    def test_non_terminal_status_is_silent(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        folder = root / _PLAN_FOLDER
        folder.mkdir(parents=True)
        (folder / "RESEARCH.md").write_text("# research notes\n")
        _init_repo(root)
        (folder / "PLAN.md").write_text("# Plan 00001: widget\n\n**Status**: In Progress\n")
        _git(root, "add", "-A")

        context = staged_context(project_root=root, policy=DocumentationPolicy())
        assert _run_staged(context) == []

    def test_journal_files_are_never_supporting_docs(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        folder = root / _PLAN_FOLDER
        folder.mkdir(parents=True)
        (folder / "JOURNAL").mkdir()
        (folder / "JOURNAL" / "00001-Journal-26-01-01.md").write_text("## entry\n")
        _init_repo(root)
        (folder / "PLAN.md").write_text("# Plan 00001: widget\n\n**Status**: Complete\n")
        _git(root, "add", "-A")

        context = staged_context(project_root=root, policy=DocumentationPolicy())
        assert _run_staged(context) == []

    def test_no_staged_documents_produces_no_findings(self, tmp_path: Path) -> None:
        context = CheckContext(project_root=tmp_path, policy=DocumentationPolicy())
        assert _run_staged(context) == []

    def test_folder_missing_on_disk_is_silent(self, tmp_path: Path) -> None:
        """A PLAN.md whose staged path names a folder absent from disk."""
        from unittest.mock import patch

        root = tmp_path / "repo"
        folder = root / _PLAN_FOLDER
        folder.mkdir(parents=True)
        _init_repo(root)
        (folder / "PLAN.md").write_text("# Plan 00001: widget\n\n**Status**: Complete\n")
        _git(root, "add", "-A")

        context = staged_context(project_root=root, policy=DocumentationPolicy())
        with patch.object(Path, "is_dir", return_value=False):
            assert _run_staged(context) == []

    def test_non_plan_md_staged_file_is_ignored(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        (root / "CLAUDE").mkdir()
        (root / "CLAUDE" / "Notes.md").write_text("**Status**: Complete\n")
        _git(root, "add", "-A")

        context = staged_context(project_root=root, policy=DocumentationPolicy())
        assert _run_staged(context) == []
