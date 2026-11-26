"""``git_deadline``: one wall-clock deadline over every git call made inside it (N752 review)."""

import subprocess
from pathlib import Path
from unittest import mock

from claude_code_hooks_daemon.utils.git_repo import GIT_TIMED_OUT, git_deadline, run_git


def _ok() -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["git"], 0, "", "")


class TestGitDeadline:
    def test_no_deadline_leaves_the_timeout_alone(self, tmp_path: Path) -> None:
        with mock.patch("subprocess.run", return_value=_ok()) as run:
            run_git(tmp_path, "status", timeout=5)
        assert run.call_args.kwargs["timeout"] == 5

    def test_a_call_inside_is_clamped_to_the_time_left(self, tmp_path: Path) -> None:
        with (
            mock.patch("subprocess.run", return_value=_ok()) as run,
            git_deadline(2.0, clock=lambda: 1.5),
        ):
            run_git(tmp_path, "status", timeout=5)
        assert run.call_args.kwargs["timeout"] == 0.5

    def test_a_call_with_a_smaller_limit_than_the_time_left_keeps_it(self, tmp_path: Path) -> None:
        with (
            mock.patch("subprocess.run", return_value=_ok()) as run,
            git_deadline(60.0, clock=lambda: 0.0),
        ):
            run_git(tmp_path, "status", timeout=5)
        assert run.call_args.kwargs["timeout"] == 5

    def test_an_exhausted_deadline_spawns_nothing_and_reports_a_timeout(
        self, tmp_path: Path
    ) -> None:
        with mock.patch("subprocess.run") as run, git_deadline(2.0, clock=lambda: 3.0):
            result = run_git(tmp_path, "status", timeout=5)
        run.assert_not_called()
        assert result.returncode == GIT_TIMED_OUT

    def test_the_deadline_ends_with_the_block(self, tmp_path: Path) -> None:
        with git_deadline(2.0, clock=lambda: 0.0):
            pass
        with mock.patch("subprocess.run", return_value=_ok()) as run:
            run_git(tmp_path, "status", timeout=5)
        assert run.call_args.kwargs["timeout"] == 5
