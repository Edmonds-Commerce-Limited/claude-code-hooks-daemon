"""Tests for check ``quote-drift`` (Plan 00284, Tasks 3.1d + 3.1e)."""

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.docs_qa.checks.quote_drift import CHECK_ID, CHECKS
from claude_code_hooks_daemon.docs_qa.context import edit_context, staged_context, sweep_context
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


def _run_staged(context: CheckContext) -> list[Finding]:
    for spec in CHECKS:
        if spec.stage is CheckStage.STAGED:
            return spec.run(context)
    raise AssertionError("no STAGED check registered")


def _quote_block(source: str, anchor: str, body: str) -> str:
    return f"<!-- ssot-quote: {source}#{anchor} -->\n{body}\n<!-- /ssot-quote -->\n"


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
    def test_registers_edit_staged_and_sweep(self) -> None:
        stages = {spec.stage for spec in CHECKS}
        assert stages == {CheckStage.EDIT, CheckStage.STAGED, CheckStage.SWEEP}
        assert all(spec.check_id == CHECK_ID for spec in CHECKS)


class TestStagedStage:
    def test_drifted_staged_quote_is_block(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        (root / "CLAUDE").mkdir()
        (root / "CLAUDE" / "Source.md").write_text(f"## Anchor\n\n{_LONG_SENTENCE}\n")
        (root / "CLAUDE" / "Quoter.md").write_text(
            _quote_block(
                "CLAUDE/Source.md",
                "anchor",
                "This text has drifted entirely from the source and no longer matches.",
            )
        )
        _git(root, "add", "-A")

        context = staged_context(project_root=root, policy=DocumentationPolicy())
        findings = _run_staged(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.BLOCK
        assert findings[0].path == "CLAUDE/Quoter.md"

    def test_clean_staged_quote_produces_no_finding(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        (root / "CLAUDE").mkdir()
        (root / "CLAUDE" / "Source.md").write_text(f"## Anchor\n\n{_LONG_SENTENCE}\n")
        (root / "CLAUDE" / "Quoter.md").write_text(
            _quote_block("CLAUDE/Source.md", "anchor", _LONG_SENTENCE)
        )
        _git(root, "add", "-A")

        context = staged_context(project_root=root, policy=DocumentationPolicy())
        assert _run_staged(context) == []

    def test_grandfathered_staged_quote_is_advise(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        (root / "CLAUDE").mkdir()
        (root / "CLAUDE" / "Quoter.md").write_text(
            _quote_block("CLAUDE/Nope.md", "anchor", _LONG_SENTENCE)
        )
        _git(root, "add", "-A")
        policy = DocumentationPolicy(
            qa=DocumentationQaPolicy(grandfather_allowlist=("CLAUDE/*.md",))
        )

        context = staged_context(project_root=root, policy=policy)
        findings = _run_staged(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE

    def test_no_staged_documents_produces_no_findings(self, tmp_path: Path) -> None:
        context = CheckContext(project_root=tmp_path, policy=DocumentationPolicy())
        assert _run_staged(context) == []


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

    def test_unreadable_quoting_file_is_skipped_not_fatal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """N5 (Plan 00287): an unreadable quoting file must not abort the
        whole SessionStart sweep."""
        (tmp_path / "CLAUDE").mkdir()
        source = tmp_path / "CLAUDE" / "Source.md"
        source.write_text(f"## Anchor\n\n{_LONG_SENTENCE}\n")
        quoter = tmp_path / "CLAUDE" / "Quoter.md"
        quoter.write_text(_quote_block("CLAUDE/Source.md", "anchor", _LONG_SENTENCE))
        policy = DocumentationPolicy()
        corpus = _build_corpus(tmp_path, policy)

        original_read_text = Path.read_text

        def _raising_read_text(
            self: Path, encoding: str | None = None, errors: str | None = None
        ) -> str:
            if self == quoter:
                raise OSError("permission denied")
            return original_read_text(self, encoding=encoding, errors=errors)

        monkeypatch.setattr(Path, "read_text", _raising_read_text)
        context = sweep_context(project_root=tmp_path, policy=policy, corpus=corpus)
        assert _run_sweep(context) == []

    def test_unreadable_source_file_is_reported_not_fatal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """N5 (Plan 00287): an unreadable SOURCE file (the quote's target)
        must not crash the check either -- report it, the same way a
        missing source file is reported."""
        (tmp_path / "CLAUDE").mkdir()
        source = tmp_path / "CLAUDE" / "Source.md"
        source.write_text(f"## Anchor\n\n{_LONG_SENTENCE}\n")
        quoter = tmp_path / "CLAUDE" / "Quoter.md"
        quoter.write_text(_quote_block("CLAUDE/Source.md", "anchor", _LONG_SENTENCE))
        policy = DocumentationPolicy()
        corpus = _build_corpus(tmp_path, policy)

        original_read_text = Path.read_text

        def _raising_read_text(
            self: Path, encoding: str | None = None, errors: str | None = None
        ) -> str:
            if self == source:
                raise OSError("permission denied")
            return original_read_text(self, encoding=encoding, errors=errors)

        monkeypatch.setattr(Path, "read_text", _raising_read_text)
        context = sweep_context(project_root=tmp_path, policy=policy, corpus=corpus)
        findings = _run_sweep(context)
        assert len(findings) == 1
        assert "could not be read" in findings[0].message

    def test_document_with_no_quotes_is_skipped_cheaply(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "CLAUDE" / "Plain.md").write_text("# Plain\n\njust prose\n")
        policy = DocumentationPolicy()
        corpus = _build_corpus(tmp_path, policy)
        context = sweep_context(project_root=tmp_path, policy=policy, corpus=corpus)
        assert _run_sweep(context) == []
