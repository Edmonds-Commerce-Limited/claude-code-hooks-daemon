"""Tests for the first-class GitRepo utility (Plan 00113).

GitRepo is the single home for the git operations the daemon needs:
resolve the enclosing repo of a path, and read/write ``git config --local``
values. These tests init real git repos in tmp_path so the production
subprocess path is exercised.
"""

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.git_repo import GitRepo

_KEY = "hooksdaemon.testValue"


def _git_init(repo_root: Path) -> Path:
    repo_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", str(repo_root)],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )
    return repo_root


class TestResolveFor:
    def test_resolves_repo_for_path_inside(self, tmp_path: Path) -> None:
        repo = _git_init(tmp_path / "proj")
        resolved = GitRepo.resolve_for(repo / "src" / "x.py")
        assert resolved is not None
        assert resolved.root.resolve() == repo.resolve()

    def test_resolves_for_target_that_does_not_exist_yet(self, tmp_path: Path) -> None:
        repo = _git_init(tmp_path / "proj")
        (repo / "CLAUDE" / "Plan").mkdir(parents=True)
        target = repo / "CLAUDE" / "Plan" / "00042-not-created/PLAN.md"
        resolved = GitRepo.resolve_for(target)
        assert resolved is not None
        assert resolved.root.resolve() == repo.resolve()

    def test_resolves_nested_repo_not_outer(self, tmp_path: Path) -> None:
        outer = _git_init(tmp_path / "outer")
        inner = _git_init(outer / "vendor" / "lib")
        resolved = GitRepo.resolve_for(inner / "a/b.py")
        assert resolved is not None
        assert resolved.root.resolve() == inner.resolve()
        assert resolved.root.resolve() != outer.resolve()

    def test_returns_none_when_not_in_repo(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        assert GitRepo.resolve_for(plain / "x.py") is None

    def test_returns_none_when_git_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _git_init(tmp_path / "proj")

        def _raise(*_a: object, **_k: object) -> None:
            raise OSError("git missing")

        monkeypatch.setattr(subprocess, "run", _raise)
        assert GitRepo.resolve_for(repo / "x.py") is None


class TestReadConfig:
    def test_absent_key_returns_none(self, tmp_path: Path) -> None:
        repo = GitRepo(_git_init(tmp_path / "proj"))
        assert repo.read_config(_KEY) is None

    def test_reads_written_value(self, tmp_path: Path) -> None:
        repo = GitRepo(_git_init(tmp_path / "proj"))
        repo.write_config(_KEY, "42")
        assert repo.read_config(_KEY) == "42"

    def test_returns_raw_string_not_parsed(self, tmp_path: Path) -> None:
        """read_config is type-agnostic — returns the raw string; typed parsing
        is the caller's job (e.g. plan_numbering parses int)."""
        repo = GitRepo(_git_init(tmp_path / "proj"))
        repo.write_config(_KEY, "not-a-number")
        assert repo.read_config(_KEY) == "not-a-number"

    def test_returns_none_when_git_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = GitRepo(_git_init(tmp_path / "proj"))

        def _raise(*_a: object, **_k: object) -> None:
            raise OSError("git missing")

        monkeypatch.setattr(subprocess, "run", _raise)
        assert repo.read_config(_KEY) is None


class TestWriteConfig:
    def test_write_then_read_roundtrips(self, tmp_path: Path) -> None:
        repo = GitRepo(_git_init(tmp_path / "proj"))
        repo.write_config(_KEY, "110")
        assert repo.read_config(_KEY) == "110"

    def test_overwrites_previous(self, tmp_path: Path) -> None:
        repo = GitRepo(_git_init(tmp_path / "proj"))
        repo.write_config(_KEY, "110")
        repo.write_config(_KEY, "111")
        assert repo.read_config(_KEY) == "111"

    def test_write_raises_on_invalid_repo(self, tmp_path: Path) -> None:
        """FAIL FAST: writing to a non-repo path raises (not a silent no-op)."""
        not_a_repo = tmp_path / "plain"
        not_a_repo.mkdir()
        repo = GitRepo(not_a_repo)
        with pytest.raises(subprocess.CalledProcessError):
            repo.write_config(_KEY, "1")

    def test_value_survives_branch_switch(self, tmp_path: Path) -> None:
        """A --local config value lives in .git/config, so it is identical
        regardless of the checked-out branch (the core stability property)."""
        root = _git_init(tmp_path / "proj")
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            subprocess.run(
                ["git", "-C", str(root), "config", k, v],
                capture_output=True,
                check=True,
                timeout=Timeout.GIT_CONTEXT,
            )
        (root / "f.txt").write_text("x")
        subprocess.run(
            ["git", "-C", str(root), "add", "f.txt"],
            capture_output=True,
            check=True,
            timeout=Timeout.GIT_CONTEXT,
        )
        subprocess.run(
            ["git", "-C", str(root), "commit", "-m", "init"],
            capture_output=True,
            check=True,
            timeout=Timeout.GIT_CONTEXT,
        )
        repo = GitRepo(root)
        repo.write_config(_KEY, "110")
        subprocess.run(
            ["git", "-C", str(root), "checkout", "-b", "feature"],
            capture_output=True,
            check=True,
            timeout=Timeout.GIT_CONTEXT,
        )
        assert repo.read_config(_KEY) == "110"


class TestGitRepoValueSemantics:
    def test_equality_by_root(self, tmp_path: Path) -> None:
        """GitRepo is a value object: two instances with the same root are equal."""
        assert GitRepo(tmp_path) == GitRepo(tmp_path)
