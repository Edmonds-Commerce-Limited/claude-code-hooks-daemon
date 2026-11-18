"""Reading park records costs one git process per pass, not four per branch (Plan 00618 N-5)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core import branch_park
from claude_code_hooks_daemon.core.branch_creation import creation_verdict
from claude_code_hooks_daemon.core.branch_park import (
    ParkRecord,
    read_park_record,
    read_park_records,
    write_park_record,
)
from claude_code_hooks_daemon.utils.git_repo import run_git


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    root = tmp_path / "repo"
    _git(tmp_path, "clone", "-q", str(remote), str(root))
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / ".git" / "info" / "exclude").write_text("untracked/\n")
    _git(root, "checkout", "-q", "-b", "main")
    _git(root, "commit", "-q", "--allow-empty", "-m", "root")
    _git(root, "push", "-q", "-u", "origin", "main")
    _git(root, "remote", "set-head", "origin", "main")
    for name in ("a", "b.dotted", "c"):
        _git(root, "branch", name)
    return root


def test_one_batched_read_returns_every_complete_record(repo: Path) -> None:
    tip = _git(repo, "rev-parse", "a")
    write_park_record(repo, "a", ParkRecord(tip, "why a", 100, "t"))
    write_park_record(repo, "b.dotted", ParkRecord(tip, "why b with spaces", 200, "u"))
    _git(repo, "config", "branch.c.hooksDaemonParked", tip)  # incomplete: ignored
    records = read_park_records(repo)
    assert records == {
        "a": ParkRecord(tip, "why a", 100, "t"),
        "b.dotted": ParkRecord(tip, "why b with spaces", 200, "u"),
    }
    assert read_park_record(repo, "a") == records["a"]
    assert read_park_record(repo, "c") is None


def test_batched_read_skips_an_unparsable_record(repo: Path) -> None:
    tip = _git(repo, "rev-parse", "a")
    write_park_record(repo, "a", ParkRecord(tip, "r", 1, "t"))
    _git(repo, "config", "branch.a.hooksDaemonParkedAt", "x")
    assert read_park_records(repo) == {}


def test_creation_check_reads_parks_with_one_config_process(repo: Path) -> None:
    config_calls: list[tuple[str, ...]] = []

    def spy(cwd: Path, *args: str, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
        if args[:1] == ("config",) and any("hooksdaemonparked" in a.lower() for a in args):
            config_calls.append(args)
        return run_git(cwd, *args, timeout=timeout)

    with mock.patch.object(branch_park, "run_git", spy):
        creation_verdict(repo, BranchesConfig(default="main"), "newb")
    assert len(config_calls) <= 1, config_calls
