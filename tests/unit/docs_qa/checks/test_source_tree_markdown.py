"""Tests for check ``source-tree-markdown`` (Plan 00288, Task 5.1)."""

from pathlib import Path

from claude_code_hooks_daemon.core.project_layout import ProjectLayout
from claude_code_hooks_daemon.docs_qa.checks.source_tree_markdown import CHECK_ID, CHECKS
from claude_code_hooks_daemon.docs_qa.context import sweep_context
from claude_code_hooks_daemon.docs_qa.corpus import DocCorpus
from claude_code_hooks_daemon.docs_qa.policy import (
    DocumentationPolicy,
    DocumentationQaPolicy,
    GeneratedDocEntry,
)
from claude_code_hooks_daemon.docs_qa.types import CheckContext, CheckStage, Finding
from claude_code_hooks_daemon.utils.vendor_paths import VendorScope

_EMPTY_LAYOUT = ProjectLayout(
    source_dirs=(),
    test_dirs=(),
    config_dirs=("config",),
    vendor_dirs=frozenset(),
    agent_docs_dir="CLAUDE",
    human_docs_dir="docs",
    plan_dir="CLAUDE/Plan",
    plan_archive_dirs=(),
)


def _layout(*, source_dirs: tuple[str, ...] = (), test_dirs: tuple[str, ...] = ()) -> ProjectLayout:
    return ProjectLayout(
        source_dirs=source_dirs,
        test_dirs=test_dirs,
        config_dirs=("config",),
        vendor_dirs=frozenset({"node_modules", "vendor"}),
        agent_docs_dir="CLAUDE",
        human_docs_dir="docs",
        plan_dir="CLAUDE/Plan",
        plan_archive_dirs=(),
    )


def _run_sweep(context: CheckContext) -> list[Finding]:
    for spec in CHECKS:
        if spec.stage is CheckStage.SWEEP:
            return spec.run(context)
    raise AssertionError("no SWEEP check registered")


def _context(
    project_root: Path,
    layout: ProjectLayout | None,
    policy: DocumentationPolicy | None = None,
) -> CheckContext:
    return sweep_context(
        project_root=project_root,
        policy=policy or DocumentationPolicy(),
        corpus=DocCorpus(project_root=project_root),
        layout=layout,
    )


class TestRegistration:
    def test_registers_sweep_only(self) -> None:
        stages = {spec.stage for spec in CHECKS}
        assert stages == {CheckStage.SWEEP}
        assert all(spec.check_id == CHECK_ID for spec in CHECKS)


class TestNoLayoutSilence:
    def test_no_layout_is_silent(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "NOTES.md").write_text("notes")
        context = _context(tmp_path, layout=None)
        assert _run_sweep(context) == []

    def test_empty_layout_lists_is_silent(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "NOTES.md").write_text("notes")
        context = _context(tmp_path, layout=_EMPTY_LAYOUT)
        assert _run_sweep(context) == []


class TestFlaggedMarkdown:
    def test_plain_markdown_under_source_dir_is_flagged(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "pkg").mkdir(parents=True)
        (tmp_path / "src" / "pkg" / "NOTES.md").write_text("notes")
        context = _context(tmp_path, layout=_layout(source_dirs=("src",)))
        findings = _run_sweep(context)
        assert len(findings) == 1
        assert findings[0].check_id == CHECK_ID
        assert findings[0].path == "src/pkg/NOTES.md"
        assert "src/pkg/NOTES.md" in findings[0].message
        assert "routing" in findings[0].remediation

    def test_plain_markdown_under_test_dir_is_flagged(self, tmp_path: Path) -> None:
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "PLAN.md").write_text("notes")
        context = _context(tmp_path, layout=_layout(test_dirs=("tests",)))
        findings = _run_sweep(context)
        assert [f.path for f in findings] == ["tests/PLAN.md"]


class TestAllowedInPlace:
    def test_claude_md_is_allowed(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "pkg").mkdir(parents=True)
        (tmp_path / "src" / "pkg" / "CLAUDE.md").write_text("routing doc")
        context = _context(tmp_path, layout=_layout(source_dirs=("src",)))
        assert _run_sweep(context) == []

    def test_readme_md_is_allowed(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "pkg").mkdir(parents=True)
        (tmp_path / "src" / "pkg" / "README.md").write_text("package readme")
        context = _context(tmp_path, layout=_layout(source_dirs=("src",)))
        assert _run_sweep(context) == []

    def test_fixture_dir_markdown_is_allowed(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "tests" / "fixtures").mkdir(parents=True)
        (tmp_path / "src" / "tests" / "fixtures" / "SAMPLE.md").write_text("fixture data")
        context = _context(tmp_path, layout=_layout(source_dirs=("src",)))
        assert _run_sweep(context) == []

    def test_dunder_fixtures_dir_markdown_is_allowed(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "__fixtures__").mkdir(parents=True)
        (tmp_path / "src" / "__fixtures__" / "SAMPLE.md").write_text("fixture data")
        context = _context(tmp_path, layout=_layout(source_dirs=("src",)))
        assert _run_sweep(context) == []

    def test_generated_manifest_markdown_is_allowed(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "pkg").mkdir(parents=True)
        (tmp_path / "src" / "pkg" / "GENERATED.md").write_text("generated")
        policy = DocumentationPolicy(
            qa=DocumentationQaPolicy(
                generated_docs=(GeneratedDocEntry(glob="src/pkg/GENERATED.md", generator="gen"),),
            ),
        )
        context = _context(tmp_path, layout=_layout(source_dirs=("src",)), policy=policy)
        assert _run_sweep(context) == []

    def test_outside_declared_layout_is_not_flagged(self, tmp_path: Path) -> None:
        (tmp_path / "other" / "pkg").mkdir(parents=True)
        (tmp_path / "other" / "pkg" / "NOTES.md").write_text("notes")
        context = _context(tmp_path, layout=_layout(source_dirs=("src",)))
        assert _run_sweep(context) == []


