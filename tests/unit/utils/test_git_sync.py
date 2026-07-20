"""Tests for the git_sync utility (Plan 00178).

git_sync is the focused home for the upstream-sync git operations the
``git_upstream_checker`` SessionStart handler needs: resolve the current branch
and its upstream, count ahead/behind, check the working tree is clean, run a
full ``git fetch --all --prune``, and perform a safe ``git pull --ff-only``.

These tests init real git repos (with a local bare "remote") in tmp_path so the
production subprocess path is exercised end to end. Failure / env-assertion
paths use monkeypatch.
"""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils import git_sync

_TIMEOUT = Timeout.GIT_CONTEXT


def _run(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=Timeout.GIT_FETCH_BACKGROUND,
    )
    return result.stdout.strip()


def _configure_identity(repo: Path) -> None:
    _run(repo, "config", "user.email", "t@t")
    _run(repo, "config", "user.name", "tester")
    _run(repo, "config", "commit.gpgsign", "false")


def _commit(repo: Path, name: str, content: str) -> None:
    (repo / name).write_text(content)
    _run(repo, "add", name)
    _run(repo, "commit", "-m", f"add {name}")


def _make_remote_and_clone(tmp_path: Path) -> tuple[Path, Path]:
    """Create a bare remote with one commit on ``main`` and a tracking clone.

    Returns (remote_bare, clone) where clone's ``main`` tracks ``origin/main``
    and is exactly in sync.
    """
    seed = tmp_path / "seed"
    seed.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(seed)],
        capture_output=True,
        check=True,
        timeout=_TIMEOUT,
    )
    _configure_identity(seed)
    _commit(seed, "README.md", "seed\n")

    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "clone", "--bare", str(seed), str(remote)],
        capture_output=True,
        check=True,
        timeout=_TIMEOUT,
    )

    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", str(remote), str(clone)],
        capture_output=True,
        check=True,
        timeout=_TIMEOUT,
    )
    _configure_identity(clone)
    return remote, clone


def _advance_remote(tmp_path: Path, remote: Path, *, commits: int = 1) -> None:
    """Push ``commits`` new commits to the remote via a throwaway clone."""
    pusher = tmp_path / "pusher"
    if not pusher.exists():
        subprocess.run(
            ["git", "clone", str(remote), str(pusher)],
            capture_output=True,
            check=True,
            timeout=_TIMEOUT,
        )
        _configure_identity(pusher)
    for i in range(commits):
        _commit(pusher, f"remote_{i}.txt", f"remote change {i}\n")
    _run(pusher, "push", "origin", "main")


def _status(repo: Path) -> git_sync.UpstreamStatus:
    """Assert-non-None helper so tests stay free of type: ignore."""
    status = git_sync.upstream_status(repo)
    assert status is not None
    return status


