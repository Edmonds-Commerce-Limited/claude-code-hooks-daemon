"""``git_deadline``: one wall-clock deadline over every git call made inside it (N752 review)."""

import subprocess
from pathlib import Path
from unittest import mock

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.git_repo import GIT_TIMED_OUT, git_deadline, run_git

#: A call's own limit; every deadline below is chosen against it.
_LIMIT = Timeout.GIT_CONTEXT


def _ok() -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["git"], 0, "", "")


class TestGitDeadline:
    def test_no_deadline_leaves_the_timeout_alone(self, tmp_path: Path) -> None:
        with mock.patch("subprocess.run", return_value=_ok()) as run:
            run_git(tmp_path, "status", timeout=_LIMIT)
        assert run.call_args.kwargs["timeout"] == _LIMIT

    def test_a_call_inside_is_clamped_to_the_time_left(self, tmp_path: Path) -> None:
        with (
            mock.patch("subprocess.run", return_value=_ok()) as run,
            git_deadline(2.0, clock=lambda: 1.5),
        ):
            run_git(tmp_path, "status", timeout=_LIMIT)
        assert run.call_args.kwargs["timeout"] == 0.5

    def test_a_call_with_a_smaller_limit_than_the_time_left_keeps_it(self, tmp_path: Path) -> None:
        with (
            mock.patch("subprocess.run", return_value=_ok()) as run,
            git_deadline(60.0, clock=lambda: 0.0),
        ):
            run_git(tmp_path, "status", timeout=_LIMIT)
        assert run.call_args.kwargs["timeout"] == _LIMIT

    def test_an_exhausted_deadline_spawns_nothing_and_reports_a_timeout(
        self, tmp_path: Path
    ) -> None:
        with mock.patch("subprocess.run") as run, git_deadline(2.0, clock=lambda: 3.0):
            result = run_git(tmp_path, "status", timeout=_LIMIT)
        run.assert_not_called()
        assert result.returncode == GIT_TIMED_OUT

    def test_a_nested_deadline_never_widens_the_outer_one(self, tmp_path: Path) -> None:
        """An inner block asking for more time keeps the outer, earlier deadline."""

        def clock() -> float:
            return 1.5

        with (
            mock.patch("subprocess.run", return_value=_ok()) as run,
            git_deadline(2.0, clock=clock),
            git_deadline(60.0, clock=clock),
        ):
            run_git(tmp_path, "status", timeout=_LIMIT)
        assert run.call_args.kwargs["timeout"] == 0.5

    def test_a_nested_deadline_may_tighten_the_outer_one(self, tmp_path: Path) -> None:
        def clock() -> float:
            return 0.0

        with (
            mock.patch("subprocess.run", return_value=_ok()) as run,
            git_deadline(60.0, clock=clock),
            git_deadline(1.0, clock=clock),
        ):
            run_git(tmp_path, "status", timeout=_LIMIT)
        assert run.call_args.kwargs["timeout"] == 1.0

    def test_the_outer_deadline_returns_after_an_inner_block_ends(self, tmp_path: Path) -> None:
        def clock() -> float:
            return 0.0

        with git_deadline(3.0, clock=clock):
            with git_deadline(1.0, clock=clock):
                pass
            with mock.patch("subprocess.run", return_value=_ok()) as run:
                run_git(tmp_path, "status", timeout=_LIMIT)
        assert run.call_args.kwargs["timeout"] == 3.0

    def test_the_deadline_ends_with_the_block(self, tmp_path: Path) -> None:
        with git_deadline(2.0, clock=lambda: 0.0):
            pass
        with mock.patch("subprocess.run", return_value=_ok()) as run:
            run_git(tmp_path, "status", timeout=_LIMIT)
        assert run.call_args.kwargs["timeout"] == _LIMIT
