"""Tests for check ``pointer-resolves`` (Plan 00284, Task 3.1a)."""

import subprocess
from pathlib import Path

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.docs_qa.checks.pointer_resolves import CHECK_ID, CHECKS, _resolves
from claude_code_hooks_daemon.docs_qa.context import edit_context, staged_context, sweep_context
from claude_code_hooks_daemon.docs_qa.corpus import DocCorpus, DocRecord
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy, DocumentationQaPolicy
from claude_code_hooks_daemon.docs_qa.types import CheckContext, CheckStage, Finding, Severity
from claude_code_hooks_daemon.plan_links import PlanTreeLayout


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

    def test_parent_link_resolves_from_a_directory_that_does_not_exist_yet(
        self, tmp_path: Path
    ) -> None:
        """The first document written into a NEW directory (Plan 00412).

        ``Path.exists()`` stats the path as written, so ``..`` is walked
        through the filesystem: with ``CLAUDE/Security/`` not yet on disk, the
        join could not be stat-ed at all and a link to a real file read as
        dead. A new dead link is BLOCK, so the write was denied — and no retry
        could succeed, because the directory only comes into being by the write
        being allowed. Creating the first document in a new docs directory was
        impossible if it linked to a sibling with ``../``.
        """
        (tmp_path / "CLAUDE" / "Routine").mkdir(parents=True)
        (tmp_path / "CLAUDE" / "Routine" / "Target.md").write_text("# target\n")
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "Security" / "README.md",
            file_content="See [target](../Routine/Target.md).\n",
            file_exists_before=False,
        )
        assert _run_edit(context) == []

    def test_a_genuinely_dead_parent_link_is_still_reported(self, tmp_path: Path) -> None:
        """The fix must not turn every ``../`` link into an unchecked one."""
        (tmp_path / "CLAUDE" / "Routine").mkdir(parents=True)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "Security" / "README.md",
            file_content="See [gone](../Routine/Nope.md).\n",
            file_exists_before=False,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.BLOCK

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


class TestTheResolverIsNotAnExistenceOracle:
    """Plan 00412: a link target is AUTHORED, and this check stats it.

    Found by the run 2026-001 consolidation, INSIDE the tree the
    `authored-path-stat` Detector already covers — and passing that Detector
    green, because reaching the sanctioned helper is the whole of what a
    chokepoint rule can check. `authored_path_exists` normalises but does not
    CONTAIN, so routing a site through it proves the join is lexical, not that
    the result stays in the repository.

    The leak is existence, not content: whether a finding appears tells the
    reader whether the named host path is there. Milder than the `quote_drift`
    read, and the same class.
    """

    def test_an_absolute_path_outside_the_repository_does_not_resolve(self, tmp_path: Path) -> None:
        """No `..` needed: `base / "/etc/passwd"` discards `base` entirely.

        `/etc/hostname` is chosen because it exists on this container, so a
        passing assertion means containment refused it — not that the file was
        simply absent, which would make the test vacuous.
        """
        root = tmp_path / "repo"
        root.mkdir()

        assert _resolves(root, None, "/etc/hostname") is False

    def test_a_parent_hop_out_of_the_repository_does_not_resolve(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside.md"
        outside.write_text("# outside\n")
        root = tmp_path / "repo"
        (root / "docs").mkdir(parents=True)

        assert _resolves(root, root / "docs" / "page.md", "../../outside.md") is False

    def test_the_projects_own_absolute_path_still_resolves(self, tmp_path: Path) -> None:
        """The deliberate case the leading-`/` branch exists for.

        An author writing the project's own fully-qualified path is supported,
        and containment must not take that away — `/workspace/CHANGELOG.md` is
        INSIDE `project_root` when the root really is `/workspace`. Seven of
        this repo's eight absolute link targets are exactly this shape.
        """
        (tmp_path / "Real.md").write_text("# real\n")

        assert _resolves(tmp_path, None, str(tmp_path / "Real.md")) is True

    def test_a_repo_root_relative_link_still_resolves(self, tmp_path: Path) -> None:
        """GitHub-style `/CHANGELOG.md` shorthand, the branch's other half."""
        (tmp_path / "CHANGELOG.md").write_text("# changes\n")

        assert _resolves(tmp_path, None, "/CHANGELOG.md") is True

    def test_a_parent_hop_that_stays_inside_still_resolves(self, tmp_path: Path) -> None:
        """`..` is not the hazard; leaving the repository is.

        A nested document legitimately walks up to reach a sibling tree, and
        refusing every `..` would be the over-correction that makes the check
        wrong in the common case.
        """
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "CLAUDE" / "Target.md").write_text("# target\n")
        (tmp_path / "docs").mkdir()

        assert _resolves(tmp_path, tmp_path / "docs" / "page.md", "../CLAUDE/Target.md") is True


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