class TestCurrentBranch:
    def test_returns_branch_name(self, tmp_path: Path) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        assert git_sync.current_branch(clone) == "main"

    def test_returns_none_when_detached(self, tmp_path: Path) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        head = _run(clone, "rev-parse", "HEAD")
        _run(clone, "checkout", head)
        assert git_sync.current_branch(clone) is None

    def test_returns_none_when_not_a_repo(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        assert git_sync.current_branch(plain) is None


class TestUpstreamRef:
    def test_returns_tracking_ref(self, tmp_path: Path) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        assert git_sync.upstream_ref(clone) == "origin/main"

    def test_returns_none_when_no_upstream(self, tmp_path: Path) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        _run(clone, "checkout", "-b", "local-only")
        assert git_sync.upstream_ref(clone) is None

    def test_returns_none_when_not_a_repo(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        assert git_sync.upstream_ref(plain) is None


class TestUpstreamStatus:
    def test_in_sync(self, tmp_path: Path) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        status = _status(clone)
        assert status.branch == "main"
        assert status.upstream == "origin/main"
        assert status.behind == 0
        assert status.ahead == 0

    def test_behind_after_remote_advances_and_fetch(self, tmp_path: Path) -> None:
        remote, clone = _make_remote_and_clone(tmp_path)
        _advance_remote(tmp_path, remote, commits=2)
        assert git_sync.fetch_all_prune(clone) is True
        status = _status(clone)
        assert status.behind == 2
        assert status.ahead == 0

    def test_ahead_after_local_commit(self, tmp_path: Path) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        _commit(clone, "local.txt", "local\n")
        status = _status(clone)
        assert status.behind == 0
        assert status.ahead == 1

    def test_diverged(self, tmp_path: Path) -> None:
        remote, clone = _make_remote_and_clone(tmp_path)
        _advance_remote(tmp_path, remote, commits=1)
        git_sync.fetch_all_prune(clone)
        _commit(clone, "local.txt", "local\n")
        status = _status(clone)
        assert status.behind == 1
        assert status.ahead == 1

    def test_none_when_detached(self, tmp_path: Path) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        head = _run(clone, "rev-parse", "HEAD")
        _run(clone, "checkout", head)
        assert git_sync.upstream_status(clone) is None

    def test_none_when_no_upstream(self, tmp_path: Path) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        _run(clone, "checkout", "-b", "local-only")
        assert git_sync.upstream_status(clone) is None

    def test_none_when_not_a_repo(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        assert git_sync.upstream_status(plain) is None


class _FakeCompleted:
    """Minimal CompletedProcess stand-in for defensive-branch tests."""

    def __init__(self, returncode: int, stdout: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


class TestUpstreamStatusDefensive:
    """Cover the defensive rev-list branches unreachable via real git."""

    def _patch_branch_and_upstream(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(git_sync, "current_branch", lambda _cwd: "main")
        monkeypatch.setattr(git_sync, "upstream_ref", lambda _cwd: "origin/main")

    def test_none_when_rev_list_returns_nonzero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_branch_and_upstream(monkeypatch)
        monkeypatch.setattr(git_sync, "_run_git", lambda *_a, **_k: _FakeCompleted(1, ""))
        assert git_sync.upstream_status(tmp_path) is None

    def test_none_when_rev_list_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_branch_and_upstream(monkeypatch)
        monkeypatch.setattr(git_sync, "_run_git", lambda *_a, **_k: None)
        assert git_sync.upstream_status(tmp_path) is None

    def test_none_when_field_count_wrong(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_branch_and_upstream(monkeypatch)
        monkeypatch.setattr(git_sync, "_run_git", lambda *_a, **_k: _FakeCompleted(0, "5"))
        assert git_sync.upstream_status(tmp_path) is None

    def test_none_when_fields_not_integers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_branch_and_upstream(monkeypatch)
        monkeypatch.setattr(git_sync, "_run_git", lambda *_a, **_k: _FakeCompleted(0, "x\ty"))
        assert git_sync.upstream_status(tmp_path) is None


class TestWorkingTreeClean:
    def test_clean_repo(self, tmp_path: Path) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        assert git_sync.working_tree_clean(clone) is True

    def test_dirty_with_untracked(self, tmp_path: Path) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        (clone / "new.txt").write_text("x\n")
        assert git_sync.working_tree_clean(clone) is False

    def test_dirty_with_modified(self, tmp_path: Path) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        (clone / "README.md").write_text("changed\n")
        assert git_sync.working_tree_clean(clone) is False

    def test_not_a_repo_is_not_clean(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        assert git_sync.working_tree_clean(plain) is False


class TestFetchAllPrune:
    def test_fetch_updates_remote_tracking_ref(self, tmp_path: Path) -> None:
        remote, clone = _make_remote_and_clone(tmp_path)
        _advance_remote(tmp_path, remote, commits=1)
        # Before fetch the clone still sees itself in sync.
        assert _status(clone).behind == 0
        assert git_sync.fetch_all_prune(clone) is True
        assert _status(clone).behind == 1

    def test_returns_false_when_not_a_repo(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        assert git_sync.fetch_all_prune(plain) is False

    def test_fail_silent_on_subprocess_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, clone = _make_remote_and_clone(tmp_path)

        def _raise(*_a: object, **_k: object) -> None:
            raise OSError("git missing")

        monkeypatch.setattr(subprocess, "run", _raise)
        assert git_sync.fetch_all_prune(clone) is False

    def test_fail_silent_on_timeout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, clone = _make_remote_and_clone(tmp_path)

        def _timeout(*_a: object, **_k: object) -> None:
            raise subprocess.TimeoutExpired(cmd="git fetch", timeout=1)

        monkeypatch.setattr(subprocess, "run", _timeout)
        assert git_sync.fetch_all_prune(clone) is False

    def test_uses_full_fetch_flags_and_noninteractive_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        captured: dict[str, Any] = {}

        class _Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        def _capture(cmd: list[str], **kwargs: Any) -> _Completed:
            captured["cmd"] = cmd
            captured["env"] = kwargs.get("env")
            return _Completed()

        monkeypatch.setattr(subprocess, "run", _capture)
        git_sync.fetch_all_prune(clone)
        cmd = captured["cmd"]
        assert "fetch" in cmd
        assert "--all" in cmd
        assert "--prune" in cmd
        env = captured["env"]
        assert isinstance(env, dict)
        assert env.get("GIT_TERMINAL_PROMPT") == "0"


class TestPullFfOnly:
    def test_fast_forward_success(self, tmp_path: Path) -> None:
        remote, clone = _make_remote_and_clone(tmp_path)
        _advance_remote(tmp_path, remote, commits=2)
        git_sync.fetch_all_prune(clone)
        result = git_sync.pull_ff_only(clone)
        assert result.ok is True
        assert _status(clone).behind == 0

    def test_non_fast_forward_fails_gracefully(self, tmp_path: Path) -> None:
        remote, clone = _make_remote_and_clone(tmp_path)
        _advance_remote(tmp_path, remote, commits=1)
        git_sync.fetch_all_prune(clone)
        _commit(clone, "local.txt", "diverge\n")  # now diverged -> ff impossible
        result = git_sync.pull_ff_only(clone)
        assert result.ok is False
        assert result.detail  # non-empty reason

    def test_fail_silent_on_subprocess_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, clone = _make_remote_and_clone(tmp_path)

        def _raise(*_a: object, **_k: object) -> None:
            raise OSError("git missing")

        monkeypatch.setattr(subprocess, "run", _raise)
        result = git_sync.pull_ff_only(clone)
        assert result.ok is False
