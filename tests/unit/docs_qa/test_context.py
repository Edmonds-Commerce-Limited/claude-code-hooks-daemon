"""Tests for ``docs_qa.context`` builders (Plan 00284, Tasks 3.1a + 3.1e)."""

import os
import subprocess
from collections.abc import Callable, Generator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core.project_layout import ProjectLayout
from claude_code_hooks_daemon.docs_qa import corpus as corpus_module
from claude_code_hooks_daemon.docs_qa.context import edit_context, staged_context, sweep_context
from claude_code_hooks_daemon.docs_qa.corpus import DocCorpus
from claude_code_hooks_daemon.docs_qa.policy import (
    DocumentationPolicy,
    DocumentationQaPolicy,
)
from claude_code_hooks_daemon.docs_qa.runner import run_stage
from claude_code_hooks_daemon.docs_qa.types import CheckStage


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


class TestEditContext:
    def test_builds_context_with_file_payload(self, tmp_path: Path) -> None:
        policy = DocumentationPolicy()
        file_path = tmp_path / "CLAUDE" / "Foo.md"
        context = edit_context(
            project_root=tmp_path,
            policy=policy,
            file_path=file_path,
            file_content="# Foo\n",
            file_exists_before=True,
            file_content_before="# Foo (old)\n",
        )
        assert context.project_root == tmp_path
        assert context.policy is policy
        assert context.file_path == file_path
        assert context.file_content == "# Foo\n"
        assert context.file_exists_before is True
        assert context.file_content_before == "# Foo (old)\n"
        assert context.corpus is None

    def test_optional_corpus_is_attached_when_supplied(self, tmp_path: Path) -> None:
        corpus = DocCorpus(project_root=tmp_path, documents={})
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "Foo.md",
            file_content="# Foo\n",
            file_exists_before=False,
            corpus=corpus,
        )
        assert context.corpus is corpus

    def test_file_content_before_defaults_to_none(self, tmp_path: Path) -> None:
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "Foo.md",
            file_content="# Foo\n",
            file_exists_before=False,
        )
        assert context.file_content_before is None


