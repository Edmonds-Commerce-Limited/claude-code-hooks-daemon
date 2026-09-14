"""Fetching, and pulling only when provably safe (Plan 00401 Task 1.3).

This is the ONLY module in the package that touches the network, and it runs
from SessionStart, which already owns that budget. The owner's ruling was "the
daemon pulls when provably safe; reports and never touches otherwise", and
"otherwise" is the interesting half — a pull that clobbers someone's local work
is a worse outcome than the staleness this whole plan exists to prevent.

The refusal cases are therefore asserted individually rather than as one
"unsafe" bucket, because each needs a different remedy in the report and it
would be easy to ship a version that refuses correctly while explaining wrongly.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.reference_repos.refresh import refresh_repo
from claude_code_hooks_daemon.utils import git_sync


def _run(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout.strip()


def _identity(repo: Path) -> None:
    _run(repo, "config", "user.email", "t@t")
    _run(repo, "config", "user.name", "tester")
    _run(repo, "config", "commit.gpgsign", "false")


def _commit(repo: Path, name: str, content: str) -> None:
    (repo / name).write_text(content, encoding="utf-8")
    _run(repo, "add", name)
    _run(repo, "commit", "-m", f"add {name}")


def _remote_and_clone(tmp_path: Path) -> tuple[Path, Path]:
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    seed.mkdir()
    _run(seed, "init", "-b", "main")
    _identity(seed)
    _commit(seed, "README.md", "one\n")
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(origin)],
        capture_output=True,
        check=True,
        timeout=30,
    )
    _run(seed, "remote", "add", "origin", str(origin))
    _run(seed, "push", "-u", "origin", "main")

    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", str(origin), str(clone)],
        capture_output=True,
        check=True,
        timeout=30,
    )
    _identity(clone)
    return origin, clone


def _advance_origin(tmp_path: Path, origin: Path, name: str = "extra.md") -> None:
    pusher = tmp_path / "pusher"
    if not pusher.exists():
        subprocess.run(
            ["git", "clone", str(origin), str(pusher)],
            capture_output=True,
            check=True,
            timeout=30,
        )
        _identity(pusher)
    _commit(pusher, name, "more\n")
    _run(pusher, "push", "origin", "main")


class TestTheSafeCase:
    def test_a_clean_behind_repo_is_fetched_and_fast_forwarded(self, tmp_path: Path) -> None:
        origin, clone = _remote_and_clone(tmp_path)
        _advance_origin(tmp_path, origin)

        outcome = refresh_repo(clone)

        assert outcome.fetched is True
        assert outcome.pulled is True
        assert outcome.state.behind == 0
        assert outcome.state.needs_attention is False

    def test_the_pulled_content_actually_arrives(self, tmp_path: Path) -> None:
        """The point is the working tree, not the counter."""
        origin, clone = _remote_and_clone(tmp_path)
        _advance_origin(tmp_path, origin, name="landed.md")

        refresh_repo(clone)

        assert (clone / "landed.md").exists()

    def test_an_already_current_repo_fetches_but_pulls_nothing(self, tmp_path: Path) -> None:
        """Nothing to do is not a failure, and must not be reported as one."""
        _, clone = _remote_and_clone(tmp_path)

        outcome = refresh_repo(clone)

        assert outcome.fetched is True
        assert outcome.pulled is False
        assert outcome.state.needs_attention is False


class TestRefusals:
    """Each refusal is distinct, because each needs a different remedy."""

    def test_a_dirty_repo_is_fetched_but_never_pulled(self, tmp_path: Path) -> None:
        origin, clone = _remote_and_clone(tmp_path)
        _advance_origin(tmp_path, origin)
        (clone / "README.md").write_text("local edit\n", encoding="utf-8")

        outcome = refresh_repo(clone)

        assert outcome.fetched is True
        assert outcome.pulled is False
        assert outcome.state.behind == 1
        assert "uncommitted" in outcome.detail.lower()

    def test_a_dirty_repos_local_edit_survives(self, tmp_path: Path) -> None:
        """The invariant that matters more than freshness."""
        origin, clone = _remote_and_clone(tmp_path)
        _advance_origin(tmp_path, origin)
        (clone / "README.md").write_text("local edit\n", encoding="utf-8")

        refresh_repo(clone)

        assert (clone / "README.md").read_text(encoding="utf-8") == "local edit\n"

    def test_a_repo_with_local_commits_is_never_pulled(self, tmp_path: Path) -> None:
        _, clone = _remote_and_clone(tmp_path)
        _commit(clone, "mine.md", "mine\n")

        outcome = refresh_repo(clone)

        assert outcome.pulled is False
        assert "local commit" in outcome.detail.lower()

    def test_a_diverged_repo_is_named_as_diverged_not_merely_ahead(self, tmp_path: Path) -> None:
        """Diverged needs `git pull --rebase`; ahead needs a push. Different advice."""
        origin, clone = _remote_and_clone(tmp_path)
        _advance_origin(tmp_path, origin)
        _commit(clone, "mine.md", "mine\n")

        outcome = refresh_repo(clone)

        assert outcome.pulled is False
        assert outcome.state.is_diverged is True
        assert "diverged" in outcome.detail.lower()

    def test_an_uncheckable_repo_is_not_even_fetched(self, tmp_path: Path) -> None:
        """No remote means nothing to fetch; attempting it would just waste time."""
        local = tmp_path / "local"
        local.mkdir()
        _run(local, "init", "-b", "main")
        _identity(local)
        _commit(local, "README.md", "one\n")

        outcome = refresh_repo(local)

        assert outcome.fetched is False
        assert outcome.pulled is False
        assert outcome.state.checkable is False


class TestPullCanBeDisabled:
    def test_allow_pull_false_fetches_but_never_pulls(self, tmp_path: Path) -> None:
        """Report-only mode: the owner may want visibility without mutation."""
        origin, clone = _remote_and_clone(tmp_path)
        _advance_origin(tmp_path, origin)

        outcome = refresh_repo(clone, allow_pull=False)

        assert outcome.fetched is True
        assert outcome.pulled is False
        assert outcome.state.behind == 1
        assert outcome.state.needs_attention is True


class TestWhenGitItselfFails:
    def test_a_failed_fetch_is_reported_rather_than_raised(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An offline machine must degrade to a report, never break the session.

        SessionStart runs this; an exception here would cost the whole session's
        startup context for something as ordinary as being on a train.
        """
        _, clone = _remote_and_clone(tmp_path)

        monkeypatch.setattr(git_sync, "fetch_all", lambda *_a, **_k: False)

        outcome = refresh_repo(clone)

        assert outcome.fetched is False
        assert outcome.pulled is False
        assert "fetch" in outcome.detail.lower()

    def test_a_failed_pull_is_reported_rather_than_raised(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        origin, clone = _remote_and_clone(tmp_path)
        _advance_origin(tmp_path, origin)

        monkeypatch.setattr(
            git_sync,
            "pull_ff_only",
            lambda *_a, **_k: git_sync.PullResult(ok=False, detail="refused"),
        )

        outcome = refresh_repo(clone)

        assert outcome.fetched is True
        assert outcome.pulled is False
        assert "refused" in outcome.detail
