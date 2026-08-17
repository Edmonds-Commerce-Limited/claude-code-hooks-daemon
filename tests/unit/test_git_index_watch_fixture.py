"""The index-lock watcher must not be able to pass vacuously (Plan 00248 F6).

``GitIndexWatch`` exists to stop one specific false pass: if git's cached stat
info is already current it skips the index refresh of its own accord, so "the
index was not rewritten" is true of ANY implementation and ``expect_none`` proves
nothing. Both context managers therefore make the index stale first.

That safeguard had a hole of exactly the same shape. ``_make_stale`` listed the
repository root non-recursively and touched whatever files it found, without
checking they were tracked — so for a repo whose tracked files live in
subdirectories it touched nothing, git had no refresh to skip, and the vacuity
came back. A guard whose own guard can silently stop working is worth a test of
its own, which is what this file is: the fixture as the subject, not as a tool.
"""

from __future__ import annotations

import subprocess  # nosec B404 - trusted system tool (git) for repo fixtures
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from tests.conftest import GitIndexWatch


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # nosec B603 B607 - trusted system tool, list form
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_COMMIT,
    )


@pytest.fixture
def nested_repo(tmp_path: Path) -> Path:
    """A repo whose ONLY tracked file lives in a subdirectory.

    The realistic shape — `src/`, `tests/`, `docs/` — and the one the previous
    implementation could not see.
    """
    repo = tmp_path / "nested"
    (repo / "src" / "deep").mkdir(parents=True)
    _git(repo, "init")
    _git(repo, "config", "--local", "user.email", "t@t")
    _git(repo, "config", "--local", "user.name", "t")
    _git(repo, "config", "--local", "commit.gpgsign", "false")
    (repo / "src" / "deep" / "module.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "src/deep/module.py")
    _git(repo, "commit", "-m", "init")
    return repo


class TestMakeStaleReachesTrackedFilesAtAnyDepth:
    def test_a_tracked_file_in_a_subdirectory_is_touched(self, nested_repo: Path) -> None:
        tracked = nested_repo / "src" / "deep" / "module.py"
        before = tracked.stat().st_mtime_ns

        GitIndexWatch._make_stale(nested_repo)

        assert tracked.stat().st_mtime_ns != before, (
            "the only tracked file was not touched, so git has no refresh to "
            "skip and every expect_none assertion in this repo is vacuous"
        )

    def test_the_control_still_provokes_a_refresh_at_depth(self, nested_repo: Path) -> None:
        """The real proof: bare git must actually rewrite the index here.

        Touching a file is only a means; what matters is that it makes git WANT
        to refresh. ``expect_one`` asserts the rewrite happened, so it fails
        loudly if ``_make_stale`` ever stops working — which is the property that
        was missing.
        """
        watch = GitIndexWatch()

        with watch.expect_one(nested_repo, "bare git status"):
            subprocess.run(  # nosec B603 B607 - trusted system tool, list form
                ["git", "-C", str(nested_repo), "status", "--porcelain"],
                capture_output=True,
                check=True,
                timeout=Timeout.GIT_CONTEXT,
            )


class TestTheFixtureFailsLoudlyRatherThanVacuously:
    def test_an_untracked_only_repo_is_reported_not_silently_skipped(self, tmp_path: Path) -> None:
        """No tracked files means no possible staleness — say so, do not pass."""
        repo = tmp_path / "empty"
        repo.mkdir()
        _git(repo, "init")
        (repo / "loose.txt").write_text("not added\n", encoding="utf-8")

        with pytest.raises(AssertionError, match="no tracked files"):
            GitIndexWatch._make_stale(repo)

    def test_a_repo_with_no_index_is_reported_by_name(self, tmp_path: Path) -> None:
        """A bare ``FileNotFoundError`` from a fixture reads as a test bug."""
        repo = tmp_path / "fresh"
        repo.mkdir()
        _git(repo, "init")

        with pytest.raises(AssertionError, match="no .git/index"):
            GitIndexWatch._identity(repo)
