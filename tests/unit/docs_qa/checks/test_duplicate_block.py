"""Tests for check ``duplicate-block`` (Plan 00284, Task 3.1f)."""

from pathlib import Path

from claude_code_hooks_daemon.docs_qa.checks.duplicate_block import CHECK_ID, CHECKS
from claude_code_hooks_daemon.docs_qa.context import edit_context, sweep_context
from claude_code_hooks_daemon.docs_qa.corpus import DocCorpus, DocRecord
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy, DocumentationQaPolicy
from claude_code_hooks_daemon.docs_qa.structured_blocks import (
    extract_structured_block_hashes,
    extract_structured_block_locations,
)
from claude_code_hooks_daemon.docs_qa.types import CheckContext, CheckStage, Finding, Severity

_LONG_FENCE_BODY = "\n".join(
    f"echo 'line number {n} of a long fenced example block'" for n in range(6)
)
_DUPLICATED_TEXT = f"# Doc\n\n```bash\n{_LONG_FENCE_BODY}\n```\n"
_DUPLICATED_HASHES = extract_structured_block_hashes(_DUPLICATED_TEXT)
_DUPLICATED_LOCATIONS = extract_structured_block_locations(_DUPLICATED_TEXT)


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
    # ``block_locations`` mirrors ``_DUPLICATED_LOCATIONS`` whenever the
    # caller passes ``_DUPLICATED_HASHES`` (repeated N times over, matching
    # a self-duplicating record) -- both are derived from the same source
    # text, so this keeps every existing call site correct without editing
    # them individually.
    location_count = len(block_hashes) // max(len(_DUPLICATED_HASHES), 1)
    block_locations = _DUPLICATED_LOCATIONS * location_count if block_hashes else ()
    return DocRecord(
        rel_path=rel_path,
        mtime_ns=1,
        size=1,
        links=(),
        block_hashes=block_hashes,
        block_locations=block_locations,
    )


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


class TestLineRanges:
    """Task 3.3 T1: findings must cite ``path:start-end`` for BOTH sides."""

    def test_edit_stage_message_cites_own_and_partner_spans(self, tmp_path: Path) -> None:
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
        own_start = _DUPLICATED_LOCATIONS[0].start_line
        own_end = _DUPLICATED_LOCATIONS[0].end_line
        assert f"A.md:{own_start}-{own_end}" in findings[0].message
        assert f"B.md:{own_start}-{own_end}" in findings[0].message

    def test_sweep_stage_message_cites_reporter_and_partner_spans(self, tmp_path: Path) -> None:
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
        start = _DUPLICATED_LOCATIONS[0].start_line
        end = _DUPLICATED_LOCATIONS[0].end_line
        assert f"A.md:{start}-{end}" in findings[0].message
        assert f"B.md:{start}-{end}" in findings[0].message

    def test_two_distinct_duplicated_blocks_in_one_file_produce_two_findings(
        self, tmp_path: Path
    ) -> None:
        """A file with two DIFFERENT duplicated blocks (different hashes,
        different partners) gets one finding per block, each citing its own
        specific span -- not one finding aggregating every partner."""
        other_fence_body = "\n".join(
            f"echo 'a distinct second line {n} of another example'" for n in range(6)
        )
        other_text = f"```bash\n{other_fence_body}\n```\n"
        other_locations = extract_structured_block_locations(other_text)
        combined_text = f"{_DUPLICATED_TEXT}\n{other_text}"

        combined_locations = extract_structured_block_locations(combined_text)
        corpus = DocCorpus(
            project_root=tmp_path,
            documents={
                # A stale pre-edit copy of A.md itself, so each shared hash
                # reaches the required 2 DISTINCT documents in the index
                # before the rel_path self-filter removes it -- mirrors
                # ``test_block_shared_with_another_document_is_flagged``.
                "A.md": DocRecord(
                    rel_path="A.md",
                    mtime_ns=1,
                    size=1,
                    links=(),
                    block_hashes=tuple(loc.block_hash for loc in combined_locations),
                    block_locations=combined_locations,
                ),
                "B.md": _record("B.md", block_hashes=_DUPLICATED_HASHES),
                "C.md": DocRecord(
                    rel_path="C.md",
                    mtime_ns=1,
                    size=1,
                    links=(),
                    block_hashes=tuple(loc.block_hash for loc in other_locations),
                    block_locations=other_locations,
                ),
            },
        )
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "A.md",
            file_content=combined_text,
            file_exists_before=True,
            corpus=corpus,
        )
        findings = _run_edit(context)
        assert len(findings) == 2
        partner_names = {finding.message.split(":")[0] for finding in findings}
        messages = " ".join(finding.message for finding in findings)
        assert "B.md" in messages
        assert "C.md" in messages
        assert partner_names == {"`A.md"}  # both findings are reported on A.md's own spans
