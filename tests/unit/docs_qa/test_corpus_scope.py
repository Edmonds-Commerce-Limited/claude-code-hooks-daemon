"""EDIT-stage scope: nested checkouts and gitignored paths are out (Issue #80).

The SWEEP already drops gitignored paths; ``is_lintable_path`` is the single
scope check for the ``docs_qa_edit`` handler and ``docs-qa --lint``, so these
cases pin that the two stages agree.
"""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.docs_qa.corpus import is_lintable_path
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy
from tests.support.git_fixtures import run_git

_MODULE_DOC = "# Module\n\nShort body.\n"


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    run_git(root, "init")
    run_git(root, "config", "user.email", "t@example.com")
    run_git(root, "config", "user.name", "T")
    (root / ".gitignore").write_text("untracked/\nignored/\n")
    return root


def _module_doc(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    doc = directory / "CLAUDE.md"
    doc.write_text(_MODULE_DOC)
    return doc


def _lintable(project: Path, doc: Path) -> bool:
    rel = str(doc.relative_to(project))
    return is_lintable_path(rel, doc, project, DocumentationPolicy())


class TestNestedCheckouts:
    def test_a_module_doc_in_a_nested_clone_is_not_linted(self, project: Path) -> None:
        clone = project / "vendor" / "other"
        run_git(project, "init", str(clone))
        assert not _lintable(project, _module_doc(clone / "pkg"))

    def test_a_module_doc_in_a_submodule_style_checkout_is_not_linted(self, project: Path) -> None:
        sub = project / "sub"
        sub.mkdir()
        (sub / ".git").write_text("gitdir: ../.git/modules/sub\n")
        assert not _lintable(project, _module_doc(sub / "pkg"))

    def test_a_module_doc_in_a_foreign_linked_worktree_is_not_linted(
        self, project: Path, tmp_path: Path
    ) -> None:
        other = tmp_path / "other"
        (other / ".git" / "worktrees").mkdir(parents=True)
        foreign = project / "scratch" / "foreign"
        foreign.mkdir(parents=True)
        (foreign / ".git").write_text(f"gitdir: {other}/.git/worktrees/foreign\n")
        assert not _lintable(project, _module_doc(foreign / "pkg"))

    def test_a_module_doc_in_this_repositorys_own_worktree_is_still_linted(
        self, project: Path
    ) -> None:
        (project / "README.md").write_text("# r\n")
        run_git(project, "add", ".gitignore", "README.md")
        run_git(project, "commit", "-m", "init")
        worktree = project / "untracked" / "worktrees" / "wt"
        run_git(project, "worktree", "add", "-b", "wt", str(worktree))
        assert _lintable(project, _module_doc(worktree / "src"))


class TestGitignoredPaths:
    def test_a_module_doc_in_a_gitignored_directory_is_not_linted(self, project: Path) -> None:
        assert not _lintable(project, _module_doc(project / "ignored" / "pkg"))

    def test_an_ordinary_module_doc_is_still_linted(self, project: Path) -> None:
        assert _lintable(project, _module_doc(project / "src"))

    def test_a_tracked_module_doc_is_still_linted(self, project: Path) -> None:
        doc = _module_doc(project / "src")
        run_git(project, "add", "src/CLAUDE.md")
        assert _lintable(project, doc)

    def test_a_project_that_is_not_a_git_repository_keeps_every_path_in_scope(
        self, tmp_path: Path
    ) -> None:
        plain = tmp_path / "plain"
        doc = _module_doc(plain / "ignored" / "pkg")
        assert is_lintable_path(str(doc.relative_to(plain)), doc, plain, DocumentationPolicy())

    def test_a_gitignored_corpus_document_is_not_linted(self, project: Path) -> None:
        (project / ".gitignore").write_text("CLAUDE/Scratch.md\n")
        doc = project / "CLAUDE" / "Scratch.md"
        doc.parent.mkdir()
        doc.write_text("# s\n")
        assert not _lintable(project, doc)

    def test_the_deliberately_gitignored_ccy_module_doc_is_still_linted(
        self, project: Path
    ) -> None:
        (project / ".claude" / "ccy").mkdir(parents=True)
        (project / ".claude" / "ccy" / ".gitignore").write_text("*\n")
        assert _lintable(project, _module_doc(project / ".claude" / "ccy"))
