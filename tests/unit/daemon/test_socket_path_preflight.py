"""A worktree's socket path is over the cap BEFORE anything is created.

`get_socket_path` already falls back to /tmp when the path exceeds the AF_UNIX
limit, and that fallback is correct at runtime — but it happens hours later,
inside a worktree nobody is watching, and the acceptance gates then report "no
live socket found under untracked/" with a remedy (restart the daemon) that
cannot work, because a restart puts the socket straight back in /tmp
(Plan 00422 N6, fault 1).

The length is a property of the BRANCH NAME, so a short name works and a
descriptive one silently does not. These two helpers let the creation path
measure the path it is about to produce, for a directory that does not exist
yet — which is why the mode cannot be sniffed from disk the way
`_get_untracked_dir` does.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.daemon.paths import (
    _UNIX_SOCKET_PATH_LIMIT,
    prospective_socket_path,
    socket_path_overflow,
)


class TestProspectiveSocketPath:
    def test_self_install_mode_uses_the_short_untracked_dir(self) -> None:
        path = prospective_socket_path(Path("/workspace/wt/branch"), self_install=True)

        assert str(path).startswith("/workspace/wt/branch/untracked/daemon")
        assert str(path).endswith(".sock")

    def test_normal_mode_nests_under_the_claude_directory(self) -> None:
        path = prospective_socket_path(Path("/workspace/wt/branch"), self_install=False)

        assert "/.claude/hooks-daemon/untracked/" in str(path)

    def test_it_answers_for_a_directory_that_does_not_exist(self) -> None:
        """The whole point: this runs BEFORE `git worktree add`."""
        missing = Path("/workspace/untracked/worktrees/not-created-yet")
        assert not missing.exists()

        path = prospective_socket_path(missing, self_install=True)

        assert str(path).startswith(str(missing))
        assert not missing.exists(), "computing a path must not create anything"


class TestSocketPathOverflow:
    def test_a_short_path_has_no_overflow(self) -> None:
        assert socket_path_overflow(Path("/w/u/daemon.sock")) == 0

    def test_a_path_exactly_at_the_limit_fits(self) -> None:
        exact = Path("/" + "a" * (_UNIX_SOCKET_PATH_LIMIT - 1))
        assert len(str(exact)) == _UNIX_SOCKET_PATH_LIMIT

        assert socket_path_overflow(exact) == 0

    def test_one_byte_over_reports_exactly_one(self) -> None:
        over = Path("/" + "a" * _UNIX_SOCKET_PATH_LIMIT)

        assert socket_path_overflow(over) == 1

    def test_it_reports_the_real_excess_for_the_measured_worktree_case(self) -> None:
        """The N6 case: a descriptive branch name pushes it over."""
        root = Path("/workspace/untracked/worktrees/worktree-issue-42-remote-docs-add-overwrite")

        overflow = socket_path_overflow(prospective_socket_path(root, self_install=True))

        assert overflow > 0, "the branch name from N6 must still be reported as over the cap"
