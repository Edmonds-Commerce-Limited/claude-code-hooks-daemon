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


class TestGrandfatherAllowlist:
    def test_grandfathered_path_is_suppressed(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "pkg").mkdir(parents=True)
        (tmp_path / "src" / "pkg" / "NOTES.md").write_text("notes")
        policy = DocumentationPolicy(
            qa=DocumentationQaPolicy(grandfather_allowlist=("src/pkg/NOTES.md",)),
        )
        context = _context(tmp_path, layout=_layout(source_dirs=("src",)), policy=policy)
        assert _run_sweep(context) == []
