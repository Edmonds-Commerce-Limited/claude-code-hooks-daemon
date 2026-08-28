"""Tests for check ``quote-drift`` (Plan 00284, Task 3.1d)."""

from pathlib import Path

from claude_code_hooks_daemon.docs_qa.checks.quote_drift import CHECK_ID, CHECKS
from claude_code_hooks_daemon.docs_qa.context import edit_context, sweep_context
from claude_code_hooks_daemon.docs_qa.corpus import DocCorpus, build_and_save_corpus
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy, DocumentationQaPolicy
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


def _run_sweep(context: CheckContext) -> list[Finding]:
    for spec in CHECKS:
        if spec.stage is CheckStage.SWEEP:
            return spec.run(context)
    raise AssertionError("no SWEEP check registered")


def _quote_block(source: str, anchor: str, body: str) -> str:
    return f"<!-- ssot-quote: {source}#{anchor} -->\n{body}\n<!-- /ssot-quote -->\n"


class TestRegistration:
    def test_registers_edit_and_sweep(self) -> None:
        stages = {spec.stage for spec in CHECKS}
        assert stages == {CheckStage.EDIT, CheckStage.SWEEP}
        assert all(spec.check_id == CHECK_ID for spec in CHECKS)


class TestEditStageCleanAndDrifted:
    def test_verified_quote_produces_no_finding(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        source = tmp_path / "CLAUDE" / "Source.md"
        source.write_text(f"## Anchor\n\n{_LONG_SENTENCE}\n")
        quoter = tmp_path / "CLAUDE" / "Quoter.md"
        content = _quote_block("CLAUDE/Source.md", "anchor", _LONG_SENTENCE)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=quoter,
            file_content=content,
            file_exists_before=False,
        )
        assert _run_edit(context) == []

    def test_drifted_quote_is_block(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        source = tmp_path / "CLAUDE" / "Source.md"
        source.write_text("## Anchor\n\nThe source text has genuinely changed since.\n")
        quoter = tmp_path / "CLAUDE" / "Quoter.md"
        content = _quote_block("CLAUDE/Source.md", "anchor", _LONG_SENTENCE)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=quoter,
            file_content=content,
            file_exists_before=False,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert findings[0].check_id == CHECK_ID
        assert findings[0].severity is Severity.BLOCK
        assert "drift" in findings[0].message.lower()

    def test_missing_source_file_is_block_with_distinct_message(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        quoter = tmp_path / "CLAUDE" / "Quoter.md"
        content = _quote_block("CLAUDE/Nope.md", "anchor", _LONG_SENTENCE)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=quoter,
            file_content=content,
            file_exists_before=False,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert "source file" in findings[0].message.lower()
        assert "missing" in findings[0].message.lower()

    def test_missing_anchor_is_block_with_distinct_message(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        source = tmp_path / "CLAUDE" / "Source.md"
        source.write_text("## Something Else\n\nBody.\n")
        quoter = tmp_path / "CLAUDE" / "Quoter.md"
        content = _quote_block("CLAUDE/Source.md", "anchor", _LONG_SENTENCE)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=quoter,
            file_content=content,
            file_exists_before=False,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert "anchor" in findings[0].message.lower()
        assert (
            "not found" in findings[0].message.lower() or "missing" in findings[0].message.lower()
        )

    def test_too_short_quote_is_block(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        source = tmp_path / "CLAUDE" / "Source.md"
        source.write_text("## Anchor\n\nshort\n")
        quoter = tmp_path / "CLAUDE" / "Quoter.md"
        content = _quote_block("CLAUDE/Source.md", "anchor", "short")
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=quoter,
            file_content=content,
            file_exists_before=False,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert "too short" in findings[0].message.lower()

    def test_grandfathered_quoting_file_is_advise(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        quoter = tmp_path / "CLAUDE" / "Quoter.md"
        content = _quote_block("CLAUDE/Nope.md", "anchor", _LONG_SENTENCE)
        policy = DocumentationPolicy(
            qa=DocumentationQaPolicy(grandfather_allowlist=("CLAUDE/*.md",))
        )
        context = edit_context(
            project_root=tmp_path,
            policy=policy,
            file_path=quoter,
            file_content=content,
            file_exists_before=False,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE

    def test_no_quote_blocks_produces_no_findings(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "X.md",
            file_content="just prose\n",
            file_exists_before=False,
        )
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

    def test_edit_stage_verifies_without_a_corpus(self, tmp_path: Path) -> None:
        """The primary EDIT path reads the source file directly -- no corpus needed."""
        (tmp_path / "CLAUDE").mkdir()
        source = tmp_path / "CLAUDE" / "Source.md"
        source.write_text(f"## Anchor\n\n{_LONG_SENTENCE}\n")
        quoter = tmp_path / "CLAUDE" / "Quoter.md"
        content = _quote_block("CLAUDE/Source.md", "anchor", _LONG_SENTENCE)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=quoter,
            file_content=content,
            file_exists_before=False,
        )
        assert context.corpus is None
        assert _run_edit(context) == []


def _build_corpus(tmp_path: Path, policy: DocumentationPolicy) -> DocCorpus:
    index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
    return build_and_save_corpus(tmp_path, policy, index_path)


class TestSweepStage:
    def test_drifted_quote_is_advise(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        source = tmp_path / "CLAUDE" / "Source.md"
        source.write_text("## Anchor\n\nCompletely different content now, unrelated.\n")
        quoter = tmp_path / "CLAUDE" / "Quoter.md"
        quoter.write_text(_quote_block("CLAUDE/Source.md", "anchor", _LONG_SENTENCE))
        policy = DocumentationPolicy()
        corpus = _build_corpus(tmp_path, policy)
        context = sweep_context(project_root=tmp_path, policy=policy, corpus=corpus)
        findings = _run_sweep(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE
        assert findings[0].path == "CLAUDE/Quoter.md"

    def test_clean_quote_produces_no_finding(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        source = tmp_path / "CLAUDE" / "Source.md"
        source.write_text(f"## Anchor\n\n{_LONG_SENTENCE}\n")
        quoter = tmp_path / "CLAUDE" / "Quoter.md"
        quoter.write_text(_quote_block("CLAUDE/Source.md", "anchor", _LONG_SENTENCE))
        policy = DocumentationPolicy()
        corpus = _build_corpus(tmp_path, policy)
        context = sweep_context(project_root=tmp_path, policy=policy, corpus=corpus)
        assert _run_sweep(context) == []

    def test_no_corpus_produces_no_findings(self, tmp_path: Path) -> None:
        context = CheckContext(project_root=tmp_path, policy=DocumentationPolicy())
        assert _run_sweep(context) == []

    def test_document_removed_from_disk_after_indexing_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        source = tmp_path / "CLAUDE" / "Source.md"
        source.write_text(f"## Anchor\n\n{_LONG_SENTENCE}\n")
        quoter = tmp_path / "CLAUDE" / "Quoter.md"
        quoter.write_text(_quote_block("CLAUDE/Source.md", "anchor", _LONG_SENTENCE))
        policy = DocumentationPolicy()
        corpus = _build_corpus(tmp_path, policy)
        quoter.unlink()  # indexed, but gone by the time the sweep re-reads it
        context = sweep_context(project_root=tmp_path, policy=policy, corpus=corpus)
        assert _run_sweep(context) == []

    def test_document_with_no_quotes_is_skipped_cheaply(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "CLAUDE" / "Plain.md").write_text("# Plain\n\njust prose\n")
        policy = DocumentationPolicy()
        corpus = _build_corpus(tmp_path, policy)
        context = sweep_context(project_root=tmp_path, policy=policy, corpus=corpus)
        assert _run_sweep(context) == []
