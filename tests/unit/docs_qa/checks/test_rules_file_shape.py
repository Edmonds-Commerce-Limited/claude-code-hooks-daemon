"""Tests for check ``rules-file-shape`` (Plan 00284, Task 3.1c)."""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.docs_qa.checks.rules_file_shape import (
    CHECK_ID,
    CHECKS,
    RULES_FILE_BODY_LINE_BUDGET,
)
from claude_code_hooks_daemon.docs_qa.context import edit_context, sweep_context
from claude_code_hooks_daemon.docs_qa.corpus import DocCorpus
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy, DocumentationQaPolicy
from claude_code_hooks_daemon.docs_qa.types import CheckContext, CheckStage, Finding, Severity

_FRONTMATTER = "---\npaths:\n  - '*'\ndescription: x\n---\n"


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


def _rules_path(tmp_path: Path, name: str = "one.md") -> Path:
    rules_dir = tmp_path / ".claude" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    return rules_dir / name


_COMPLIANT_BODY = _FRONTMATTER + (
    "# Trigger\n\nYou are reading this because X.\n\nDo the thing.\n\nSee [docs](../../CLAUDE/X.md).\n"
)

_FENCE_BODY = _FRONTMATTER + "# T\n\n```bash\necho hi\n```\n\nSee [x](../../CLAUDE/X.md).\n"

_TABLE_BODY = _FRONTMATTER + (
    "# T\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\nSee [x](../../CLAUDE/X.md).\n"
)

_PROCEDURE_BODY = _FRONTMATTER + (
    "# T\n\n1. First\n2. Second\n3. Third\n\nSee [x](../../CLAUDE/X.md).\n"
)

_SSOT_QUOTE_BODY = _FRONTMATTER + (
    "# T\n\n<!-- ssot-quote: CLAUDE/X.md#anchor -->\nquoted text\n<!-- /ssot-quote -->\n"
)


class TestRegistration:
    def test_registers_edit_and_sweep(self) -> None:
        stages = {spec.stage for spec in CHECKS}
        assert stages == {CheckStage.EDIT, CheckStage.SWEEP}
        assert all(spec.check_id == CHECK_ID for spec in CHECKS)


class TestScope:
    def test_ignores_files_outside_claude_rules(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "X.md",
            file_content=_FENCE_BODY,
            file_exists_before=False,
        )
        assert _run_edit(context) == []

    def test_ignores_nested_rules_subdirectories(self, tmp_path: Path) -> None:
        nested = tmp_path / ".claude" / "rules" / "sub" / "deep.md"
        nested.parent.mkdir(parents=True)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=nested,
            file_content=_FENCE_BODY,
            file_exists_before=False,
        )
        assert _run_edit(context) == []


