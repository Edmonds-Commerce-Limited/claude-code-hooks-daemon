"""The QA-run lock check is ADVISORY, so it must never abort the restart.

Plan 00407 N10. `_warn_if_qa_run_in_progress`'s own docstring says it warns and
never refuses, because "a refusal here would be a new way to get stuck". The
helper underneath it opened the lock file outside any `OSError` handling, and
nothing wraps the CLI's dispatch — so an unhandled exception ended
`hooks-daemon restart` with a traceback, which is a STRONGER refusal than the
one the function was written to avoid, on the daemon's most-used recovery verb.

The window is real rather than theoretical: the check does `is_file()` and then
`os.open`, so a QA run that finishes in between unlinks the file underneath it.
A lock owned by another user, or an `flock` that the filesystem does not
support, land in the same place.

Unknown must therefore degrade to "no warning", which is the only answer an
advisory can safely give when it cannot tell, and the degradation is logged
at WARNING so it is not mistaken for "no run in progress".
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon.cli import _QA_RUN_LOCK_RELPATH, _qa_run_lock_holder


def _lock_file(root: Path) -> Path:
    lock = root / _QA_RUN_LOCK_RELPATH
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("pid=4242\n", encoding="utf-8")
    return lock


class TestNothingHoldsTheLock:
    def test_an_absent_lock_file_is_not_a_held_lock(self, tmp_path: Path) -> None:
        assert _qa_run_lock_holder(tmp_path) is None

    def test_a_lock_file_nobody_holds_is_not_a_held_lock(self, tmp_path: Path) -> None:
        """A lock FILE on disk says nothing about whether a lock is HELD."""
        _lock_file(tmp_path)

        assert _qa_run_lock_holder(tmp_path) is None


class TestTheAdvisoryNeverRaises:
    def test_the_file_vanishing_between_the_check_and_the_open_is_survived(
        self, tmp_path: Path
    ) -> None:
        """The TOCTOU: the QA run finished and unlinked the lock."""
        _lock_file(tmp_path)

        with patch("claude_code_hooks_daemon.daemon.cli.os.open", side_effect=FileNotFoundError):
            assert _qa_run_lock_holder(tmp_path) is None

    def test_a_lock_owned_by_another_user_is_survived(self, tmp_path: Path) -> None:
        """It is opened O_RDWR, so another user's lock raises EACCES."""
        _lock_file(tmp_path)

        with patch("claude_code_hooks_daemon.daemon.cli.os.open", side_effect=PermissionError):
            assert _qa_run_lock_holder(tmp_path) is None

    def test_a_filesystem_that_cannot_flock_is_survived(self, tmp_path: Path) -> None:
        """NFS and overlayfs answer ENOLCK/EOPNOTSUPP rather than contending."""
        _lock_file(tmp_path)

        with patch(
            "claude_code_hooks_daemon.daemon.cli.fcntl.flock", side_effect=OSError("ENOLCK")
        ):
            assert _qa_run_lock_holder(tmp_path) is None

    def test_an_unreadable_lock_body_still_reports_a_held_lock(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Contention is the answer, so an unreadable pid must not unsay it.

        00466 N29: this reported "nothing holds it", which silenced the
        restart warning for a run that was in progress.
        """
        _lock_file(tmp_path)

        with (
            caplog.at_level(logging.WARNING),
            patch("claude_code_hooks_daemon.daemon.cli.fcntl.flock", side_effect=BlockingIOError),
            patch.object(Path, "read_text", side_effect=OSError),
        ):
            assert _qa_run_lock_holder(tmp_path) == "unknown"
        assert "pid is unreadable" in caplog.text


class TestCannotTellIsSaid:
    """00466 N29: "cannot tell" degrades to no restart warning, and says so."""

    def test_an_unopenable_lock_is_logged_at_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _lock_file(tmp_path)

        with (
            caplog.at_level(logging.WARNING),
            patch("claude_code_hooks_daemon.daemon.cli.os.open", side_effect=PermissionError),
        ):
            assert _qa_run_lock_holder(tmp_path) is None
        assert "Could not tell whether a QA run is in progress" in caplog.text

    def test_an_untestable_lock_is_logged_at_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _lock_file(tmp_path)

        with (
            caplog.at_level(logging.WARNING),
            patch("claude_code_hooks_daemon.daemon.cli.fcntl.flock", side_effect=OSError("ENOLCK")),
        ):
            assert _qa_run_lock_holder(tmp_path) is None
        assert "Could not tell whether a QA run is in progress" in caplog.text


class TestAHeldLockIsStillReported:
    def test_contention_reports_the_recorded_pid(self, tmp_path: Path) -> None:
        """The control: degrading on error must not stop it answering."""
        _lock_file(tmp_path)

        with patch("claude_code_hooks_daemon.daemon.cli.fcntl.flock", side_effect=BlockingIOError):
            assert _qa_run_lock_holder(tmp_path) == "4242"
