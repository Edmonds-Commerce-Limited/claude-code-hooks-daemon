"""Tests for ``branch-keep`` and the keep notes (Plan 00571 Phase 3 slice c)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.branch_keep import (
    KEEP_NOTES_REF,
    BranchKeepError,
    BranchKeepSameReason,
    Keep,
    fetch_keeps,
    keep_branch,
    keep_tracking_ref,
    parse_keep_note,
    read_keeps,
)
from tests.support.git_fixtures import git_setup_timeout


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=git_setup_timeout(),
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
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
    return root


class TestParse:
    def test_reads_the_three_fields(self) -> None:
        body = "Kept-Reason: release branch\nKept-By: Tess\nKept-At: 2026-11-01T10:00:00Z\n"
        keep = parse_keep_note(body)
        assert keep is not None
        assert keep.reason == "release branch"
        assert keep.by == "Tess"
        assert keep.at == 1793527200

    def test_latest_of_several_wins(self) -> None:
        body = (
            "Kept-Reason: old\nKept-By: A\nKept-At: 2026-01-01T00:00:00Z\n\n"
            "Kept-Reason: new\nKept-By: B\nKept-At: 2026-06-01T00:00:00Z\n"
        )
        keep = parse_keep_note(body)
        assert keep is not None and keep.reason == "new"

    def test_garbage_is_none(self) -> None:
        assert parse_keep_note("nothing here") is None


class TestKeep:
    def test_keep_writes_note_and_pushes(self, repo: Path) -> None:
        tip = _git(repo, "rev-parse", "main")
        result = keep_branch(
            repo, [tip], reason="needed for audit", remote="origin", user="Tess", now=1_800_000_000
        )
        assert result.pushed is True
        assert "Kept-Reason: needed for audit" in _git(
            repo, "notes", f"--ref={KEEP_NOTES_REF}", "show", tip
        )
        assert _git(repo, "ls-remote", "origin", KEEP_NOTES_REF)

    def test_read_keeps_returns_only_requested_tips(self, repo: Path) -> None:
        tip = _git(repo, "rev-parse", "main")
        keep_branch(repo, [tip], reason="r", remote="origin", user="Tess", now=1_800_000_000)
        found = read_keeps(repo, {tip, "f" * 40}, "origin")
        assert set(found) == {tip}
        assert found[tip] == Keep("r", "Tess", 1_800_000_000)

    def test_read_keeps_without_any_ref_is_empty(self, repo: Path) -> None:
        assert read_keeps(repo, {_git(repo, "rev-parse", "main")}, "origin") == {}

    def test_same_reason_refused(self, repo: Path) -> None:
        tip = _git(repo, "rev-parse", "main")
        keep_branch(repo, [tip], reason="r", remote="origin", user="Tess", now=1_800_000_000)
        with pytest.raises(BranchKeepSameReason):
            keep_branch(repo, [tip], reason="r", remote="origin", user="Tess", now=1_800_000_100)

    def test_new_reason_replaces(self, repo: Path) -> None:
        tip = _git(repo, "rev-parse", "main")
        keep_branch(repo, [tip], reason="r", remote="origin", user="Tess", now=1_800_000_000)
        keep_branch(repo, [tip], reason="s", remote="origin", user="Tess", now=1_800_000_100)
        assert read_keeps(repo, {tip}, "origin")[tip].reason == "s"

    @pytest.mark.parametrize("reason", ["", "  ", "a\nb"])
    def test_bad_reason_refused(self, repo: Path, reason: str) -> None:
        with pytest.raises(BranchKeepError):
            keep_branch(
                repo,
                [_git(repo, "rev-parse", "main")],
                reason=reason,
                remote="origin",
                user="Tess",
                now=1.0,
            )

    def test_push_failure_keeps_local_and_gives_retry(self, repo: Path) -> None:
        _git(repo, "remote", "set-url", "origin", str(repo / "missing.git"))
        tip = _git(repo, "rev-parse", "main")
        result = keep_branch(repo, [tip], reason="r", remote="origin", user="Tess", now=1.0)
        assert result.pushed is False
        assert result.retry_command is not None and KEEP_NOTES_REF in result.retry_command
        assert read_keeps(repo, {tip}, "origin")[tip].reason == "r"


class TestFetch:
    def test_fetch_into_tracking_ref_is_read(self, repo: Path, tmp_path: Path) -> None:
        tip = _git(repo, "rev-parse", "main")
        keep_branch(repo, [tip], reason="r", remote="origin", user="Tess", now=1_800_000_000)
        other = tmp_path / "other"
        _git(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(other))
        assert fetch_keeps(other, "origin") is None
        assert _git(other, "rev-parse", "--verify", keep_tracking_ref("origin"))
        assert read_keeps(other, {tip}, "origin")[tip].reason == "r"

    def test_fetch_from_remote_without_ref_succeeds(self, repo: Path) -> None:
        assert fetch_keeps(repo, "origin") is None

    def test_fetch_failure_returns_error_text(self, repo: Path) -> None:
        _git(repo, "remote", "set-url", "origin", str(repo / "missing.git"))
        assert fetch_keeps(repo, "origin")
