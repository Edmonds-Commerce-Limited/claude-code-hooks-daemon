"""Tests for check ``duplicate-block`` (Plan 00284, Task 3.1f)."""

from pathlib import Path

from claude_code_hooks_daemon.docs_qa.checks.duplicate_block import CHECK_ID, CHECKS
from claude_code_hooks_daemon.docs_qa.context import edit_context, sweep_context
from claude_code_hooks_daemon.docs_qa.corpus import DocCorpus, DocRecord
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy, DocumentationQaPolicy
from claude_code_hooks_daemon.docs_qa.structured_blocks import extract_structured_block_hashes
from claude_code_hooks_daemon.docs_qa.types import CheckContext, CheckStage, Finding, Severity

_LONG_FENCE_BODY = "\n".join(
    f"echo 'line number {n} of a long fenced example block'" for n in range(6)
)
_DUPLICATED_TEXT = f"# Doc\n\n```bash\n{_LONG_FENCE_BODY}\n```\n"
_DUPLICATED_HASHES = extract_structured_block_hashes(_DUPLICATED_TEXT)


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


def _record(rel_path: str, block_hashes: tuple[str, ...] = ()) -> DocRecord:
    return DocRecord(rel_path=rel_path, mtime_ns=1, size=1, links=(), block_hashes=block_hashes)


class TestRegistration:
    def test_registers_edit_and_sweep_only(self) -> None:
        stages = {spec.stage for spec in CHECKS}
        assert stages == {CheckStage.EDIT, CheckStage.SWEEP}
        assert all(spec.check_id == CHECK_ID for spec in CHECKS)


class TestNeverBlockEligible:
    def test_every_finding_is_advise_severity(self, tmp_path: Path) -> None:
        """The design's own gate: no severity path in this check may be BLOCK
        until a hand-triaged whole-repo run authorises promotion."""
        corpus = DocCorpus(
            project_root=tmp_path,
            documents={
                "A.md": _record("A.md", block_hashes=_DUPLICATED_HASHES),
                "B.md": _record("B.md", block_hashes=_DUPLICATED_HASHES),
            },
        )
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "A.md",
            file_content=_DUPLICATED_TEXT,
            file_exists_before=True,
            corpus=corpus,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert all(finding.severity is Severity.ADVISE for finding in findings)


class TestEditStage:
    def test_cold_corpus_produces_no_findings(self, tmp_path: Path) -> None:
        cold_corpus = DocCorpus(project_root=tmp_path, documents={}, cold=True)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "A.md",
            file_content=_DUPLICATED_TEXT,
            file_exists_before=True,
            corpus=cold_corpus,
        )
        assert _run_edit(context) == []

    def test_no_corpus_at_all_produces_no_findings(self, tmp_path: Path) -> None:
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "A.md",
            file_content=_DUPLICATED_TEXT,
            file_exists_before=True,
            corpus=None,
        )
        assert _run_edit(context) == []

    def test_block_shared_with_another_document_is_flagged(self, tmp_path: Path) -> None:
        corpus = DocCorpus(
            project_root=tmp_path,
            documents={
                "A.md": _record("A.md", block_hashes=_DUPLICATED_HASHES),
                "B.md": _record("B.md", block_hashes=_DUPLICATED_HASHES),
            },
        )
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "A.md",
            file_content=_DUPLICATED_TEXT,
            file_exists_before=True,
            corpus=corpus,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert findings[0].path == "A.md"
        assert "B.md" in findings[0].message

    def test_block_unique_to_this_document_produces_no_finding(self, tmp_path: Path) -> None:
        corpus = DocCorpus(
            project_root=tmp_path,
            documents={"A.md": _record("A.md", block_hashes=_DUPLICATED_HASHES)},
        )
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "A.md",
            file_content=_DUPLICATED_TEXT,
            file_exists_before=True,
            corpus=corpus,
        )
        assert _run_edit(context) == []

    def test_the_corpus_own_stale_copy_of_the_edited_file_is_never_its_own_partner(
        self, tmp_path: Path
    ) -> None:
        """The cached corpus record for the file BEING edited must never
        count itself as a duplicate partner of its own new content."""
        corpus = DocCorpus(
            project_root=tmp_path,
            documents={"A.md": _record("A.md", block_hashes=_DUPLICATED_HASHES)},
        )
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "A.md",
            file_content=_DUPLICATED_TEXT,
            file_exists_before=True,
            corpus=corpus,
        )
        assert _run_edit(context) == []

    def test_no_structured_blocks_produces_no_finding(self, tmp_path: Path) -> None:
        corpus = DocCorpus(
            project_root=tmp_path,
            documents={"B.md": _record("B.md", block_hashes=_DUPLICATED_HASHES)},
        )
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "A.md",
            file_content="Just plain prose, nothing structured here.\n",
            file_exists_before=True,
            corpus=corpus,
        )
        assert _run_edit(context) == []

    def test_grandfathered_file_produces_no_finding(self, tmp_path: Path) -> None:
        corpus = DocCorpus(
            project_root=tmp_path,
            documents={
                "A.md": _record("A.md", block_hashes=_DUPLICATED_HASHES),
                "B.md": _record("B.md", block_hashes=_DUPLICATED_HASHES),
            },
        )
        policy = DocumentationPolicy(qa=DocumentationQaPolicy(grandfather_allowlist=("A.md",)))
        context = edit_context(
            project_root=tmp_path,
            policy=policy,
            file_path=tmp_path / "A.md",
            file_content=_DUPLICATED_TEXT,
            file_exists_before=True,
            corpus=corpus,
        )
        assert _run_edit(context) == []

    def test_no_file_content_produces_no_findings(self, tmp_path: Path) -> None:
        context = CheckContext(project_root=tmp_path, policy=DocumentationPolicy())
        assert _run_edit(context) == []


