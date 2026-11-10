"""Task 4.3 gaps: remote-only park record, group-pool PARKED, "park cleared" on an ended park."""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import (
    BranchesConfig,
    BranchParkedConfig,
    BranchWipConfig,
)
from claude_code_hooks_daemon.core.branch_creation import creation_verdict
from claude_code_hooks_daemon.core.branch_park import (
    announce_ended_parks,
    park_branch,
    read_park_record,
)
from tests.support.git_fixtures import git_setup_timeout

_REFUSAL = "gate: a fresh full-QA verdict is required"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=git_setup_timeout(),
    ).stdout.strip()


def _refuse_pushes(repo: Path) -> None:
    hook = repo / ".git" / "hooks" / "pre-push"
    hook.write_text(f"#!/bin/sh\necho '{_REFUSAL}' >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo whose branch ``work`` is pushed to a bare origin."""
    bare = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(bare)],
        check=True,
        timeout=git_setup_timeout(),
    )
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "Tess")
    _git(root, "remote", "add", "origin", str(bare))
    _git(root, "commit", "-q", "--allow-empty", "-m", "root")
    _git(root, "push", "-q", "origin", "main")
    _git(root, "checkout", "-q", "-b", "work")
    (root / "f.txt").write_text("x")
    _git(root, "add", "f.txt")
    _git(root, "commit", "-q", "-m", "work")
    _git(root, "push", "-q", "origin", "work")
    _git(root, "checkout", "-q", "main")
    return root


def _remote_only(repo: Path) -> None:
    _git(repo, "branch", "-q", "-D", "work")


class TestRemoteOnlyRefusedPush:
    def test_a_refused_push_parks_locally_and_writes_the_record(self, repo: Path) -> None:
        _remote_only(repo)
        _refuse_pushes(repo)
        result = park_branch(repo, "work", reason="waiting", remote="origin")
        assert result.pushed is False
        assert _REFUSAL in (result.push_error or "")
        assert result.retry_command == "git push origin work"
        record = read_park_record(repo, "work")
        assert record is not None and record.sha == result.sha and record.reason == "waiting"
        assert _git(repo, "rev-parse", "refs/heads/work") == result.sha

    def test_an_accepted_push_leaves_no_local_branch(self, repo: Path) -> None:
        _remote_only(repo)
        result = park_branch(repo, "work", reason="waiting", remote="origin")
        assert result.pushed is True
        assert read_park_record(repo, "work") is None
        probe = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", "refs/heads/work"],
            capture_output=True,
            check=False,
            timeout=git_setup_timeout(),
        )
        assert probe.returncode != 0

    def test_the_cli_exits_three_for_a_remote_only_refusal(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from claude_code_hooks_daemon.core.branch_park import EXIT_PARKED_NOT_PUSHED
        from claude_code_hooks_daemon.daemon.cli import build_parser, cmd_branch_park

        (repo / ".claude" / "hooks-daemon").mkdir(parents=True)
        _remote_only(repo)
        _refuse_pushes(repo)
        args = build_parser().parse_args(
            ["--project-root", str(repo), "branch-park", "work", "--reason", "waiting"]
        )
        args.project_root = repo
        assert cmd_branch_park(args) == EXIT_PARKED_NOT_PUSHED
        out = capsys.readouterr().out
        assert "parked locally, not pushed" in out and "git push origin work" in out


class TestGroupPoolResolvesToParked:
    @staticmethod
    def _config() -> BranchesConfig:
        return BranchesConfig(
            default="main",
            wip=BranchWipConfig(cap=1, mode="block", count_remote=True, creation_grace=0),
            parked=BranchParkedConfig(cap=5),
        )

    def test_a_rejected_park_push_stops_counting_as_open(self, repo: Path) -> None:
        # Before the park the single open branch fills the cap of 1.
        assert creation_verdict(repo, self._config(), "fresh").decision == "deny"
        _refuse_pushes(repo)
        park_branch(repo, "work", reason="waiting", remote="origin")
        verdict = creation_verdict(repo, self._config(), "fresh")
        assert verdict.decision == "allow", verdict.lines

    def test_a_remote_tip_that_is_not_behind_the_park_stays_open(self, repo: Path) -> None:
        _refuse_pushes(repo)
        park_branch(repo, "work", reason="waiting", remote="origin")
        # The remote moved on to a commit the park does not contain.
        _git(repo, "checkout", "-q", "-b", "other", "main")
        (repo / "g.txt").write_text("g")
        _git(repo, "add", "g.txt")
        _git(repo, "commit", "-q", "-m", "other")
        _git(repo, "update-ref", "refs/remotes/origin/work", "refs/heads/other")
        _git(repo, "checkout", "-q", "main")
        _git(repo, "branch", "-q", "-D", "other")
        assert creation_verdict(repo, self._config(), "fresh").decision == "deny"


class TestEndedParkIsAnnounced:
    def test_new_work_prints_park_cleared_once_then_removes_the_record(self, repo: Path) -> None:
        park_branch(repo, "work", reason="waiting", remote="origin")
        _git(repo, "checkout", "-q", "work")
        (repo / "h.txt").write_text("h")
        _git(repo, "add", "h.txt")
        _git(repo, "commit", "-q", "-m", "more work")
        _git(repo, "checkout", "-q", "main")
        assert announce_ended_parks(repo) == ["Park cleared: work (waiting)"]
        assert read_park_record(repo, "work") is None
        assert announce_ended_parks(repo) == []

    def test_a_standing_park_is_not_announced(self, repo: Path) -> None:
        park_branch(repo, "work", reason="waiting", remote="origin")
        assert announce_ended_parks(repo) == []
        assert read_park_record(repo, "work") is not None

    def test_a_vanished_branch_ends_the_park_visibly(self, repo: Path) -> None:
        # ``git branch -D`` drops the branch's config section itself; a bare ref
        # deletion leaves the record behind, and that must be said.
        park_branch(repo, "work", reason="waiting", remote="origin")
        _git(repo, "update-ref", "-d", "refs/heads/work")
        assert announce_ended_parks(repo) == ["Park cleared: work (waiting)"]
        assert read_park_record(repo, "work") is None


def test_branch_sweep_prints_an_ended_park_once(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from claude_code_hooks_daemon.daemon.cli import build_parser, cmd_branch_sweep

    (repo / ".claude" / "hooks-daemon").mkdir(parents=True)
    park_branch(repo, "work", reason="waiting", remote="origin")
    _git(repo, "checkout", "-q", "work")
    (repo / "h.txt").write_text("h")
    _git(repo, "add", "h.txt")
    _git(repo, "commit", "-q", "-m", "more work")
    _git(repo, "checkout", "-q", "main")

    def run() -> str:
        args = build_parser().parse_args(["--project-root", str(repo), "branch-sweep"])
        args.project_root = repo
        assert cmd_branch_sweep(args) == 0
        return capsys.readouterr().out

    assert "Park cleared: work (waiting)" in run()
    assert "Park cleared" not in run()
