"""Tests for check ``generated-doc-hand-edit`` (Plan 00284, Task 3.1b)."""

import subprocess  # nosec B404 — runs the trusted system `git`
from pathlib import Path

import pytest

from claude_code_hooks_daemon.docs_qa.checks.generated_doc_hand_edit import CHECK_ID, CHECKS
from claude_code_hooks_daemon.docs_qa.context import edit_context, sweep_context
from claude_code_hooks_daemon.docs_qa.corpus import DocCorpus
from claude_code_hooks_daemon.docs_qa.policy import (
    DocumentationPolicy,
    DocumentationQaPolicy,
    GeneratedDocEntry,
)
from claude_code_hooks_daemon.docs_qa.types import CheckContext, CheckStage, Finding, Severity
from claude_code_hooks_daemon.version import __version__ as DAEMON_VERSION


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


def _policy(*entries: GeneratedDocEntry, grandfather: tuple[str, ...] = ()) -> DocumentationPolicy:
    return DocumentationPolicy(
        qa=DocumentationQaPolicy(generated_docs=entries, grandfather_allowlist=grandfather)
    )


_ENTRY = GeneratedDocEntry(
    glob=".claude/HOOKS-DAEMON.md", generator="bin/hooks-daemon generate-docs"
)

_GIT_TIMEOUT_SECONDS = 30


def _git(repo: Path, *args: str) -> None:
    """Run a git command in `repo`, failing the test on a non-zero exit."""
    subprocess.run(  # nosec B603 B607 — fixed argv, no shell, trusted input
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_SECONDS,
        check=True,
    )


def _git_repo(root: Path) -> None:
    """A real repository — trackedness is a git fact, so it is asked of git."""
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "test")


class TestRegistration:
    def test_registers_edit_and_sweep(self) -> None:
        stages = {spec.stage for spec in CHECKS}
        assert stages == {CheckStage.EDIT, CheckStage.SWEEP}
        assert all(spec.check_id == CHECK_ID for spec in CHECKS)