def _plan_tree(root: Path) -> None:
    """A live plan, an archived plan, and a journal day-file in the live one."""
    plan_dir = root / "CLAUDE" / "Plan"
    (plan_dir / "00419-live" / "JOURNAL").mkdir(parents=True)
    (plan_dir / "00419-live" / "PLAN.md").write_text("# 419\n")
    (plan_dir / "00419-live" / "NIGGLES.md").write_text("# n\n")
    (plan_dir / "00419-live" / "JOURNAL" / "00419-Journal-26-09-16.md").write_text("# j\n")
    (plan_dir / "Completed" / "00413-done").mkdir(parents=True)
    (plan_dir / "Completed" / "00413-done" / "PLAN.md").write_text("# 413\n")


class TestArchiveAwarePlanLinks:
    """Plan 00419 N2: a link names a plan NUMBER, wherever the plan now lives.

    Archiving moves a plan folder one level deeper, so every
    ``](../00NNN-y/PLAN.md)`` it carries stops resolving on disk. The project
    has already ruled that an archived record is not rewritten and that a
    ``JOURNAL/`` day-file structurally cannot be, so a link that resolves only
    through the archive is not a dead link.
    """

    def test_a_relocated_link_is_never_reported_as_dead(self, tmp_path: Path) -> None:
        _plan_tree(tmp_path)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "PlanWorkflow.md",
            file_content="See [413](Plan/00413-done/PLAN.md).\n",
            file_exists_before=False,
        )

        findings = _run_edit(context)

        assert all("does not exist" not in f.message for f in findings)

    def test_a_relocated_link_is_never_block(self, tmp_path: Path) -> None:
        """The edit under judgement did not move the target."""
        _plan_tree(tmp_path)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "PlanWorkflow.md",
            file_content="See [413](Plan/00413-done/PLAN.md).\n",
            file_exists_before=False,
        )

        assert all(f.severity is Severity.ADVISE for f in _run_edit(context))

    def test_a_relocated_link_from_an_ordinary_doc_advises_with_the_new_path(
        self, tmp_path: Path
    ) -> None:
        _plan_tree(tmp_path)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "PlanWorkflow.md",
            file_content="See [413](Plan/00413-done/PLAN.md).\n",
            file_exists_before=False,
        )

        findings = _run_edit(context)

        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE
        assert "CLAUDE/Plan/Completed/00413-done/PLAN.md" in findings[0].remediation

    def test_an_archived_source_is_not_a_finding_at_all(self, tmp_path: Path) -> None:
        """Truth is enforced on LIVE plans, never on the historical record."""
        _plan_tree(tmp_path)
        corpus = DocCorpus(
            project_root=tmp_path,
            documents={
                "CLAUDE/Plan/Completed/00413-done/PLAN.md": DocRecord(
                    rel_path="CLAUDE/Plan/Completed/00413-done/PLAN.md",
                    mtime_ns=1,
                    size=1,
                    links=("../00419-live/PLAN.md",),
                )
            },
        )
        context = sweep_context(project_root=tmp_path, policy=DocumentationPolicy(), corpus=corpus)

        assert _run_sweep(context) == []

    def test_a_journal_dayfile_source_is_not_a_finding_at_all(self, tmp_path: Path) -> None:
        """`journal-append-only` forbids the repoint a finding would demand."""
        _plan_tree(tmp_path)
        journal = tmp_path / "CLAUDE/Plan/00419-live/JOURNAL/00419-Journal-26-09-16.md"
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=journal,
            file_content="Recorded [413](../../00413-done/PLAN.md).\n",
            file_exists_before=True,
            file_content_before="",
        )

        assert _run_edit(context) == []

    def test_a_live_plan_document_yields_to_plan_qa(self, tmp_path: Path) -> None:
        """`plan-link-resolves` reports this one, with a better remediation.

        Reporting it here as well would put one fact on two session-start
        advisories.
        """
        _plan_tree(tmp_path)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE/Plan/00419-live/PLAN.md",
            file_content="See [413](../00413-done/PLAN.md).\n",
            file_exists_before=True,
            file_content_before="",
        )

        assert _run_edit(context) == []

    def test_a_live_supporting_doc_is_still_reported_here(self, tmp_path: Path) -> None:
        """plan-QA's sweep reads PLAN.md only, so this one would be lost."""
        _plan_tree(tmp_path)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE/Plan/00419-live/NIGGLES.md",
            file_content="See [413](../00413-done/PLAN.md).\n",
            file_exists_before=True,
            file_content_before="",
        )

        findings = _run_edit(context)

        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE

    def test_a_link_to_a_plan_that_never_existed_is_still_dead(self, tmp_path: Path) -> None:
        _plan_tree(tmp_path)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "PlanWorkflow.md",
            file_content="See [gone](Plan/00999-never-was/PLAN.md).\n",
            file_exists_before=False,
        )

        findings = _run_edit(context)

        assert len(findings) == 1
        assert findings[0].severity is Severity.BLOCK
        assert "does not exist" in findings[0].message

    def test_the_sweep_reports_a_relocated_link_at_advise(self, tmp_path: Path) -> None:
        _plan_tree(tmp_path)
        corpus = DocCorpus(
            project_root=tmp_path,
            documents={
                "CLAUDE/PlanWorkflow.md": DocRecord(
                    rel_path="CLAUDE/PlanWorkflow.md",
                    mtime_ns=1,
                    size=1,
                    links=("Plan/00413-done/PLAN.md",),
                )
            },
        )
        context = sweep_context(project_root=tmp_path, policy=DocumentationPolicy(), corpus=corpus)

        findings = _run_sweep(context)

        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE
        assert "CLAUDE/Plan/Completed/00413-done/PLAN.md" in findings[0].remediation

    def test_a_renamed_archive_directory_is_honoured(self, tmp_path: Path) -> None:
        """The archive names are CONFIG; a project using `Done` is not
        silently held to `Completed`."""
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        (plan_dir / "Done" / "00413-done").mkdir(parents=True)
        (plan_dir / "Done" / "00413-done" / "PLAN.md").write_text("# 413\n")
        policy = DocumentationPolicy(
            plan_tree=PlanTreeLayout(plan_dir="CLAUDE/Plan", archive_dirs=("Done",))
        )
        context = edit_context(
            project_root=tmp_path,
            policy=policy,
            file_path=tmp_path / "CLAUDE" / "PlanWorkflow.md",
            file_content="See [413](Plan/00413-done/PLAN.md).\n",
            file_exists_before=False,
        )

        findings = _run_edit(context)

        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE


