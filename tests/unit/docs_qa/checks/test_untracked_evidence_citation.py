"""Tests for check ``untracked-evidence-citation`` (Plan 00627, Task 7.3)."""

from pathlib import Path

from claude_code_hooks_daemon.docs_qa.checks import all_checks
from claude_code_hooks_daemon.docs_qa.checks.untracked_evidence_citation import CHECK_ID, CHECKS
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy
from claude_code_hooks_daemon.docs_qa.types import CheckContext, CheckStage, Finding, Severity

_CITING = "The measured results are in `untracked/scratch/bench-run.txt`."


def _run(
    tmp_path: Path,
    content: str,
    before: str | None = None,
    name: str = "CLAUDE/Plan/00001-x/PLAN.md",
) -> list[Finding]:
    context = CheckContext(
        project_root=tmp_path,
        policy=DocumentationPolicy(),
        file_path=tmp_path / name,
        file_content=content,
        file_content_before=before,
    )
    (spec,) = CHECKS
    assert spec.stage is CheckStage.EDIT
    return spec.run(context)


def test_registered_in_catalogue() -> None:
    assert any(spec.check_id == CHECK_ID for spec in all_checks())


def test_new_line_citing_untracked_file_as_evidence_is_advised(tmp_path: Path) -> None:
    findings = _run(tmp_path, f"# Plan\n\n{_CITING}\n")
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity is Severity.ADVISE
    assert "untracked/scratch/bench-run.txt" in finding.message
    assert "line 3" in finding.message
    assert "subagent-reports/" in finding.remediation


def test_line_already_present_before_the_edit_is_not_flagged(tmp_path: Path) -> None:
    content = f"# Plan\n\n{_CITING}\n"
    assert _run(tmp_path, content + "More.\n", before=content) == []


def test_bare_directory_is_an_instruction_not_evidence(tmp_path: Path) -> None:
    content = "Write the measured results to `untracked/scratch/` first.\n"
    assert _run(tmp_path, content) == []


def test_path_without_evidence_word_is_not_flagged(tmp_path: Path) -> None:
    assert _run(tmp_path, "Run it with output in untracked/scratch/out.txt\n") == []


def test_fenced_code_block_is_skipped(tmp_path: Path) -> None:
    content = f"```bash\n# {_CITING}\n```\n"
    assert _run(tmp_path, content) == []


def test_non_markdown_file_is_skipped(tmp_path: Path) -> None:
    assert _run(tmp_path, _CITING, name="src/x.py") == []


def test_a_doc_that_is_itself_untracked_is_skipped(tmp_path: Path) -> None:
    assert _run(tmp_path, _CITING, name="untracked/scratch/notes.md") == []


def test_untracked_inside_another_word_is_not_a_path(tmp_path: Path) -> None:
    assert _run(tmp_path, "Evidence: notuntracked/foo.txt\n") == []


def test_no_content_is_silent(tmp_path: Path) -> None:
    context = CheckContext(project_root=tmp_path, policy=DocumentationPolicy())
    (spec,) = CHECKS
    assert spec.run(context) == []
