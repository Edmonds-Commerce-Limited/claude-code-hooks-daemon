"""The git-backed :class:`Ancestry` oracle — Plan 00412 Task 2.4 (RED first).

:mod:`routines.intervals` keeps git out of the arithmetic on purpose, and this
is the edge where it comes back in. Everything here is about the answers git
gives that are not "yes" or "no".

The protocol's contract is that an unknown or unreachable ref **is not an
ancestor of anything**. That is what makes a diverged branch, a rebased-away
commit and a typo all resolve to ``UNRELATED`` rather than blowing up a QA
sweep — and ``UNRELATED`` is a reportable finding, where an exception out of a
sweep is just a broken sweep.

Exercised against real repositories with real commits. ``merge-base
--is-ancestor`` signals through its EXIT CODE, which no mock of a subprocess
would test.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.routines.git_ancestry import GitAncestry


def _git(repo: Path, *args: str) -> str:
    """Run a git command in ``repo`` and return its stdout, stripped."""
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=Timeout.GIT_COMMIT,
    )
    return completed.stdout.strip()


def _commit(repo: Path, name: str) -> str:
    """Create one commit in ``repo`` and return its sha."""
    (repo / name).write_text(name)
    _git(repo, "add", name)
    _git(repo, "commit", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """An initialised git repository with an identity configured."""
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "ancestry@test.invalid")
    _git(tmp_path, "config", "user.name", "Ancestry Test")
    return tmp_path


class TestOrdinaryHistory:
    """The two answers git gives happily."""

    def test_an_earlier_commit_is_an_ancestor(self, repo: Path) -> None:
        """The healthy case, and the one a gap check asks about most."""
        first = _commit(repo, "first")
        second = _commit(repo, "second")

        assert GitAncestry(repo).is_ancestor(first, second) is True

    def test_a_later_commit_is_not_an_ancestor(self, repo: Path) -> None:
        """Direction matters: this is what separates a gap from an overlap."""
        first = _commit(repo, "first")
        second = _commit(repo, "second")

        assert GitAncestry(repo).is_ancestor(second, first) is False

    def test_a_commit_is_its_own_ancestor(self, repo: Path) -> None:
        """Git's own convention, and left alone rather than "corrected".

        ``intervals.compose`` short-circuits on equality before it ever asks,
        so this answer is never load-bearing — but silently disagreeing with
        git about its own definition would be a trap for the next caller.
        """
        first = _commit(repo, "first")

        assert GitAncestry(repo).is_ancestor(first, first) is True


class TestRefsGitCannotResolve:
    """The answers that are neither yes nor no, and must not raise."""

    def test_an_unknown_ref_is_not_an_ancestor(self, repo: Path) -> None:
        """A typo or a rebased-away sha resolves to False, not an exception.

        A QA sweep that raises reports nothing at all; one that returns False
        reports UNRELATED, which is a finding someone can act on.
        """
        first = _commit(repo, "first")

        assert GitAncestry(repo).is_ancestor("deadbeefdeadbeef", first) is False

    def test_an_unknown_later_ref_is_also_false(self, repo: Path) -> None:
        """Unresolvable on either side is still just 'not an ancestor'."""
        first = _commit(repo, "first")

        assert GitAncestry(repo).is_ancestor(first, "deadbeefdeadbeef") is False

    def test_a_diverged_branch_is_not_an_ancestor(self, repo: Path) -> None:
        """The case UNRELATED exists for: neither ref precedes the other.

        Reporting this as MEETS would be the pointer bug wearing an interval's
        clothes, which is the whole reason the fourth continuity exists.
        """
        base = _commit(repo, "base")
        left = _commit(repo, "left")
        _git(repo, "checkout", "--quiet", "-b", "other", base)
        right = _commit(repo, "right")

        ancestry = GitAncestry(repo)
        assert ancestry.is_ancestor(left, right) is False
        assert ancestry.is_ancestor(right, left) is False

    def test_a_tag_resolves_like_a_commit(self, repo: Path) -> None:
        """D12 anchors runs to release TAGS, so tags must resolve."""
        first = _commit(repo, "first")
        _git(repo, "tag", "v1.0.0", first)
        second = _commit(repo, "second")

        assert GitAncestry(repo).is_ancestor("v1.0.0", second) is True


class TestNotARepository:
    """A sweep run somewhere unexpected still reports rather than crashes."""

    def test_outside_a_repository_everything_is_false(self, tmp_path: Path) -> None:
        """No history means nothing precedes anything, which is honest."""
        assert GitAncestry(tmp_path / "nowhere").is_ancestor("a", "b") is False


class TestComposesWithTheAlgebra:
    """The point of the oracle: it plugs into the pure arithmetic."""

    def test_drives_discontinuities(self, repo: Path) -> None:
        """A real gap, found through the real oracle, end to end."""
        from claude_code_hooks_daemon.routines.intervals import (
            Continuity,
            RunInterval,
            discontinuities,
        )

        first = _commit(repo, "first")
        second = _commit(repo, "second")
        third = _commit(repo, "third")

        runs = [
            RunInterval(from_ref=first, to_ref=second),
            # Starts at `third`, not `second` -- the commit between them was
            # covered by nobody.
            RunInterval(from_ref=third, to_ref=third),
        ]

        assert discontinuities(runs, GitAncestry(repo)) == [(0, Continuity.GAP)]