class TestSweepStage:
    def test_no_corpus_produces_no_findings(self, tmp_path: Path) -> None:
        context = CheckContext(project_root=tmp_path, policy=DocumentationPolicy())
        assert _run_sweep(context) == []

    def test_shared_block_reports_once_naming_both_files(self, tmp_path: Path) -> None:
        corpus = DocCorpus(
            project_root=tmp_path,
            documents={
                "A.md": _record("A.md", block_hashes=_DUPLICATED_HASHES),
                "B.md": _record("B.md", block_hashes=_DUPLICATED_HASHES),
            },
        )
        context = sweep_context(project_root=tmp_path, policy=DocumentationPolicy(), corpus=corpus)
        findings = _run_sweep(context)
        assert len(findings) == 1
        # Deterministic reporter: the alphabetically-first path of the pair.
        assert findings[0].path == "A.md"
        assert "B.md" in findings[0].message

    def test_three_way_duplicate_reports_exactly_once(self, tmp_path: Path) -> None:
        corpus = DocCorpus(
            project_root=tmp_path,
            documents={
                "A.md": _record("A.md", block_hashes=_DUPLICATED_HASHES),
                "B.md": _record("B.md", block_hashes=_DUPLICATED_HASHES),
                "C.md": _record("C.md", block_hashes=_DUPLICATED_HASHES),
            },
        )
        context = sweep_context(project_root=tmp_path, policy=DocumentationPolicy(), corpus=corpus)
        findings = _run_sweep(context)
        assert len(findings) == 1
        assert findings[0].path == "A.md"
        assert "B.md" in findings[0].message
        assert "C.md" in findings[0].message

    def test_unique_blocks_produce_no_findings(self, tmp_path: Path) -> None:
        corpus = DocCorpus(
            project_root=tmp_path,
            documents={
                "A.md": _record("A.md", block_hashes=_DUPLICATED_HASHES),
                "B.md": _record("B.md", block_hashes=()),
            },
        )
        context = sweep_context(project_root=tmp_path, policy=DocumentationPolicy(), corpus=corpus)
        assert _run_sweep(context) == []

    def test_grandfathered_reporter_suppresses_the_finding(self, tmp_path: Path) -> None:
        corpus = DocCorpus(
            project_root=tmp_path,
            documents={
                "A.md": _record("A.md", block_hashes=_DUPLICATED_HASHES),
                "B.md": _record("B.md", block_hashes=_DUPLICATED_HASHES),
            },
        )
        policy = DocumentationPolicy(qa=DocumentationQaPolicy(grandfather_allowlist=("A.md",)))
        context = sweep_context(project_root=tmp_path, policy=policy, corpus=corpus)
        assert _run_sweep(context) == []

    def test_a_document_repeating_its_own_block_is_never_a_self_duplicate(
        self, tmp_path: Path
    ) -> None:
        corpus = DocCorpus(
            project_root=tmp_path,
            documents={
                "A.md": _record("A.md", block_hashes=_DUPLICATED_HASHES + _DUPLICATED_HASHES),
            },
        )
        context = sweep_context(project_root=tmp_path, policy=DocumentationPolicy(), corpus=corpus)
        assert _run_sweep(context) == []
