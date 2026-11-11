"""Defence: a ``git config`` write waits out a held ``config.lock`` instead of failing at once.

Class (N621): a multi-step write to a shared single-writer file that fails on first
contention instead of waiting. Git does not retry ``.git/config.lock`` itself, so
parallel agents writing the one config file collided.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.branch_park import (
    BranchParkError,
    ParkRecord,
    clear_park_record,
    read_park_record,
    write_park_record,
)
from claude_code_hooks_daemon.utils.git_config_write import (
    GitConfigLockError,
    run_git_config_write,
)
from claude_code_hooks_daemon.utils.git_repo import GitRepo
from tests.support.git_fixtures import git_setup_timeout

_HOLD_SECONDS = 0.4
_SHORT_BUDGET = 0.3
_STALE_AGE = 120


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(
        ["git", "init", "-q", str(tmp_path)],
        check=True,
        capture_output=True,
        timeout=git_setup_timeout(),
    )
    return tmp_path


def _hold_lock(lock: Path, seconds: float) -> threading.Thread:
    lock.write_text("")

    def release() -> None:
        time.sleep(seconds)
        lock.unlink()

    thread = threading.Thread(target=release)
    thread.start()
    return thread


class TestRunGitConfigWrite:
    def test_waits_out_a_held_lock(self, repo: Path) -> None:
        holder = _hold_lock(repo / ".git" / "config.lock", _HOLD_SECONDS)
        result = run_git_config_write(repo, "test.key", "value")
        holder.join()
        assert result.returncode == 0
        assert GitRepo(repo).read_config("test.key") == "value"

    def test_lock_held_past_the_budget_raises_naming_the_path(self, repo: Path) -> None:
        lock = repo / ".git" / "config.lock"
        lock.write_text("")
        with pytest.raises(GitConfigLockError) as excinfo:
            run_git_config_write(
                repo, "test.key", "value", base_wait=_SHORT_BUDGET, ceiling=_SHORT_BUDGET
            )
        assert str(lock) in str(excinfo.value)
        assert excinfo.value.lock_path == lock

    def test_old_lock_with_no_git_process_is_reported_stale_never_deleted(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lock = repo / ".git" / "config.lock"
        lock.write_text("")
        old = time.time() - _STALE_AGE
        os.utime(lock, (old, old))
        monkeypatch.setattr(
            "claude_code_hooks_daemon.utils.git_config_write._git_process_running",
            lambda: False,
        )
        with pytest.raises(GitConfigLockError, match="stale") as excinfo:
            run_git_config_write(
                repo, "test.key", "value", base_wait=_SHORT_BUDGET, ceiling=_SHORT_BUDGET
            )
        assert f"rm {lock}" in str(excinfo.value)
        assert lock.exists()

    def test_fresh_lock_is_not_called_stale(self, repo: Path) -> None:
        (repo / ".git" / "config.lock").write_text("")
        with pytest.raises(GitConfigLockError) as excinfo:
            run_git_config_write(
                repo, "test.key", "value", base_wait=_SHORT_BUDGET, ceiling=_SHORT_BUDGET
            )
        assert "stale" not in str(excinfo.value)

    def test_other_failures_are_returned_not_retried(self, repo: Path) -> None:
        result = run_git_config_write(repo, "no-section-key", "value")
        assert result.returncode != 0


class TestParkRecordUnderContention:
    _RECORD = ParkRecord(sha="a" * 40, reason="why", parked_at=1, parked_by="me")

    def test_park_record_written_while_lock_is_held(self, repo: Path) -> None:
        holder = _hold_lock(repo / ".git" / "config.lock", _HOLD_SECONDS)
        write_park_record(repo, "feature", self._RECORD)
        holder.join()
        assert read_park_record(repo, "feature") == self._RECORD

    def test_clear_waits_out_a_held_lock(self, repo: Path) -> None:
        write_park_record(repo, "feature", self._RECORD)
        holder = _hold_lock(repo / ".git" / "config.lock", _HOLD_SECONDS)
        assert clear_park_record(repo, "feature") == self._RECORD
        holder.join()
        assert read_park_record(repo, "feature") is None

    def test_lock_beyond_budget_is_a_park_error_naming_the_lock(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "claude_code_hooks_daemon.utils.git_config_write.Timeout.GIT_CONFIG_LOCK_WAIT",
            _SHORT_BUDGET,
        )
        monkeypatch.setattr(
            "claude_code_hooks_daemon.utils.git_config_write.Timeout.GIT_CONFIG_LOCK_WAIT_MAX",
            _SHORT_BUDGET,
        )
        lock = repo / ".git" / "config.lock"
        lock.write_text("")
        with pytest.raises(BranchParkError, match="config.lock"):
            write_park_record(repo, "feature", self._RECORD)


class TestGitRepoWriteConfig:
    def test_write_config_waits_out_a_held_lock(self, repo: Path) -> None:
        holder = _hold_lock(repo / ".git" / "config.lock", _HOLD_SECONDS)
        GitRepo(repo).write_config("test.key", "value")
        holder.join()
        assert GitRepo(repo).read_config("test.key") == "value"
