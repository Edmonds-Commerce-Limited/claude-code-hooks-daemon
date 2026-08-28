"""Tests for check ``at-import-census`` (Plan 00284, Task 3.1e)."""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.docs_qa.checks.at_import_census import CHECK_ID, CHECKS
from claude_code_hooks_daemon.docs_qa.context import edit_context, sweep_context
from claude_code_hooks_daemon.docs_qa.corpus import build_and_save_corpus
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy, DocumentationQaPolicy
from claude_code_hooks_daemon.docs_qa.types import CheckContext, CheckStage, Finding, Severity


def _run_edit(context: CheckContext) -> list[Finding]:
    for spec in CHECKS:
        if spec.stage is CheckStage.EDIT:
            return spec.run(context)
    raise AssertionError("no EDIT check registered")


def _run_sweep(context: CheckContext) -> list[Finding]:
    for spec in CHECKS:
        if spec.stage is CheckStage.SWEEP:
            return spec.run(context)
    raise AssertionError("no SWEEP check registered")


class TestRegistration:
    def test_registers_edit_and_sweep(self) -> None:
        stages = {spec.stage for spec in CHECKS}
        assert stages == {CheckStage.EDIT, CheckStage.SWEEP}
        assert all(spec.check_id == CHECK_ID for spec in CHECKS)


class TestEditStage:
    def test_new_non_resident_import_is_block(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "New.md",
            file_content="See @CLAUDE/Other.md for details.\n",
            file_exists_before=False,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert findings[0].check_id == CHECK_ID
        assert findings[0].severity is Severity.BLOCK
        assert "CLAUDE/Other.md" in findings[0].message

    def test_resident_import_produces_no_finding(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "New.md",
            file_content="See @CLAUDE.md for details.\n",
            file_exists_before=False,
        )
        assert _run_edit(context) == []

    def test_backtick_quoted_import_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "New.md",
            file_content="Do not use `@CLAUDE/Other.md` style imports.\n",
            file_exists_before=False,
        )
        assert _run_edit(context) == []

    def test_import_inside_fence_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "New.md",
            file_content="```\n@CLAUDE/Other.md\n```\n",
            file_exists_before=False,
        )
        assert _run_edit(context) == []

    def test_pre_existing_import_is_advise(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "Existing.md",
            file_content="Intro. See @CLAUDE/Other.md.\n",
            file_exists_before=True,
            file_content_before="See @CLAUDE/Other.md.\n",
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE

    def test_custom_resident_allowlist_pattern(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        policy = DocumentationPolicy(
            qa=DocumentationQaPolicy(resident_at_imports=("CLAUDE.md", "CLAUDE/Allowed.md"))
        )
        context = edit_context(
            project_root=tmp_path,
            policy=policy,
            file_path=tmp_path / "CLAUDE" / "New.md",
            file_content="See @CLAUDE/Allowed.md.\n",
            file_exists_before=False,
        )
        assert _run_edit(context) == []

    def test_new_non_resident_import_in_grandfathered_file_is_advise(self, tmp_path: Path) -> None:
        """F2 (Plan 00287): grandfather_allowlist must downgrade a NEW
        non-resident import to ADVISE, mirroring pointer-resolves and
        rules-file-shape -- R12's "held to advise-only forever" promise."""
        (tmp_path / "CLAUDE").mkdir()
        policy = DocumentationPolicy(
            qa=DocumentationQaPolicy(grandfather_allowlist=("CLAUDE/New.md",))
        )
        context = edit_context(
            project_root=tmp_path,
            policy=policy,
            file_path=tmp_path / "CLAUDE" / "New.md",
            file_content="See @CLAUDE/Other.md for details.\n",
            file_exists_before=False,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE

    def test_missing_file_path_or_content_produces_no_findings(self, tmp_path: Path) -> None:
        context_no_path = CheckContext(
            project_root=tmp_path, policy=DocumentationPolicy(), file_content="x"
        )
        context_no_content = CheckContext(
            project_root=tmp_path, policy=DocumentationPolicy(), file_path=tmp_path / "X.md"
        )
        assert _run_edit(context_no_path) == []
        assert _run_edit(context_no_content) == []

    def test_no_at_import_produces_no_finding(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "New.md",
            file_content="Nothing here, just an email a@b.com mention.\n",
            file_exists_before=False,
        )
        assert _run_edit(context) == []


class TestSweepStage:
    def test_reports_non_resident_import_as_advise(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "CLAUDE" / "Foo.md").write_text("See @CLAUDE/Other.md.\n")
        index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
        corpus = build_and_save_corpus(tmp_path, DocumentationPolicy(), index_path)

        context = sweep_context(project_root=tmp_path, policy=DocumentationPolicy(), corpus=corpus)
        findings = _run_sweep(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE
        assert findings[0].path == "CLAUDE/Foo.md"

    def test_no_corpus_produces_no_findings(self, tmp_path: Path) -> None:
        context = CheckContext(project_root=tmp_path, policy=DocumentationPolicy())
        assert _run_sweep(context) == []

    def test_resident_import_in_sweep_produces_no_finding(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "CLAUDE" / "Foo.md").write_text("See @CLAUDE.md.\n")
        index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
        corpus = build_and_save_corpus(tmp_path, DocumentationPolicy(), index_path)

        context = sweep_context(project_root=tmp_path, policy=DocumentationPolicy(), corpus=corpus)
        assert _run_sweep(context) == []

    def test_document_removed_from_disk_after_indexing_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        target = tmp_path / "CLAUDE" / "Foo.md"
        target.write_text("See @CLAUDE/Other.md.\n")
        index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
        corpus = build_and_save_corpus(tmp_path, DocumentationPolicy(), index_path)
        target.unlink()

        context = sweep_context(project_root=tmp_path, policy=DocumentationPolicy(), corpus=corpus)
        assert _run_sweep(context) == []

    def test_clean_corpus_produces_no_findings(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "CLAUDE" / "Foo.md").write_text("nothing here\n")
        index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
        corpus = build_and_save_corpus(tmp_path, DocumentationPolicy(), index_path)

        context = sweep_context(project_root=tmp_path, policy=DocumentationPolicy(), corpus=corpus)
        assert _run_sweep(context) == []

    def test_unreadable_file_is_skipped_not_fatal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """N5 (Plan 00287): an unreadable file must not abort the whole
        SessionStart sweep."""
        (tmp_path / "CLAUDE").mkdir()
        target = tmp_path / "CLAUDE" / "Foo.md"
        target.write_text("See @CLAUDE/Other.md.\n")
        index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
        corpus = build_and_save_corpus(tmp_path, DocumentationPolicy(), index_path)

        original_read_text = Path.read_text

        def _raising_read_text(
            self: Path, encoding: str | None = None, errors: str | None = None
        ) -> str:
            if self == target:
                raise OSError("permission denied")
            return original_read_text(self, encoding=encoding, errors=errors)

        monkeypatch.setattr(Path, "read_text", _raising_read_text)
        context = sweep_context(project_root=tmp_path, policy=DocumentationPolicy(), corpus=corpus)
        assert _run_sweep(context) == []
