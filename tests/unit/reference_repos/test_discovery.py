"""Discovery of governed reference repositories (Plan 00401 Task 1.1).

The convention this serves: reference clones are tracked under
``untracked/repos/`` and an agent reads them as though they were current. Before
anything can report on their freshness, something has to decide WHICH checkouts
are governed — and get the boundaries right, because both failure directions are
silent.

Enumerating too little leaves a stale repo ungoverned and the agent reasons from
a weeks-old checkout. Enumerating too much walks into a checkout's own history,
its vendored dependencies, or a sibling tree that is nobody's reference repo,
and the resulting report is noise a reader learns to skip.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.reference_repos import discovery
from claude_code_hooks_daemon.reference_repos.discovery import discover_reference_repos


def _make_checkout(path: Path) -> Path:
    """Create a directory that looks like a git checkout."""
    (path / ".git").mkdir(parents=True)
    return path


def _make_worktree_checkout(path: Path, gitdir: str = "/elsewhere/.git/worktrees/w") -> Path:
    """Create a checkout whose ``.git`` is a FILE, as worktrees and submodules use."""
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    return path


class TestFindingCheckouts:
    """A governed repo is a directory carrying a ``.git`` entry."""

    def test_a_checkout_directly_under_the_root_is_found(self, tmp_path: Path) -> None:
        root = tmp_path / "repos"
        _make_checkout(root / "alpha")

        assert discover_reference_repos([root]) == [root / "alpha"]

    def test_a_checkout_nested_below_the_root_is_found(self, tmp_path: Path) -> None:
        """Roots are organised by owner in practice (``repos/anthropic/sdk``)."""
        root = tmp_path / "repos"
        _make_checkout(root / "anthropic" / "sdk")

        assert discover_reference_repos([root]) == [root / "anthropic" / "sdk"]

    def test_a_git_FILE_counts_as_a_checkout(self, tmp_path: Path) -> None:
        """A worktree or submodule has a ``.git`` file, not a directory.

        Testing ``.git``'s existence rather than its type keeps those governed;
        an ``is_dir()`` check would silently skip exactly the checkouts a
        multi-worktree workflow produces.
        """
        root = tmp_path / "repos"
        _make_worktree_checkout(root / "worktree-clone")

        assert discover_reference_repos([root]) == [root / "worktree-clone"]

    def test_several_checkouts_are_returned_in_a_stable_order(self, tmp_path: Path) -> None:
        """Order is sorted, so a report and its diff do not churn between runs."""
        root = tmp_path / "repos"
        for name in ("zulu", "alpha", "mike"):
            _make_checkout(root / name)

        assert discover_reference_repos([root]) == [
            root / "alpha",
            root / "mike",
            root / "zulu",
        ]

    def test_directories_that_are_not_checkouts_are_ignored(self, tmp_path: Path) -> None:
        root = tmp_path / "repos"
        (root / "notes").mkdir(parents=True)
        (root / "notes" / "README.md").write_text("hi", encoding="utf-8")
        _make_checkout(root / "real")

        assert discover_reference_repos([root]) == [root / "real"]

    def test_multiple_roots_are_all_swept(self, tmp_path: Path) -> None:
        first = tmp_path / "repos"
        second = tmp_path / "vendor"
        _make_checkout(first / "alpha")
        _make_checkout(second / "beta")

        assert discover_reference_repos([first, second]) == [
            first / "alpha",
            second / "beta",
        ]


class TestNotDescendingIntoACheckout:
    """Once a checkout is found, its interior is not searched."""

    def test_a_nested_repo_inside_a_checkout_is_not_returned_separately(
        self, tmp_path: Path
    ) -> None:
        """A submodule is part of its parent, not an independently governed repo.

        Returning it separately would report the same staleness twice and invite
        a pull of a submodule that its parent pins deliberately.
        """
        root = tmp_path / "repos"
        outer = _make_checkout(root / "outer")
        _make_checkout(outer / "vendor" / "inner")

        assert discover_reference_repos([root]) == [outer]

    def test_the_git_directory_itself_is_never_walked(self, tmp_path: Path) -> None:
        """``.git`` holds paths that can look like checkouts (worktree admin dirs)."""
        root = tmp_path / "repos"
        outer = _make_checkout(root / "outer")
        (outer / ".git" / "worktrees" / "w").mkdir(parents=True)
        (outer / ".git" / "worktrees" / "w" / ".git").mkdir()

        assert discover_reference_repos([root]) == [outer]


class TestRootsThatCannotBeSwept:
    """A root that is absent or unusable is skipped, never raised."""

    def test_a_missing_root_yields_nothing_and_does_not_raise(self, tmp_path: Path) -> None:
        """Zero config is the default, so the default root usually does not exist.

        Raising here would make the handler fail closed in every project that has
        not adopted the convention.
        """
        assert discover_reference_repos([tmp_path / "absent"]) == []

    def test_a_root_that_is_a_file_yields_nothing(self, tmp_path: Path) -> None:
        not_a_dir = tmp_path / "repos"
        not_a_dir.write_text("not a directory", encoding="utf-8")

        assert discover_reference_repos([not_a_dir]) == []

    def test_no_roots_at_all_yields_nothing(self) -> None:
        assert discover_reference_repos([]) == []

    def test_an_unreadable_subtree_does_not_abort_the_whole_sweep(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One bad directory must not cost the report every other repo.

        The failure is forced by patching ``os.scandir`` rather than by
        ``chmod``: this suite runs as root in a container, where mode ``000``
        denies nothing, so a permissions-based version of this test would pass
        green without ever reaching the error path it claims to cover.
        """
        root = tmp_path / "repos"
        _make_checkout(root / "alpha")
        blocked = root / "blocked"
        blocked.mkdir()

        real_scandir = discovery.os.scandir

        def _scandir(path: Any) -> Any:
            if Path(str(path)) == blocked:
                raise PermissionError(f"cannot read {blocked}")
            return real_scandir(path)

        monkeypatch.setattr(discovery.os, "scandir", _scandir)

        assert discover_reference_repos([root]) == [root / "alpha"]

    def test_an_entry_whose_type_cannot_be_determined_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``is_dir()`` stats the entry, and that stat can fail on its own.

        A racing deletion or a dangling mount makes this fire in the field. The
        sweep should lose that one entry, not the run.
        """
        root = tmp_path / "repos"
        _make_checkout(root / "alpha")

        class _UnstattableEntry:
            name = "unstattable"
            path = str(root / "unstattable")

            def is_dir(self, *, follow_symlinks: bool = True) -> bool:
                raise OSError("stat failed")

        real_scandir = discovery.os.scandir

        def _scandir(path: Any) -> Any:
            if Path(str(path)) == root:
                return [*real_scandir(path), _UnstattableEntry()]
            return real_scandir(path)

        monkeypatch.setattr(discovery.os, "scandir", _scandir)

        assert discover_reference_repos([root]) == [root / "alpha"]

    def test_a_root_that_is_itself_a_checkout_does_not_walk_its_git_dir(
        self, tmp_path: Path
    ) -> None:
        """A root pointed at a repository must not enumerate git's bookkeeping.

        ``.git`` contains directories that look like checkouts — a worktree
        admin dir carries its own ``.git`` — so descending would invent governed
        repos out of git internals. The root itself is never returned either:
        repos are discovered UNDER a root, not as one.
        """
        root = _make_checkout(tmp_path / "repos")
        (root / ".git" / "worktrees" / "w").mkdir(parents=True)
        (root / ".git" / "worktrees" / "w" / ".git").mkdir()
        _make_checkout(root / "alpha")

        assert discover_reference_repos([root]) == [root / "alpha"]


class TestExclusions:
    """Exclude globs use the project's single glob dialect."""

    def test_an_excluded_checkout_is_not_returned(self, tmp_path: Path) -> None:
        root = tmp_path / "repos"
        _make_checkout(root / "alpha")
        _make_checkout(root / "scratch")

        found = discover_reference_repos(
            [root], exclude_globs=["**/scratch"], project_root=tmp_path
        )

        assert found == [root / "alpha"]

    def test_no_exclude_globs_excludes_nothing(self, tmp_path: Path) -> None:
        root = tmp_path / "repos"
        _make_checkout(root / "alpha")

        assert discover_reference_repos([root], exclude_globs=[]) == [root / "alpha"]


