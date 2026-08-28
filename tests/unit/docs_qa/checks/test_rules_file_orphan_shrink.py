"""Tests for check ``rules-file-orphan-shrink`` (Plan 00284, Task 3.1e)."""

import subprocess
from pathlib import Path

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.docs_qa.checks.rules_file_orphan_shrink import CHECK_ID, CHECKS
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


class TestRegistration:
    def test_registers_staged_only(self) -> None:
        stages = {spec.stage for spec in CHECKS}
        assert stages == {CheckStage.STAGED}
        assert all(spec.check_id == CHECK_ID for spec in CHECKS)


class TestOrphanShrink:
    def test_shrink_with_no_canonical_growth_advises(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        (root / ".claude" / "rules").mkdir(parents=True)
        rules_file = root / ".claude" / "rules" / "one.md"
        rules_file.write_text("---\npaths: ['*']\n---\n" + ("word " * 100) + "\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "initial")
        rules_file.write_text("---\npaths: ['*']\n---\nshort\n")
        _git(root, "add", "-A")

        context = staged_context(project_root=root, policy=DocumentationPolicy())
        findings = _run_staged(context)
        assert len(findings) == 1
        assert findings[0].check_id == CHECK_ID
        assert findings[0].severity is Severity.ADVISE
        assert findings[0].path == ".claude/rules/one.md"

    def test_shrink_with_same_commit_canonical_growth_is_silent(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        (root / ".claude" / "rules").mkdir(parents=True)
        (root / "CLAUDE").mkdir()
        rules_file = root / ".claude" / "rules" / "one.md"
        rules_file.write_text("---\npaths: ['*']\n---\n" + ("word " * 100) + "\n")
        canonical = root / "CLAUDE" / "Canonical.md"
        canonical.write_text("short\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "initial")
        rules_file.write_text("---\npaths: ['*']\n---\nshort\n")
        canonical.write_text("short\n" + ("promoted content " * 50) + "\n")
        _git(root, "add", "-A")

        context = staged_context(project_root=root, policy=DocumentationPolicy())
        assert _run_staged(context) == []

    def test_growing_rules_file_produces_no_finding(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        (root / ".claude" / "rules").mkdir(parents=True)
        rules_file = root / ".claude" / "rules" / "one.md"
        rules_file.write_text("---\npaths: ['*']\n---\nshort\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "initial")
        rules_file.write_text("---\npaths: ['*']\n---\n" + ("word " * 100) + "\n")
        _git(root, "add", "-A")

        context = staged_context(project_root=root, policy=DocumentationPolicy())
        assert _run_staged(context) == []

    def test_new_rules_file_is_not_a_shrink(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        (root / ".claude" / "rules").mkdir(parents=True)
        (root / ".claude" / "rules" / "one.md").write_text("---\npaths: ['*']\n---\nnew\n")
        _git(root, "add", "-A")

        context = staged_context(project_root=root, policy=DocumentationPolicy())
        assert _run_staged(context) == []

    def test_non_rules_file_shrink_is_ignored(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        (root / "CLAUDE").mkdir()
        doc = root / "CLAUDE" / "Doc.md"
        doc.write_text(("word " * 100) + "\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "initial")
        doc.write_text("short\n")
        _git(root, "add", "-A")

        context = staged_context(project_root=root, policy=DocumentationPolicy())
        assert _run_staged(context) == []

    def test_no_staged_documents_produces_no_findings(self, tmp_path: Path) -> None:
        context = CheckContext(project_root=tmp_path, policy=DocumentationPolicy())
        assert _run_staged(context) == []

    def test_growth_check_scans_past_a_non_growing_canonical_file_too(self, tmp_path: Path) -> None:
        """Exercises the loop continuing past a canonical file that did NOT grow."""
        root = tmp_path / "repo"
        _init_repo(root)
        (root / ".claude" / "rules").mkdir(parents=True)
        (root / "CLAUDE").mkdir()
        rules_file = root / ".claude" / "rules" / "one.md"
        rules_file.write_text("---\npaths: ['*']\n---\n" + ("word " * 100) + "\n")
        unchanged = root / "CLAUDE" / "Unchanged.md"
        unchanged.write_text("original longer content here\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "initial")
        rules_file.write_text("---\npaths: ['*']\n---\nshort\n")
        unchanged.write_text("shorter\n")  # staged, but shrank -- not growth
        _git(root, "add", "-A")

        context = staged_context(project_root=root, policy=DocumentationPolicy())
        findings = _run_staged(context)
        assert len(findings) == 1