class TestEditStageHandEditDetection:
    def test_edit_to_manifest_matched_path_is_block(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=_policy(_ENTRY),
            file_path=tmp_path / ".claude" / "HOOKS-DAEMON.md",
            file_content="# hand edit\n",
            file_exists_before=True,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert findings[0].check_id == CHECK_ID
        assert findings[0].severity is Severity.BLOCK
        assert findings[0].path == ".claude/HOOKS-DAEMON.md"
        assert "bin/hooks-daemon generate-docs" in findings[0].message
        assert "bin/hooks-daemon generate-docs" in findings[0].remediation

    def test_edit_to_unmatched_path_produces_no_finding(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=_policy(_ENTRY),
            file_path=tmp_path / "CLAUDE" / "Other.md",
            file_content="# fine\n",
            file_exists_before=True,
        )
        assert _run_edit(context) == []

    def test_no_manifest_entries_produces_no_finding(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=_policy(),
            file_path=tmp_path / ".claude" / "HOOKS-DAEMON.md",
            file_content="# hand edit\n",
            file_exists_before=True,
        )
        assert _run_edit(context) == []

    def test_grandfathered_path_is_advise(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=_policy(_ENTRY, grandfather=(".claude/HOOKS-DAEMON.md",)),
            file_path=tmp_path / ".claude" / "HOOKS-DAEMON.md",
            file_content="# hand edit\n",
            file_exists_before=True,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE

    def test_glob_pattern_with_wildcard_matches(self, tmp_path: Path) -> None:
        (tmp_path / "docs").mkdir()
        entry = GeneratedDocEntry(glob="docs/*.md", generator="make docs")
        context = edit_context(
            project_root=tmp_path,
            policy=_policy(entry),
            file_path=tmp_path / "docs" / "GEN.md",
            file_content="# hand edit\n",
            file_exists_before=True,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert "make docs" in findings[0].message

    def test_missing_file_path_or_content_produces_no_findings(self, tmp_path: Path) -> None:
        context_no_path = CheckContext(
            project_root=tmp_path, policy=_policy(_ENTRY), file_content="x"
        )
        context_no_content = CheckContext(
            project_root=tmp_path,
            policy=_policy(_ENTRY),
            file_path=tmp_path / ".claude" / "HOOKS-DAEMON.md",
        )
        assert _run_edit(context_no_path) == []
        assert _run_edit(context_no_content) == []

    def test_edit_stage_never_consults_the_corpus(self, tmp_path: Path) -> None:
        """No corpus is built or read here — path-vs-glob only (see module docstring)."""
        (tmp_path / ".claude").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=_policy(_ENTRY),
            file_path=tmp_path / ".claude" / "HOOKS-DAEMON.md",
            file_content="# hand edit\n",
            file_exists_before=True,
        )
        assert context.corpus is None
        assert len(_run_edit(context)) == 1


class TestSweepStageFreshness:
    def test_stale_version_marker_is_advise(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        target = tmp_path / ".claude" / "HOOKS-DAEMON.md"
        target.write_text("> Generated on 2020-01-01 (v0.0.1) by `generate-docs`.\n")
        context = sweep_context(
            project_root=tmp_path,
            policy=_policy(_ENTRY),
            corpus=DocCorpus(project_root=tmp_path, documents={}),
        )
        findings = _run_sweep(context)
        assert len(findings) == 1
        assert findings[0].check_id == CHECK_ID
        assert findings[0].severity is Severity.ADVISE
        assert "0.0.1" in findings[0].message
        assert DAEMON_VERSION in findings[0].message
        assert "bin/hooks-daemon generate-docs" in findings[0].remediation

    def test_a_tracked_generated_doc_is_told_to_commit_the_result(self, tmp_path: Path) -> None:
        """Plan 00386 Phase 4, the OUTBOUND half of GitHub issue #38.

        Regenerating a TRACKED artefact and stopping there leaves the repository
        still committing a description of a daemon it no longer has — the next
        checkout deploys the old assets and the drift is back. "Regenerate" alone
        does not say that; the reader has to be told the diff must be committed.
        """
        _git_repo(tmp_path)
        (tmp_path / ".claude").mkdir()
        target = tmp_path / ".claude" / "HOOKS-DAEMON.md"
        target.write_text("> Generated on 2020-01-01 (v0.0.1) by `generate-docs`.\n")
        _git(tmp_path, "add", ".claude/HOOKS-DAEMON.md")
        _git(tmp_path, "commit", "-m", "add generated doc")

        context = sweep_context(
            project_root=tmp_path,
            policy=_policy(_ENTRY),
            corpus=DocCorpus(project_root=tmp_path, documents={}),
        )
        findings = _run_sweep(context)

        assert len(findings) == 1
        assert "commit" in findings[0].remediation.lower(), findings[0].remediation
        assert "bin/hooks-daemon generate-docs" in findings[0].remediation

    def test_an_untracked_generated_doc_is_not_told_to_commit(self, tmp_path: Path) -> None:
        """The advice has to be true. A generated doc a project does not track is
        regenerated locally and nothing is owed to history — telling that reader
        to commit would send them to stage a gitignored file."""
        _git_repo(tmp_path)
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "HOOKS-DAEMON.md").write_text(
            "> Generated on 2020-01-01 (v0.0.1) by `generate-docs`.\n"
        )

        context = sweep_context(
            project_root=tmp_path,
            policy=_policy(_ENTRY),
            corpus=DocCorpus(project_root=tmp_path, documents={}),
        )
        findings = _run_sweep(context)

        assert len(findings) == 1
        assert "commit" not in findings[0].remediation.lower(), findings[0].remediation

    def test_outside_a_git_repository_the_finding_still_lands(self, tmp_path: Path) -> None:
        """Trackedness is unknowable here, and an unknowable extra sentence must
        never cost the reader the staleness report itself."""
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "HOOKS-DAEMON.md").write_text(
            "> Generated on 2020-01-01 (v0.0.1) by `generate-docs`.\n"
        )

        context = sweep_context(
            project_root=tmp_path,
            policy=_policy(_ENTRY),
            corpus=DocCorpus(project_root=tmp_path, documents={}),
        )
        findings = _run_sweep(context)

        assert len(findings) == 1
        assert "0.0.1" in findings[0].message

    def test_current_version_marker_produces_no_finding(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        target = tmp_path / ".claude" / "HOOKS-DAEMON.md"
        target.write_text(f"> Generated on 2020-01-01 (v{DAEMON_VERSION}) by `generate-docs`.\n")
        context = sweep_context(
            project_root=tmp_path,
            policy=_policy(_ENTRY),
            corpus=DocCorpus(project_root=tmp_path, documents={}),
        )
        assert _run_sweep(context) == []

    def test_no_recognisable_marker_is_skipped_silently(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        target = tmp_path / ".claude" / "HOOKS-DAEMON.md"
        target.write_text("# Some other doc with no marker at all\n")
        context = sweep_context(
            project_root=tmp_path,
            policy=_policy(_ENTRY),
            corpus=DocCorpus(project_root=tmp_path, documents={}),
        )
        assert _run_sweep(context) == []

    def test_unreadable_file_is_skipped_not_fatal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """N5 (Plan 00287): an unreadable file must not abort the whole
        SessionStart sweep."""
        (tmp_path / ".claude").mkdir()
        target = tmp_path / ".claude" / "HOOKS-DAEMON.md"
        target.write_text("> Generated on 2020-01-01 (v0.0.1) by `x`.\n")

        original_read_text = Path.read_text

        def _raising_read_text(
            self: Path, encoding: str | None = None, errors: str | None = None
        ) -> str:
            if self == target:
                raise OSError("permission denied")
            return original_read_text(self, encoding=encoding, errors=errors)

        monkeypatch.setattr(Path, "read_text", _raising_read_text)
        context = sweep_context(
            project_root=tmp_path,
            policy=_policy(_ENTRY),
            corpus=DocCorpus(project_root=tmp_path, documents={}),
        )
        assert _run_sweep(context) == []

    def test_manifest_entry_matching_no_files_produces_no_finding(self, tmp_path: Path) -> None:
        context = sweep_context(
            project_root=tmp_path,
            policy=_policy(_ENTRY),
            corpus=DocCorpus(project_root=tmp_path, documents={}),
        )
        assert _run_sweep(context) == []

    def test_glob_matching_multiple_files_checks_each(self, tmp_path: Path) -> None:
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "A.md").write_text("> Generated on 2020-01-01 (v0.0.1) by `x`.\n")
        (tmp_path / "docs" / "B.md").write_text(
            f"> Generated on 2020-01-01 (v{DAEMON_VERSION}) by `x`.\n"
        )
        entry = GeneratedDocEntry(glob="docs/*.md", generator="make docs")
        context = sweep_context(
            project_root=tmp_path,
            policy=_policy(entry),
            corpus=DocCorpus(project_root=tmp_path, documents={}),
        )
        findings = _run_sweep(context)
        assert len(findings) == 1
        assert findings[0].path == "docs/A.md"

    def test_no_manifest_entries_produces_no_finding(self, tmp_path: Path) -> None:
        context = sweep_context(
            project_root=tmp_path,
            policy=_policy(),
            corpus=DocCorpus(project_root=tmp_path, documents={}),
        )
        assert _run_sweep(context) == []
