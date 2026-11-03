"""The containment proof behind lossless force removal (Plan 00558 DESIGN section 11).

A tip is safe to lose its ref when some OTHER ref (a branch, tag or
remote-tracking ref not deleted by the same command) still contains it. These
tests use real throwaway repositories.
"""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import force_removal
from claude_code_hooks_daemon.core.force_removal import (
    ALL_HOLDERS,
    REMOTE_HOLDERS,
    ContainmentUnknown,
    lost_commit_count,
    uncontained_tips,
)

_GIT_IDENTITY = (
    "-c",
    "user.name=Test",
    "-c",
    "user.email=test@example.invalid",
    "-c",
    "commit.gpgsign=false",
)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *_GIT_IDENTITY, *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name)
    _git(repo, "add", name)
    _git(repo, "commit", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """`main`; `solo` (one unique commit); `inner` contained by `outer/nested`; tag `v1`."""
    repo = tmp_path / "repo"
    _git(tmp_path, "init", "-b", "main", str(repo))
    _commit(repo, "base")
    _git(repo, "checkout", "-b", "solo")
    _commit(repo, "solo")
    _git(repo, "checkout", "-b", "inner", "main")
    _commit(repo, "inner")
    _git(repo, "checkout", "-b", "outer/nested")
    _commit(repo, "outer")
    _git(repo, "checkout", "-b", "tagged", "main")
    _commit(repo, "tagged")
    _git(repo, "tag", "v1")
    _git(repo, "checkout", "main")
    return repo


def _tip(repo: Path, name: str) -> str:
    return _git(repo, "rev-parse", f"refs/heads/{name}")


class TestUncontainedTips:
    def test_a_branch_held_only_by_itself_is_uncontained(self, repo: Path) -> None:
        tip = _tip(repo, "solo")
        assert uncontained_tips(repo, [tip], {"refs/heads/solo"}) == frozenset({tip})

    def test_a_tip_another_branch_contains_is_contained(self, repo: Path) -> None:
        tip = _tip(repo, "inner")
        assert uncontained_tips(repo, [tip], {"refs/heads/inner"}) == frozenset()

    def test_deleting_the_holder_too_leaves_it_uncontained(self, repo: Path) -> None:
        inner, outer = _tip(repo, "inner"), _tip(repo, "outer/nested")
        excluded = {"refs/heads/inner", "refs/heads/outer/nested"}
        assert uncontained_tips(repo, [inner, outer], excluded) == frozenset({inner, outer})

    def test_a_tag_holds_a_tip(self, repo: Path) -> None:
        tip = _tip(repo, "tagged")
        assert uncontained_tips(repo, [tip], {"refs/heads/tagged"}) == frozenset()

    def test_its_own_ref_counts_when_not_excluded(self, repo: Path) -> None:
        tip = _tip(repo, "solo")
        assert uncontained_tips(repo, [tip], set()) == frozenset()

    def test_remote_holders_only_ignores_local_branches(self, repo: Path) -> None:
        tip = _tip(repo, "inner")
        found = uncontained_tips(repo, [tip], {"refs/heads/inner"}, REMOTE_HOLDERS)
        assert found == frozenset({tip})

    def test_no_tips_asks_nothing(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def never(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
            raise AssertionError("git must not run")

        monkeypatch.setattr(force_removal, "run_git", never)
        assert uncontained_tips(repo, [], set()) == frozenset()

    def test_one_git_call_for_many_tips(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        real = force_removal.run_git
        calls: list[tuple[str, ...]] = []

        def spy(cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            return real(cwd, *args, **kwargs)

        monkeypatch.setattr(force_removal, "run_git", spy)
        tips = [_tip(repo, n) for n in ("solo", "inner", "tagged")]
        uncontained_tips(repo, tips, {f"refs/heads/{n}" for n in ("solo", "inner", "tagged")})
        assert len(calls) == 1

    def test_git_failure_raises(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def broken(cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(["git", *args], 128, "", "boom")

        monkeypatch.setattr(force_removal, "run_git", broken)
        with pytest.raises(ContainmentUnknown, match="boom"):
            uncontained_tips(repo, [_tip(repo, "solo")], set())

    def test_namespaces_cover_heads_remotes_and_tags(self) -> None:
        assert set(ALL_HOLDERS) == {"refs/heads", "refs/remotes", "refs/tags"}
        assert REMOTE_HOLDERS == ("refs/remotes",)


class TestLostCommitCount:
    def test_counts_commits_no_other_ref_reaches(self, repo: Path) -> None:
        _git(repo, "checkout", "solo")
        _commit(repo, "solo2")
        _git(repo, "checkout", "main")
        assert lost_commit_count(repo, _tip(repo, "solo"), {"refs/heads/solo"}) == 2

    def test_none_when_git_fails(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def broken(cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(["git", *args], 128, "", "boom")

        monkeypatch.setattr(force_removal, "run_git", broken)
        assert lost_commit_count(repo, _tip(repo, "solo"), set()) is None