class TestOneFindingPerDistinctLink:
    """Plan 00441, from ledger 00422 N5 row (j).

    A document that names the same dead link twice has one problem, not two.
    The plan-QA twin has always collapsed repeats; this check reported one
    finding per OCCURRENCE, so a page with a link repeated five times printed
    five identical findings — and at EDIT stage that is five identical entries
    in the report that denies the write.

    The row named only the sweep. All three stages share the shape.
    """

    def test_edit_stage_reports_a_repeated_dead_link_once(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "New.md",
            file_content="See [a](Nope.md) and again [b](Nope.md) and [c](Nope.md).\n",
            file_exists_before=False,
        )

        assert len(_run_edit(context)) == 1

    def test_sweep_stage_reports_a_repeated_dead_link_once(self, tmp_path: Path) -> None:
        corpus = DocCorpus(
            project_root=tmp_path,
            documents={
                "CLAUDE/Foo.md": DocRecord(
                    rel_path="CLAUDE/Foo.md",
                    mtime_ns=1,
                    size=1,
                    links=("Missing.md", "Missing.md", "Missing.md"),
                )
            },
        )
        (tmp_path / "CLAUDE").mkdir()
        context = sweep_context(project_root=tmp_path, policy=DocumentationPolicy(), corpus=corpus)

        assert len(_run_sweep(context)) == 1

    def test_staged_stage_reports_a_repeated_dead_link_once(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        (root / "CLAUDE").mkdir()
        (root / "CLAUDE" / "New.md").write_text("[a](Nope.md) [b](Nope.md) [c](Nope.md)\n")
        _git(root, "add", "-A")

        context = staged_context(project_root=root, policy=DocumentationPolicy())

        assert len(_run_staged(context)) == 1

    def test_two_different_dead_links_are_still_two_findings(self, tmp_path: Path) -> None:
        """The control: deduping must collapse repeats, not distinct links."""
        (tmp_path / "CLAUDE").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "New.md",
            file_content="See [a](NopeOne.md) and [b](NopeTwo.md).\n",
            file_exists_before=False,
        )

        assert len(_run_edit(context)) == 2

    def test_the_surviving_finding_names_the_link(self, tmp_path: Path) -> None:
        """A collapsed report that lost the target would be worse than repeats."""
        (tmp_path / "CLAUDE").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "New.md",
            file_content="See [a](Nope.md) and [b](Nope.md).\n",
            file_exists_before=False,
        )

        assert "Nope.md" in _run_edit(context)[0].message