class TestEditStageWorseOnly:
    def test_compliant_new_file_produces_no_finding(self, tmp_path: Path) -> None:
        target = _rules_path(tmp_path)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=target,
            file_content=_COMPLIANT_BODY,
            file_exists_before=False,
        )
        assert _run_edit(context) == []

    def test_brand_new_file_with_a_fence_is_block(self, tmp_path: Path) -> None:
        target = _rules_path(tmp_path)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=target,
            file_content=_FENCE_BODY,
            file_exists_before=False,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert findings[0].check_id == CHECK_ID
        assert findings[0].severity is Severity.BLOCK
        assert "fence" in findings[0].message.lower()
        assert "R7a" in findings[0].remediation
        assert "DocumentationStrategy.md" in findings[0].remediation

    def test_brand_new_file_with_a_table_is_block(self, tmp_path: Path) -> None:
        target = _rules_path(tmp_path)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=target,
            file_content=_TABLE_BODY,
            file_exists_before=False,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert "table" in findings[0].message.lower()

    def test_brand_new_file_with_a_numbered_procedure_run_is_block(self, tmp_path: Path) -> None:
        target = _rules_path(tmp_path)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=target,
            file_content=_PROCEDURE_BODY,
            file_exists_before=False,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert "procedure" in findings[0].message.lower()

    def test_two_item_ordered_list_is_not_a_procedure_run(self, tmp_path: Path) -> None:
        target = _rules_path(tmp_path)
        body = _FRONTMATTER + "# T\n\n1. First\n2. Second\n\nSee [x](../../CLAUDE/X.md).\n"
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=target,
            file_content=body,
            file_exists_before=False,
        )
        assert _run_edit(context) == []

    def test_brand_new_file_with_ssot_quote_is_block(self, tmp_path: Path) -> None:
        target = _rules_path(tmp_path)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=target,
            file_content=_SSOT_QUOTE_BODY,
            file_exists_before=False,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert "ssot-quote" in findings[0].message.lower()

    def test_brand_new_file_over_budget_is_block(self, tmp_path: Path) -> None:
        target = _rules_path(tmp_path)
        long_body = _FRONTMATTER + "# T\n\n" + "\n".join(f"line {i}" for i in range(30)) + "\n"
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=target,
            file_content=long_body,
            file_exists_before=False,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert "budget" in findings[0].message.lower()
        assert str(RULES_FILE_BODY_LINE_BUDGET) in findings[0].message

    def test_frontmatter_never_counts_toward_the_body_budget(self, tmp_path: Path) -> None:
        target = _rules_path(tmp_path)
        # Frontmatter alone is well over 15 raw lines, but the compliant body
        # after it is short — must not trip the budget.
        huge_frontmatter = "---\n" + "\n".join(f"note: {i}" for i in range(30)) + "\n---\n"
        body = huge_frontmatter + "# T\n\nRule.\n\nSee [x](../../CLAUDE/X.md).\n"
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=target,
            file_content=body,
            file_exists_before=False,
        )
        assert _run_edit(context) == []

    def test_adding_a_fence_to_an_existing_file_is_block(self, tmp_path: Path) -> None:
        target = _rules_path(tmp_path)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=target,
            file_content=_FENCE_BODY,
            file_exists_before=True,
            file_content_before=_COMPLIANT_BODY,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.BLOCK

    def test_unchanged_violating_content_is_advise(self, tmp_path: Path) -> None:
        target = _rules_path(tmp_path)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=target,
            file_content=_FENCE_BODY,
            file_exists_before=True,
            file_content_before=_FENCE_BODY,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE

    def test_removing_a_fence_is_silent(self, tmp_path: Path) -> None:
        target = _rules_path(tmp_path)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=target,
            file_content=_COMPLIANT_BODY,
            file_exists_before=True,
            file_content_before=_FENCE_BODY,
        )
        assert _run_edit(context) == []

    def test_reducing_fence_count_from_two_to_one_is_silent(self, tmp_path: Path) -> None:
        target = _rules_path(tmp_path)
        two_fences = _FRONTMATTER + (
            "# T\n\n```bash\na\n```\n\n```bash\nb\n```\n\nSee [x](../../CLAUDE/X.md).\n"
        )
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=target,
            file_content=_FENCE_BODY,
            file_exists_before=True,
            file_content_before=two_fences,
        )
        assert _run_edit(context) == []

    def test_grandfathered_new_violation_is_advise(self, tmp_path: Path) -> None:
        target = _rules_path(tmp_path)
        policy = DocumentationPolicy(
            qa=DocumentationQaPolicy(grandfather_allowlist=(".claude/rules/*.md",))
        )
        context = edit_context(
            project_root=tmp_path,
            policy=policy,
            file_path=target,
            file_content=_FENCE_BODY,
            file_exists_before=False,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE

    def test_body_growing_while_still_under_budget_is_silent(self, tmp_path: Path) -> None:
        target = _rules_path(tmp_path)
        short_before = _FRONTMATTER + "# T\n\nRule.\n"
        short_after = _FRONTMATTER + "# T\n\nRule.\n\nSee [x](../../CLAUDE/X.md).\n"
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=target,
            file_content=short_after,
            file_exists_before=True,
            file_content_before=short_before,
        )
        assert _run_edit(context) == []

    def test_procedure_run_ending_exactly_at_end_of_file_counts(self, tmp_path: Path) -> None:
        target = _rules_path(tmp_path)
        body = _FRONTMATTER + "# T\n\n1. First\n2. Second\n3. Third\n"
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=target,
            file_content=body,
            file_exists_before=False,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert "procedure" in findings[0].message.lower()

    def test_non_markdown_file_in_rules_dir_is_out_of_scope(self, tmp_path: Path) -> None:
        rules_dir = tmp_path / ".claude" / "rules"
        rules_dir.mkdir(parents=True)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=rules_dir / "notes.txt",
            file_content=_FENCE_BODY,
            file_exists_before=False,
        )
        assert _run_edit(context) == []

    def test_path_outside_project_root_is_out_of_scope(self, tmp_path: Path) -> None:
        other_root = tmp_path / "elsewhere"
        outside_file = other_root / ".claude" / "rules" / "one.md"
        outside_file.parent.mkdir(parents=True)
        outside_file.write_text(_FENCE_BODY)
        project_root = tmp_path / "project"
        project_root.mkdir()
        context = edit_context(
            project_root=project_root,
            policy=DocumentationPolicy(),
            file_path=outside_file,
            file_content=_FENCE_BODY,
            file_exists_before=False,
        )
        assert _run_edit(context) == []

    def test_body_over_budget_unchanged_in_size_is_advise(self, tmp_path: Path) -> None:
        target = _rules_path(tmp_path)
        long_body = _FRONTMATTER + "# T\n\n" + "\n".join(f"line {i}" for i in range(30)) + "\n"
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=target,
            file_content=long_body,
            file_exists_before=True,
            file_content_before=long_body,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE
        assert "budget" in findings[0].message.lower()

    def test_body_shrinking_while_still_over_budget_is_silent(self, tmp_path: Path) -> None:
        target = _rules_path(tmp_path)
        longer = _FRONTMATTER + "# T\n\n" + "\n".join(f"line {i}" for i in range(40)) + "\n"
        shorter_but_still_over = (
            _FRONTMATTER + "# T\n\n" + "\n".join(f"line {i}" for i in range(30)) + "\n"
        )
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=target,
            file_content=shorter_but_still_over,
            file_exists_before=True,
            file_content_before=longer,
        )
        assert _run_edit(context) == []

    def test_missing_file_path_or_content_produces_no_findings(self, tmp_path: Path) -> None:
        context_no_path = CheckContext(
            project_root=tmp_path, policy=DocumentationPolicy(), file_content=_FENCE_BODY
        )
        context_no_content = CheckContext(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=_rules_path(tmp_path),
        )
        assert _run_edit(context_no_path) == []
        assert _run_edit(context_no_content) == []


