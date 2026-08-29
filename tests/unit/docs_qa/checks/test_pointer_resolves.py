"""Tests for check ``pointer-resolves`` (Plan 00284, Task 3.1a)."""

import subprocess
from pathlib import Path

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.docs_qa.checks.pointer_resolves import CHECK_ID, CHECKS, _resolves
from claude_code_hooks_daemon.docs_qa.context import edit_context, staged_context, sweep_context
from claude_code_hooks_daemon.docs_qa.corpus import DocCorpus, DocRecord
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
    def test_registers_edit_staged_and_sweep(self) -> None:
        stages = {spec.stage for spec in CHECKS}
        assert stages == {CheckStage.EDIT, CheckStage.STAGED, CheckStage.SWEEP}
        assert all(spec.check_id == CHECK_ID for spec in CHECKS)


class TestEditStageNewFile:
    def test_broken_link_in_a_brand_new_file_is_block(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "New.md",
            file_content="See [missing](Nope.md).\n",
            file_exists_before=False,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert findings[0].check_id == CHECK_ID
        assert findings[0].severity is Severity.BLOCK
        assert findings[0].path == "CLAUDE/New.md"
        assert "Nope.md" in findings[0].message

    def test_resolving_link_produces_no_finding(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "CLAUDE" / "Target.md").write_text("# target\n")
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "New.md",
            file_content="See [target](Target.md).\n",
            file_exists_before=False,
        )
        assert _run_edit(context) == []

    def test_repo_root_relative_link_resolves(self, tmp_path: Path) -> None:
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "Guide.md").write_text("# guide\n")
        (tmp_path / "CLAUDE").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "New.md",
            file_content="See [guide](/docs/Guide.md).\n",
            file_exists_before=False,
        )
        assert _run_edit(context) == []

    def test_fully_qualified_absolute_path_link_resolves(self, tmp_path: Path) -> None:
        """A link written as the project's own fully-qualified filesystem path
        (e.g. ``/workspace/CHANGELOG.md`` when ``project_root`` IS
        ``/workspace``) must resolve directly, not be mistaken for the
        repo-root-relative convention (which would double the root segment
        and report a false "does not exist").
        """
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "Target.md").write_text("# target\n")
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "New.md",
            file_content=f"See [target]({tmp_path / 'Target.md'}).\n",
            file_exists_before=False,
        )
        assert _run_edit(context) == []

    def test_anchor_is_stripped_before_existence_check(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "CLAUDE" / "Target.md").write_text("# target\n")
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "New.md",
            file_content="See [target](Target.md#some-anchor-not-checked).\n",
            file_exists_before=False,
        )
        assert _run_edit(context) == []