class TestSweepContext:
    def test_builds_context_with_corpus(self, tmp_path: Path) -> None:
        policy = DocumentationPolicy()
        corpus = DocCorpus(project_root=tmp_path, documents={})
        context = sweep_context(project_root=tmp_path, policy=policy, corpus=corpus)
        assert context.project_root == tmp_path
        assert context.policy is policy
        assert context.corpus is corpus
        assert context.file_path is None
        assert context.file_content is None

    def test_markdown_paths_is_populated_from_one_walk(self, tmp_path: Path) -> None:
        """The single shared walk module-doc-budget and source-tree-markdown
        both consume (Plan 00295 Task 3.3), built once here rather than once
        per check."""
        (tmp_path / "src" / "pkg").mkdir(parents=True)
        (tmp_path / "src" / "pkg" / "NOTES.md").write_text("notes")
        (tmp_path / "CLAUDE.md").write_text("root")
        (tmp_path / "src" / "pkg" / "module.py").write_text("x = 1\n")
        corpus = DocCorpus(project_root=tmp_path, documents={})
        context = sweep_context(project_root=tmp_path, policy=DocumentationPolicy(), corpus=corpus)
        assert context.markdown_paths == ("CLAUDE.md", "src/pkg/NOTES.md")

    def test_markdown_paths_honours_configured_scope_exclusions(self, tmp_path: Path) -> None:
        (tmp_path / "infra" / "roles").mkdir(parents=True)
        (tmp_path / "infra" / "roles" / "NOTES.md").write_text("excluded")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "NOTES.md").write_text("real")
        policy = DocumentationPolicy(
            qa=DocumentationQaPolicy(scope_exclude_globs=("infra/roles/**",))
        )
        corpus = DocCorpus(project_root=tmp_path, documents={})
        context = sweep_context(project_root=tmp_path, policy=policy, corpus=corpus)
        assert context.markdown_paths == ("src/NOTES.md",)

    def test_module_doc_budget_and_source_tree_markdown_share_one_walk(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The point of Task 3.3: a sweep that runs BOTH checks performs the
        markdown-path ``os.walk`` exactly once, not once per check."""
        (tmp_path / "src" / "pkg").mkdir(parents=True)
        (tmp_path / "src" / "pkg" / "NOTES.md").write_text("notes")
        (tmp_path / "CLAUDE.md").write_text("root doc")

        layout = ProjectLayout(
            source_dirs=("src",),
            test_dirs=(),
            config_dirs=(),
            vendor_dirs=frozenset(),
            agent_docs_dir="CLAUDE",
            human_docs_dir="docs",
            plan_dir="CLAUDE/Plan",
            plan_archive_dirs=("Completed", "Cancelled"),
        )
        corpus = DocCorpus(project_root=tmp_path, documents={})

        walk_calls = 0
        real_walk = os.walk

        def _counting_walk(
            top: str,
            topdown: bool = True,
            onerror: Callable[[OSError], object] | None = None,
            followlinks: bool = False,
        ) -> Generator[tuple[str, list[str], list[str]], None, None]:
            nonlocal walk_calls
            walk_calls += 1
            yield from real_walk(top, topdown=topdown, onerror=onerror, followlinks=followlinks)

        monkeypatch.setattr(corpus_module.os, "walk", _counting_walk)

        context = sweep_context(
            project_root=tmp_path, policy=DocumentationPolicy(), corpus=corpus, layout=layout
        )
        findings = run_stage(CheckStage.SWEEP, context)

        assert walk_calls == 1
        assert {finding.path for finding in findings} == {"src/pkg/NOTES.md"}


class TestStagedContext:
    def test_populates_staged_documents_with_staged_content(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        (root / "CLAUDE").mkdir()
        (root / "CLAUDE" / "Foo.md").write_text("# Foo v1\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "initial")
        (root / "CLAUDE" / "Foo.md").write_text("# Foo v2\n")
        _git(root, "add", "-A")

        context = staged_context(project_root=root, policy=DocumentationPolicy())
        assert context.staged_documents == {"CLAUDE/Foo.md": "# Foo v2\n"}
        assert context.gitfacts is not None

    def test_deleted_staged_file_carries_no_content(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        (root / "CLAUDE").mkdir()
        (root / "CLAUDE" / "Foo.md").write_text("# Foo\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "initial")
        (root / "CLAUDE" / "Foo.md").unlink()
        _git(root, "add", "-A")

        context = staged_context(project_root=root, policy=DocumentationPolicy())
        assert context.staged_documents == {}

    def test_non_markdown_staged_files_are_excluded(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        (root / "src").mkdir()
        (root / "src" / "module.py").write_text("x = 1\n")
        _git(root, "add", "-A")

        context = staged_context(project_root=root, policy=DocumentationPolicy())
        assert context.staged_documents == {}

    def test_commit_message_is_threaded_through(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        context = staged_context(
            project_root=root, policy=DocumentationPolicy(), commit_message="Plan 00284: x"
        )
        assert context.commit_message == "Plan 00284: x"

    def test_pathspecs_scope_the_staged_view(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        (root / "CLAUDE").mkdir()
        (root / "CLAUDE" / "A.md").write_text("# A\n")
        (root / "CLAUDE" / "B.md").write_text("# B\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "initial")
        (root / "CLAUDE" / "A.md").write_text("# A v2\n")
        (root / "CLAUDE" / "B.md").write_text("# B v2\n")
        _git(root, "add", "-A")

        context = staged_context(
            project_root=root, policy=DocumentationPolicy(), pathspecs=["CLAUDE/A.md"]
        )
        assert context.staged_documents == {"CLAUDE/A.md": "# A v2\n"}

    def test_pathspecs_mode_reads_working_tree_not_the_stale_index(self, tmp_path: Path) -> None:
        """A pathspec'd commit ships the WORKING TREE, even if never `git add`ed."""
        root = tmp_path / "repo"
        _init_repo(root)
        (root / "CLAUDE").mkdir()
        target = root / "CLAUDE" / "A.md"
        target.write_text("# A v1\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "initial")
        target.write_text("# A v2 unstaged\n")  # deliberately NOT git add'ed

        context = staged_context(
            project_root=root, policy=DocumentationPolicy(), pathspecs=["CLAUDE/A.md"]
        )
        assert context.staged_documents == {"CLAUDE/A.md": "# A v2 unstaged\n"}

    def test_pathspecs_mode_unreadable_file_is_skipped(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        root = tmp_path / "repo"
        _init_repo(root)
        (root / "CLAUDE").mkdir()
        target = root / "CLAUDE" / "A.md"
        target.write_text("# A v1\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "initial")
        target.write_text("# A v2\n")

        with patch.object(Path, "read_text", side_effect=OSError("permission denied")):
            context = staged_context(
                project_root=root, policy=DocumentationPolicy(), pathspecs=["CLAUDE/A.md"]
            )
        assert context.staged_documents == {}


def _layout() -> ProjectLayout:
    return ProjectLayout(
        source_dirs=(),
        test_dirs=(),
        config_dirs=(),
        vendor_dirs=frozenset(),
        agent_docs_dir="CLAUDE",
        human_docs_dir="docs",
        plan_dir="CLAUDE/Plan",
        plan_archive_dirs=("Completed", "Cancelled"),
    )


class TestLayoutThreading:
    """Plan 00288: `layout` is threaded through onto the context, unchanged."""

    def test_edit_context_carries_layout(self, tmp_path: Path) -> None:
        layout = _layout()
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "Foo.md",
            file_content="# Foo\n",
            file_exists_before=False,
            layout=layout,
        )
        assert context.layout is layout

    def test_sweep_context_carries_layout(self, tmp_path: Path) -> None:
        layout = _layout()
        corpus = DocCorpus(project_root=tmp_path, documents={})
        context = sweep_context(
            project_root=tmp_path, policy=DocumentationPolicy(), corpus=corpus, layout=layout
        )
        assert context.layout is layout

    def test_staged_context_carries_layout(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        layout = _layout()
        context = staged_context(project_root=root, policy=DocumentationPolicy(), layout=layout)
        assert context.layout is layout

    def test_layout_defaults_to_none(self, tmp_path: Path) -> None:
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "Foo.md",
            file_content="# Foo\n",
            file_exists_before=False,
        )
        assert context.layout is None


class TestProjectExcludePaths:
    """Plan 00362 Task 2.9: ``policy.exclude_paths`` (the project-wide
    ``daemon.exclude_paths``) is honoured by the SWEEP walk and the STAGED view."""

    def test_sweep_markdown_paths_drop_excluded_files(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "fixtures").mkdir(parents=True)
        (tmp_path / "src" / "NOTES.md").write_text("# notes\n")
        (tmp_path / "src" / "fixtures" / "BAD.md").write_text("# bad\n")
        corpus = DocCorpus(project_root=tmp_path, documents={})
        policy = DocumentationPolicy(exclude_paths=("src/fixtures/**",))

        context = sweep_context(project_root=tmp_path, policy=policy, corpus=corpus)

        assert context.markdown_paths == ("src/NOTES.md",)

    def test_staged_documents_drop_excluded_files(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        (root / "CLAUDE" / "fixtures").mkdir(parents=True)
        (root / "CLAUDE" / "A.md").write_text("# a\n")
        (root / "CLAUDE" / "fixtures" / "B.md").write_text("# b\n")
        _git(root, "add", "-A")
        policy = DocumentationPolicy(exclude_paths=("CLAUDE/fixtures/**",))

        context = staged_context(project_root=root, policy=policy)

        assert context.staged_documents == {"CLAUDE/A.md": "# a\n"}