class TestSweepHonoursConfiguredScopeExclusions:
    """Sibling of the module-doc-budget defect, found by auditing for it.

    This SWEEP globs `.claude/rules/*.md` itself rather than reading the
    corpus, so it inherited none of the corpus's exclusions and consulted
    `scope_exclude_globs` nowhere. Narrower blast radius than
    module-doc-budget (a project-owned directory, not a vendored tree), but
    the same bug: a project that scope-excluded a rules file still got it
    reported on every sweep with no way to silence it.
    """

    def test_an_excluded_rules_file_is_not_reported(self, tmp_path: Path) -> None:
        _rules_path(tmp_path, "fences.md").write_text(_FENCE_BODY)
        context = sweep_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(
                qa=DocumentationQaPolicy(scope_exclude_globs=(".claude/rules/fences.md",))
            ),
            corpus=DocCorpus(project_root=tmp_path, documents={}),
        )
        assert _run_sweep(context) == []

    def test_an_unexcluded_rules_file_is_still_reported(self, tmp_path: Path) -> None:
        """Guard against over-fixing: the exclusion silences one file, not
        the check."""
        _rules_path(tmp_path, "fences.md").write_text(_FENCE_BODY)
        _rules_path(tmp_path, "other.md").write_text(_FENCE_BODY)
        context = sweep_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(
                qa=DocumentationQaPolicy(scope_exclude_globs=(".claude/rules/fences.md",))
            ),
            corpus=DocCorpus(project_root=tmp_path, documents={}),
        )
        findings = _run_sweep(context)
        assert [finding.path for finding in findings] == [".claude/rules/other.md"]