class TestDepthBound:
    """The sweep is bounded, because a root can point anywhere."""

    def test_a_checkout_deeper_than_the_bound_is_not_found(self, tmp_path: Path) -> None:
        """A misconfigured root must not turn into an unbounded filesystem walk.

        The bound is what stops ``roots: ["/"]`` from pinning the machine —
        the same failure the daemon's own root-recursion guard exists to prevent.
        """
        root = tmp_path / "repos"
        _make_checkout(root / "a" / "b" / "c" / "d" / "e" / "deep")

        assert discover_reference_repos([root], max_depth=3) == []

    def test_a_checkout_at_the_bound_is_found(self, tmp_path: Path) -> None:
        root = tmp_path / "repos"
        _make_checkout(root / "a" / "b" / "at-limit")

        assert discover_reference_repos([root], max_depth=3) == [root / "a" / "b" / "at-limit"]

    @pytest.mark.parametrize("bad_depth", [0, -1])
    def test_a_non_positive_depth_finds_nothing_rather_than_everything(
        self, tmp_path: Path, bad_depth: int
    ) -> None:
        """A nonsense bound must fail closed, not degrade into an unbounded walk."""
        root = tmp_path / "repos"
        _make_checkout(root / "alpha")

        assert discover_reference_repos([root], max_depth=bad_depth) == []
