"""Tests for ``docs_qa.context`` builders (Plan 00284, Task 3.1a)."""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.docs_qa.context import edit_context, staged_context, sweep_context
from claude_code_hooks_daemon.docs_qa.corpus import DocCorpus
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy


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


class TestStagedContext:
    def test_raises_not_implemented(self, tmp_path: Path) -> None:
        with pytest.raises(NotImplementedError):
            staged_context(project_root=tmp_path, policy=DocumentationPolicy())