class TestSweepStage:
    def test_reports_every_violation_present_as_advise(self, tmp_path: Path) -> None:
        _rules_path(tmp_path, "fences.md").write_text(_FENCE_BODY)
        _rules_path(tmp_path, "clean.md").write_text(_COMPLIANT_BODY)
        context = sweep_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            corpus=DocCorpus(project_root=tmp_path, documents={}),
        )
        findings = _run_sweep(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE
        assert findings[0].path == ".claude/rules/fences.md"

    def test_real_repo_shaped_fixtures_are_editable_not_broken(self, tmp_path: Path) -> None:
        """Shaped on this repo's own two non-compliant rules files (Task 3.1c).

        Both currently fail the R7a contract (table + over-budget body;
        fences + over-budget body) — worse-only semantics must still allow
        UNRELATED edits to them (Task 3.2 fixes the content itself later).
        """
        table_and_long_body = _FRONTMATTER + (
            "# Importing a report\n\n"
            + "\n".join(f"prose line {i}" for i in range(20))
            + "\n\n| Remove | Replace with |\n| --- | --- |\n| a | b |\n"
        )
        fences_and_long_body = _FRONTMATTER + (
            "# Dogfooding\n\n"
            + "\n".join(f"prose line {i}" for i in range(20))
            + "\n\n```bash\nps -eo pid\n```\n\n```bash\nkill <pid>\n```\n"
        )
        for name, content in (
            ("importing-reports.md", table_and_long_body),
            ("ccy-supervisor-dogfooding.md", fences_and_long_body),
        ):
            target = _rules_path(tmp_path, name)
            target.write_text(content)
            context = edit_context(
                project_root=tmp_path,
                policy=DocumentationPolicy(),
                file_path=target,
                # Unrelated same-shape edit: content unchanged.
                file_content=content,
                file_exists_before=True,
                file_content_before=content,
            )
            findings = _run_edit(context)
            assert findings, f"{name} should still report drift"
            assert all(f.severity is Severity.ADVISE for f in findings), name

    def test_no_rules_files_produces_no_findings(self, tmp_path: Path) -> None:
        context = sweep_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            corpus=DocCorpus(project_root=tmp_path, documents={}),
        )
        assert _run_sweep(context) == []

    def test_reports_over_budget_body_as_advise(self, tmp_path: Path) -> None:
        long_body = _FRONTMATTER + "# T\n\n" + "\n".join(f"line {i}" for i in range(30)) + "\n"
        _rules_path(tmp_path, "long.md").write_text(long_body)
        context = sweep_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            corpus=DocCorpus(project_root=tmp_path, documents={}),
        )
        findings = _run_sweep(context)
        assert len(findings) == 1
        assert "budget" in findings[0].message.lower()

    def test_unreadable_file_is_skipped_not_fatal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """N5 (Plan 00287): an unreadable file must not abort the whole
        SessionStart sweep."""
        target = _rules_path(tmp_path, "unreadable.md")
        target.write_text(_FRONTMATTER + "```\nfenced\n```\n")

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
            policy=DocumentationPolicy(),
            corpus=DocCorpus(project_root=tmp_path, documents={}),
        )
        assert _run_sweep(context) == []

    def test_a_directory_matching_the_glob_is_skipped(self, tmp_path: Path) -> None:
        rules_dir = tmp_path / ".claude" / "rules"
        (rules_dir / "not-a-file.md").mkdir(parents=True)
        context = sweep_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            corpus=DocCorpus(project_root=tmp_path, documents={}),
        )
        assert _run_sweep(context) == []
