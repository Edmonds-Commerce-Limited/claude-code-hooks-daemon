"""Tests for the shared literal link-resolution rule.

Plan 00441, from ledger 00422 N5 row (l). Docs QA and plan QA both ask "does
this markdown link point at a file that exists", and answered it differently:
docs QA accepted a link written from the repository root as well as one written
relative to the file, plan QA only the latter. The rule lives in one place now,
so the two cannot drift again.

Containment is the part that is easy to lose in a move: a link target is
AUTHORED text, so a plain existence check over `../../../etc/passwd` is an
oracle about the host filesystem rather than about this repository.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.link_resolution import link_resolves_literally


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A small tree: `docs/Guide.md`, and `Top.md` at the root."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "Guide.md").write_text("# guide\n")
    (tmp_path / "Top.md").write_text("# top\n")
    return tmp_path


class TestRelativeToTheDocument:
    def test_a_sibling_resolves(self, repo: Path) -> None:
        assert link_resolves_literally(repo, repo / "docs", "Guide.md")

    def test_a_parent_hop_resolves(self, repo: Path) -> None:
        assert link_resolves_literally(repo, repo / "docs", "../Top.md")

    def test_a_missing_sibling_does_not(self, repo: Path) -> None:
        assert not link_resolves_literally(repo, repo / "docs", "Nope.md")


class TestRelativeToTheRepositoryRoot:
    """The fallback plan QA was missing."""

    def test_a_root_relative_path_resolves(self, repo: Path) -> None:
        assert link_resolves_literally(repo, repo / "docs", "docs/Guide.md")

    def test_a_root_relative_path_that_is_absent_does_not(self, repo: Path) -> None:
        assert not link_resolves_literally(repo, repo / "docs", "docs/Nope.md")


class TestALeadingSlash:
    """Ambiguous between an absolute path and GitHub-style root-relative."""

    def test_the_literal_absolute_path_is_tried_first(self, repo: Path) -> None:
        assert link_resolves_literally(repo, repo / "docs", f"{repo}/Top.md")

    def test_a_github_style_root_relative_path_resolves(self, repo: Path) -> None:
        assert link_resolves_literally(repo, repo / "docs", "/Top.md")


class TestItIsNotAnExistenceOracle:
    def test_a_path_escaping_the_repository_does_not_resolve(self, repo: Path) -> None:
        """Even though /etc/passwd exists on the host running this."""
        assert not link_resolves_literally(repo, repo / "docs", "../../../../../../etc/passwd")

    def test_an_absolute_host_path_does_not_resolve(self, repo: Path) -> None:
        assert not link_resolves_literally(repo, repo / "docs", "/etc/passwd")


class TestFragmentsAndEmptyTargets:
    def test_a_fragment_is_stripped_before_the_test(self, repo: Path) -> None:
        assert link_resolves_literally(repo, repo / "docs", "Guide.md#a-heading")

    def test_a_bare_fragment_is_treated_as_resolving(self, repo: Path) -> None:
        """An in-page anchor names no file, so there is no file to be missing."""
        assert link_resolves_literally(repo, repo / "docs", "#a-heading")


class TestNoSourceDirectory:
    def test_root_relative_still_works_without_one(self, repo: Path) -> None:
        """An EDIT stage may have content but no path on disk yet."""
        assert link_resolves_literally(repo, None, "docs/Guide.md")

    def test_a_document_relative_link_cannot_resolve_without_one(self, repo: Path) -> None:
        assert not link_resolves_literally(repo, None, "Guide.md")
