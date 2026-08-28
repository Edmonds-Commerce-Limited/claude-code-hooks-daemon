"""Tests for check ``quote-source-stale`` (Plan 00284, Task 3.1d)."""

from pathlib import Path

from claude_code_hooks_daemon.docs_qa.checks.quote_source_stale import CHECK_ID, CHECKS
from claude_code_hooks_daemon.docs_qa.context import edit_context
from claude_code_hooks_daemon.docs_qa.corpus import build_and_save_corpus
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy
from claude_code_hooks_daemon.docs_qa.types import CheckContext, CheckStage, Finding, Severity

_LONG_SENTENCE = (
    "This is a real sentence that is long enough to clear the minimum "
    "quote length floor for verification purposes."
)


def _run_edit(context: CheckContext) -> list[Finding]:
    for spec in CHECKS:
        if spec.stage is CheckStage.EDIT:
            return spec.run(context)
    raise AssertionError("no EDIT check registered")


class TestRegistration:
    def test_registers_edit_only(self) -> None:
        stages = {spec.stage for spec in CHECKS}
        assert stages == {CheckStage.EDIT}
        assert all(spec.check_id == CHECK_ID for spec in CHECKS)


class TestEditOnSourceFile:
    def _build_corpus_with_quoter(self, tmp_path: Path, policy: DocumentationPolicy):
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "CLAUDE" / "Source.md").write_text(f"## Anchor\n\n{_LONG_SENTENCE}\n")
        (tmp_path / "CLAUDE" / "Quoter.md").write_text(
            f"<!-- ssot-quote: CLAUDE/Source.md#anchor -->\n{_LONG_SENTENCE}\n"
            "<!-- /ssot-quote -->\n"
        )
        index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
        return build_and_save_corpus(tmp_path, policy, index_path)

    def test_changed_anchor_with_known_quoter_advises(self, tmp_path: Path) -> None:
        policy = DocumentationPolicy()
        corpus = self._build_corpus_with_quoter(tmp_path, policy)
        source = tmp_path / "CLAUDE" / "Source.md"
        old_content = source.read_text()
        new_content = "## Anchor\n\nThe section content has now genuinely changed entirely.\n"
        context = edit_context(
            project_root=tmp_path,
            policy=policy,
            file_path=source,
            file_content=new_content,
            file_exists_before=True,
            file_content_before=old_content,
            corpus=corpus,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert findings[0].check_id == CHECK_ID
        assert findings[0].severity is Severity.ADVISE
        assert "CLAUDE/Quoter.md" in findings[0].message

    def test_unchanged_anchor_produces_no_finding(self, tmp_path: Path) -> None:
        policy = DocumentationPolicy()
        corpus = self._build_corpus_with_quoter(tmp_path, policy)
        source = tmp_path / "CLAUDE" / "Source.md"
        content = source.read_text()
        context = edit_context(
            project_root=tmp_path,
            policy=policy,
            file_path=source,
            file_content=content,
            file_exists_before=True,
            file_content_before=content,
            corpus=corpus,
        )
        assert _run_edit(context) == []

    def test_changed_anchor_with_no_known_quoters_is_silent(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        source = tmp_path / "CLAUDE" / "Source.md"
        source.write_text(f"## Anchor\n\n{_LONG_SENTENCE}\n")
        policy = DocumentationPolicy()
        index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
        corpus = build_and_save_corpus(tmp_path, policy, index_path)
        context = edit_context(
            project_root=tmp_path,
            policy=policy,
            file_path=source,
            file_content="## Anchor\n\nCompletely different text now, unrelated to before.\n",
            file_exists_before=True,
            file_content_before=f"## Anchor\n\n{_LONG_SENTENCE}\n",
            corpus=corpus,
        )
        assert _run_edit(context) == []

    def test_new_file_creation_produces_no_finding(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        policy = DocumentationPolicy()
        index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
        corpus = build_and_save_corpus(tmp_path, policy, index_path)
        context = edit_context(
            project_root=tmp_path,
            policy=policy,
            file_path=tmp_path / "CLAUDE" / "New.md",
            file_content="## Anchor\n\nBrand new content.\n",
            file_exists_before=False,
            corpus=corpus,
        )
        assert _run_edit(context) == []

    def test_no_corpus_is_cold_safe_and_produces_no_findings(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        source = tmp_path / "CLAUDE" / "Source.md"
        source.write_text(f"## Anchor\n\n{_LONG_SENTENCE}\n")
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=source,
            file_content="## Anchor\n\nCompletely different text now, unrelated to before.\n",
            file_exists_before=True,
            file_content_before=f"## Anchor\n\n{_LONG_SENTENCE}\n",
        )
        assert context.corpus is None
        assert _run_edit(context) == []

    def test_missing_file_path_or_content_produces_no_findings(self, tmp_path: Path) -> None:
        context_no_path = CheckContext(
            project_root=tmp_path, policy=DocumentationPolicy(), file_content="x"
        )
        context_no_content = CheckContext(
            project_root=tmp_path, policy=DocumentationPolicy(), file_path=tmp_path / "X.md"
        )
        assert _run_edit(context_no_path) == []
        assert _run_edit(context_no_content) == []

    def test_multiple_known_quoters_are_all_named(self, tmp_path: Path) -> None:
        policy = DocumentationPolicy()
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "CLAUDE" / "Source.md").write_text(f"## Anchor\n\n{_LONG_SENTENCE}\n")
        for name in ("QuoterA.md", "QuoterB.md"):
            (tmp_path / "CLAUDE" / name).write_text(
                f"<!-- ssot-quote: CLAUDE/Source.md#anchor -->\n{_LONG_SENTENCE}\n"
                "<!-- /ssot-quote -->\n"
            )
        index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
        corpus = build_and_save_corpus(tmp_path, policy, index_path)
        source = tmp_path / "CLAUDE" / "Source.md"
        old_content = source.read_text()
        new_content = "## Anchor\n\nThe section content has now genuinely changed entirely.\n"
        context = edit_context(
            project_root=tmp_path,
            policy=policy,
            file_path=source,
            file_content=new_content,
            file_exists_before=True,
            file_content_before=old_content,
            corpus=corpus,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert "CLAUDE/QuoterA.md" in findings[0].message
        assert "CLAUDE/QuoterB.md" in findings[0].message

    def test_removed_anchor_with_known_quoter_advises(self, tmp_path: Path) -> None:
        policy = DocumentationPolicy()
        corpus = self._build_corpus_with_quoter(tmp_path, policy)
        source = tmp_path / "CLAUDE" / "Source.md"
        old_content = source.read_text()
        # The anchor's heading is renamed, so "anchor" no longer resolves at all.
        new_content = f"## Renamed\n\n{_LONG_SENTENCE}\n"
        context = edit_context(
            project_root=tmp_path,
            policy=policy,
            file_path=source,
            file_content=new_content,
            file_exists_before=True,
            file_content_before=old_content,
            corpus=corpus,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert "CLAUDE/Quoter.md" in findings[0].message