class TestScopeExcludeGlobs:
    def test_scope_excluded_path_is_not_flagged(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "pkg" / "skills").mkdir(parents=True)
        (tmp_path / "src" / "pkg" / "skills" / "SKILL.md").write_text("shipped payload")
        policy = DocumentationPolicy(
            qa=DocumentationQaPolicy(scope_exclude_globs=("src/pkg/skills/**",)),
        )
        context = _context(tmp_path, layout=_layout(source_dirs=("src",)), policy=policy)
        assert _run_sweep(context) == []

    def test_non_matching_scope_exclude_still_flags(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "pkg").mkdir(parents=True)
        (tmp_path / "src" / "pkg" / "NOTES.md").write_text("notes")
        policy = DocumentationPolicy(
            qa=DocumentationQaPolicy(scope_exclude_globs=("src/other/**",)),
        )
        context = _context(tmp_path, layout=_layout(source_dirs=("src",)), policy=policy)
        assert [f.path for f in _run_sweep(context)] == ["src/pkg/NOTES.md"]


class TestDeclaredVendorDirsArePruned:
    """Plan 00331: this check walks the tree itself, so it needs the
    configurable vendor set too -- the sibling of the same gap in
    ``module_doc_budget``.

    It is the sharper case of the two, because the walk exclusion here was
    doubly stale: the check already RECEIVES a ``ProjectLayout`` (it must, to
    know which dirs are source/test), and still pruned on a module-scope
    frozenset built from the built-in names. A project could therefore
    declare ``roles`` as vendored, watch this check consult its layout, and
    still get a finding from inside the tree it had declared.
    """

    def _vendored_source_markdown(self, root: Path) -> None:
        vendored = root / "src" / "roles" / "lts.vault-scripts"
        vendored.mkdir(parents=True)
        (vendored / "NOTES.md").write_text("vendored notes")

    def test_a_declared_vendor_dir_is_not_reported(self, tmp_path: Path) -> None:
        self._vendored_source_markdown(tmp_path)
        layout = ProjectLayout(
            source_dirs=("src",),
            test_dirs=(),
            config_dirs=("config",),
            vendor_dirs=frozenset({"node_modules", "vendor", "roles"}),
            agent_docs_dir="CLAUDE",
            human_docs_dir="docs",
            plan_dir="CLAUDE/Plan",
            plan_archive_dirs=(),
        )
        policy = DocumentationPolicy(vendor_scopes=(VendorScope(vendor_dirs=layout.vendor_dirs),))
        assert _run_sweep(_context(tmp_path, layout=layout, policy=policy)) == []

    def test_an_undeclared_dir_of_that_name_is_still_reported(self, tmp_path: Path) -> None:
        """The skip must come from the declaration, not from the name."""
        self._vendored_source_markdown(tmp_path)
        context = _context(tmp_path, layout=_layout(source_dirs=("src",)))
        assert [f.path for f in _run_sweep(context)] == ["src/roles/lts.vault-scripts/NOTES.md"]


class TestVendorExceptionsSurviveThePrune:
    """Plan 00331 Phase 3, the sibling walker.

    Same prune hazard as `module_doc_budget`: this check removes vendored
    directories from `os.walk` in place, so an exception beneath one is
    unreachable unless the prune asks first.
    """

    _EXCEPTION = ("src/roles/ours/**",)

    def _layout_with_exception(self) -> ProjectLayout:
        return ProjectLayout(
            source_dirs=("src",),
            test_dirs=(),
            config_dirs=("config",),
            vendor_dirs=frozenset({"node_modules", "vendor", "roles"}),
            agent_docs_dir="CLAUDE",
            human_docs_dir="docs",
            plan_dir="CLAUDE/Plan",
            plan_archive_dirs=(),
            vendor_exceptions=self._EXCEPTION,
        )

    def _write_two_roles(self, root: Path) -> None:
        for owner in ("ours", "theirs"):
            notes = root / "src" / "roles" / owner / "NOTES.md"
            notes.parent.mkdir(parents=True)
            notes.write_text("notes")

    def test_the_excepted_tree_is_reported_and_its_neighbour_is_not(self, tmp_path: Path) -> None:
        self._write_two_roles(tmp_path)
        layout = self._layout_with_exception()
        policy = DocumentationPolicy(
            vendor_scopes=(
                VendorScope(
                    vendor_dirs=layout.vendor_dirs, vendor_exceptions=layout.vendor_exceptions
                ),
            )
        )
        findings = _run_sweep(_context(tmp_path, layout=layout, policy=policy))
        assert [f.path for f in findings] == ["src/roles/ours/NOTES.md"]

    def test_without_the_exception_the_whole_tree_stays_pruned(self, tmp_path: Path) -> None:
        """The discriminating half: same tree, same vendor_dirs, no exception."""
        self._write_two_roles(tmp_path)
        layout = self._layout_with_exception()
        policy = DocumentationPolicy(vendor_scopes=(VendorScope(vendor_dirs=layout.vendor_dirs),))
        assert _run_sweep(_context(tmp_path, layout=layout, policy=policy)) == []


class TestGrandfatherAllowlist:
    def test_grandfathered_path_is_suppressed(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "pkg").mkdir(parents=True)
        (tmp_path / "src" / "pkg" / "NOTES.md").write_text("notes")
        policy = DocumentationPolicy(
            qa=DocumentationQaPolicy(grandfather_allowlist=("src/pkg/NOTES.md",)),
        )
        context = _context(tmp_path, layout=_layout(source_dirs=("src",)), policy=policy)
        assert _run_sweep(context) == []