class TestEditStageSkips:
    def test_skips_external_urls(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "New.md",
            file_content="See [ext](https://example.com/nope).\n",
            file_exists_before=False,
        )
        assert _run_edit(context) == []

    def test_skips_mailto(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "New.md",
            file_content="Email [us](mailto:nobody@example.com).\n",
            file_exists_before=False,
        )
        assert _run_edit(context) == []

    def test_skips_pure_fragment_links(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "New.md",
            file_content="Jump to [section](#some-section).\n",
            file_exists_before=False,
        )
        assert _run_edit(context) == []

    def test_skips_placeholder_tokens(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        for placeholder in ("Plan-NNNNN.md", "vX.Y.Z.md", "{name}.md", "wild*.md", "<name>.md"):
            context = edit_context(
                project_root=tmp_path,
                policy=DocumentationPolicy(),
                file_path=tmp_path / "CLAUDE" / "New.md",
                file_content=f"See [x]({placeholder}).\n",
                file_exists_before=False,
            )
            assert _run_edit(context) == [], placeholder

    def test_out_of_scope_file_produces_no_findings(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "src" / "notes.md",
            file_content="See [missing](Nope.md).\n",
            file_exists_before=False,
        )
        assert _run_edit(context) == []


class TestEditStageOnlyNewLinksBlock:
    def test_pre_existing_broken_link_is_advise_not_block(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "Existing.md",
            file_content="Intro edit. See [missing](Nope.md).\n",
            file_exists_before=True,
            file_content_before="See [missing](Nope.md).\n",
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE

    def test_newly_added_broken_link_on_existing_file_is_block(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "Existing.md",
            file_content="See [missing](Nope.md) and [new](AlsoMissing.md).\n",
            file_exists_before=True,
            file_content_before="See [missing](Nope.md).\n",
        )
        findings = _run_edit(context)
        by_message = {f.message: f.severity for f in findings}
        nope_severity = next(sev for msg, sev in by_message.items() if "Nope.md" in msg)
        also_severity = next(sev for msg, sev in by_message.items() if "AlsoMissing.md" in msg)
        assert nope_severity is Severity.ADVISE
        assert also_severity is Severity.BLOCK


class TestGrandfatherAllowlist:
    def test_grandfathered_file_is_always_advise(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        policy = DocumentationPolicy(
            qa=DocumentationQaPolicy(grandfather_allowlist=("CLAUDE/*.md",))
        )
        context = edit_context(
            project_root=tmp_path,
            policy=policy,
            file_path=tmp_path / "CLAUDE" / "New.md",
            file_content="See [missing](Nope.md).\n",
            file_exists_before=False,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE


class TestResolvesDirect:
    def test_empty_target_after_fragment_strip_resolves(self, tmp_path: Path) -> None:
        """Defensive branch: a fragment-only value handed straight to _resolves.

        ``_run_edit``/``_run_sweep`` never reach this via ``_is_skippable``
        (which already filters ``#...``), but ``_resolves`` is exercised
        directly to pin the fallback.
        """
        assert _resolves(tmp_path, None, "#only-a-fragment") is True

    def test_fully_qualified_path_does_not_double_root(self, tmp_path: Path) -> None:
        """Regression: naive ``project_root / target.lstrip("/")`` handling
        of a leading ``/`` doubled the root segment for a target that is
        already the project's own fully-qualified path (``/workspace/x``
        under ``project_root == /workspace`` became ``/workspace/workspace/x``),
        so a real file was reported as missing.
        """
        (tmp_path / "Real.md").write_text("# real\n")
        assert _resolves(tmp_path, None, str(tmp_path / "Real.md")) is True


class TestEditStageMissingPayload:
    def test_no_file_path_produces_no_findings(self, tmp_path: Path) -> None:
        context = CheckContext(
            project_root=tmp_path, policy=DocumentationPolicy(), file_content="x"
        )
        assert _run_edit(context) == []

    def test_no_file_content_produces_no_findings(self, tmp_path: Path) -> None:
        context = CheckContext(
            project_root=tmp_path, policy=DocumentationPolicy(), file_path=tmp_path / "X.md"
        )
        assert _run_edit(context) == []


class TestStagedStage:
    def test_new_broken_link_in_a_new_file_is_block(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        (root / "CLAUDE").mkdir()
        (root / "CLAUDE" / "New.md").write_text("See [missing](Nope.md).\n")
        _git(root, "add", "-A")

        context = staged_context(project_root=root, policy=DocumentationPolicy())
        findings = _run_staged(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.BLOCK
        assert findings[0].path == "CLAUDE/New.md"

    def test_pre_existing_broken_link_is_advise(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        (root / "CLAUDE").mkdir()
        (root / "CLAUDE" / "Existing.md").write_text("See [missing](Nope.md).\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "initial")
        (root / "CLAUDE" / "Existing.md").write_text("Intro. See [missing](Nope.md).\n")
        _git(root, "add", "-A")

        context = staged_context(project_root=root, policy=DocumentationPolicy())
        findings = _run_staged(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE

    def test_clean_staged_file_produces_no_findings(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        (root / "CLAUDE").mkdir()
        (root / "CLAUDE" / "Target.md").write_text("# target\n")
        (root / "CLAUDE" / "New.md").write_text("See [target](Target.md).\n")
        _git(root, "add", "-A")

        context = staged_context(project_root=root, policy=DocumentationPolicy())
        assert _run_staged(context) == []

    def test_grandfathered_new_file_is_advise(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        (root / "CLAUDE").mkdir()
        (root / "CLAUDE" / "New.md").write_text("See [missing](Nope.md).\n")
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

    def test_skippable_target_in_staged_content_produces_no_finding(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        (root / "CLAUDE").mkdir()
        (root / "CLAUDE" / "New.md").write_text("See [ext](https://example.com/nope).\n")
        _git(root, "add", "-A")

        context = staged_context(project_root=root, policy=DocumentationPolicy())
        assert _run_staged(context) == []


class TestSweepStage:
    def test_reports_broken_links_from_the_corpus_as_advise(self, tmp_path: Path) -> None:
        corpus = DocCorpus(
            project_root=tmp_path,
            documents={
                "CLAUDE/Foo.md": DocRecord(
                    rel_path="CLAUDE/Foo.md", mtime_ns=1, size=1, links=("Missing.md",)
                )
            },
        )
        (tmp_path / "CLAUDE").mkdir()
        context = sweep_context(project_root=tmp_path, policy=DocumentationPolicy(), corpus=corpus)
        findings = _run_sweep(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE
        assert findings[0].path == "CLAUDE/Foo.md"

    def test_no_corpus_produces_no_findings(self, tmp_path: Path) -> None:
        context = sweep_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            corpus=DocCorpus(project_root=tmp_path, documents={}),
        )
        assert _run_sweep(context) == []

    def test_corpus_none_produces_no_findings(self, tmp_path: Path) -> None:
        context = CheckContext(project_root=tmp_path, policy=DocumentationPolicy())
        assert _run_sweep(context) == []

    def test_skips_skippable_links_and_resolving_links_in_the_loop(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "CLAUDE" / "Target.md").write_text("# target\n")
        corpus = DocCorpus(
            project_root=tmp_path,
            documents={
                "CLAUDE/Foo.md": DocRecord(
                    rel_path="CLAUDE/Foo.md",
                    mtime_ns=1,
                    size=1,
                    links=("#just-a-fragment", "Target.md", "Missing.md"),
                )
            },
        )
        context = sweep_context(project_root=tmp_path, policy=DocumentationPolicy(), corpus=corpus)
        findings = _run_sweep(context)
        assert len(findings) == 1
        assert "Missing.md" in findings[0].message

    def test_grandfathered_sweep_hit_still_advise(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        corpus = DocCorpus(
            project_root=tmp_path,
            documents={
                "CLAUDE/Foo.md": DocRecord(
                    rel_path="CLAUDE/Foo.md", mtime_ns=1, size=1, links=("Missing.md",)
                )
            },
        )
        policy = DocumentationPolicy(
            qa=DocumentationQaPolicy(grandfather_allowlist=("CLAUDE/*.md",))
        )
        context = sweep_context(project_root=tmp_path, policy=policy, corpus=corpus)
        findings = _run_sweep(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE
