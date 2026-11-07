"""``delete-branch`` recovery bundles accumulate (Plan 00571 Task 2.1, issue #165).

The default bundle used to be one fixed file that every call overwrote, so only
the last deleted branch could be restored. Each call now writes its own
timestamped file and prints a restore line per branch naming that file and the
full ``refs/heads/...`` refspec. Real repositories: the subject is what
``git bundle`` and ``git fetch`` actually do.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.daemon import branch_safety
from claude_code_hooks_daemon.daemon.branch_safety import new_bundle_path
from claude_code_hooks_daemon.daemon.cli import cmd_delete_branch

_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "PATH": "/usr/bin:/bin",
}

_EXIT_USAGE = 2
_RESTORE = re.compile(r"git fetch (\S+) (refs/heads/\S+):(refs/heads/\S+)")


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**_ENV, "HOME": str(repo)},
    )
    return result.stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    (path / ".claude" / "hooks-daemon").mkdir(parents=True)
    _git(path, "init", "-b", "main")
    (path / ".gitignore").write_text("untracked/\n.claude/\n", encoding="utf-8")
    _git(path, "add", ".gitignore")
    _git(path, "commit", "-m", "Initial commit")
    return path


def _merged(repo: Path, name: str, content: str = "") -> str:
    _git(repo, "checkout", "-b", name)
    filename = f"{name}-{len(content)}.txt"
    (repo / filename).write_text(f"{name}{content}\n", encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", f"Add {filename}")
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--no-ff", "-m", f"Merge {name}", name)
    return _git(repo, "rev-parse", f"refs/heads/{name}").strip()


def _args(repo: Path, branches: list[str], **overrides: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {
        "project_root": repo,
        "branches": branches,
        "protected_ref": "main",
        "allow_unproven": False,
        "reason": None,
        "bundle": None,
        "no_bundle": False,
        "dry_run": False,
        "format": "text",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _restore_lines(text: str) -> list[tuple[str, str, str]]:
    return [
        (match.group(1), match.group(2), match.group(3)) for match in _RESTORE.finditer(text)
    ]


def _run_restore(repo: Path, line: tuple[str, str, str], target: str) -> str:
    """Fetch ``line``'s bundle ref into ``target`` and return its tip."""
    bundle, source, _destination = line
    _git(repo, "fetch", "--quiet", bundle, f"{source}:refs/heads/{target}")
    return _git(repo, "rev-parse", f"refs/heads/{target}").strip()


class TestNewBundlePath:
    def test_names_carry_a_utc_stamp_and_a_random_suffix(self, tmp_path: Path) -> None:
        path = new_bundle_path(tmp_path, "delete-branch")
        assert path.parent == tmp_path
        assert re.fullmatch(r"delete-branch-\d{8}T\d{6}Z-[0-9a-f]{6}\.bundle", path.name)

    def test_two_calls_in_one_second_never_collide(self, tmp_path: Path) -> None:
        names = {new_bundle_path(tmp_path, "x") for _ in range(50)}
        assert len(names) == 50

    def test_an_existing_file_is_never_returned(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        suffixes = iter(["aaaaaa", "aaaaaa", "bbbbbb"])
        monkeypatch.setattr(branch_safety.secrets, "token_hex", lambda _n: next(suffixes))
        first = new_bundle_path(tmp_path, "x")
        first.write_bytes(b"taken")
        second = new_bundle_path(tmp_path, "x")
        assert second != first
        assert second.name.endswith("-bbbbbb.bundle")


class TestAccumulatingBundles:
    def test_five_sequential_deletes_are_all_restorable(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        names = [f"feat-{index}" for index in range(5)]
        tips = {name: _merged(repo, name) for name in names}
        lines: list[tuple[str, str, str]] = []
        for name in names:
            assert cmd_delete_branch(_args(repo, [name])) == 0
            lines += _restore_lines(capsys.readouterr().out)
        assert len(lines) == 5
        assert len({bundle for bundle, _, _ in lines}) == 5
        for (bundle, source, destination), name in zip(lines, names, strict=True):
            assert Path(bundle).parent == repo / "untracked" / "deleted-branches"
            assert source == destination == f"refs/heads/{name}"
            assert _run_restore(repo, (bundle, source, destination), name) == tips[name]

    def test_one_name_deleted_twice_keeps_both_tips(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        first = _merged(repo, "feat", "one")
        assert cmd_delete_branch(_args(repo, ["feat"])) == 0
        first_line = _restore_lines(capsys.readouterr().out)[0]
        second = _merged(repo, "feat", "second")
        assert cmd_delete_branch(_args(repo, ["feat"])) == 0
        second_line = _restore_lines(capsys.readouterr().out)[0]
        assert first != second
        assert _run_restore(repo, first_line, "back-1") == first
        assert _run_restore(repo, second_line, "back-2") == second

    def test_a_batch_prints_one_restore_line_per_branch(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _merged(repo, "a")
        _merged(repo, "b")
        assert cmd_delete_branch(_args(repo, ["a", "b"])) == 0
        lines = _restore_lines(capsys.readouterr().out)
        assert [source for _, source, _ in lines] == ["refs/heads/a", "refs/heads/b"]
        assert len({bundle for bundle, _, _ in lines}) == 1


class TestExplicitBundle:
    def test_a_new_path_is_used_as_given(
        self, repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _merged(repo, "feat")
        target = tmp_path / "mine.bundle"
        assert cmd_delete_branch(_args(repo, ["feat"], bundle=str(target))) == 0
        assert target.is_file()
        assert _restore_lines(capsys.readouterr().out)[0][0] == str(target)

    def test_an_existing_file_is_refused_and_nothing_is_deleted(
        self, repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _merged(repo, "feat")
        target = tmp_path / "taken.bundle"
        target.write_bytes(b"an earlier recovery")
        assert cmd_delete_branch(_args(repo, ["feat"], bundle=str(target))) == _EXIT_USAGE
        assert target.read_bytes() == b"an earlier recovery"
        assert "feat" in _git(repo, "branch", "--list", "feat")
        assert "already exists" in capsys.readouterr().err


class TestEveryDeleteRefused:
    def test_the_output_says_nothing_needed_recovering(
        self,
        repo: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _merged(repo, "feat")
        monkeypatch.setattr(
            branch_safety, "delete_argv_for_tier", lambda _tier: ("branch", "--no-such-flag")
        )
        assert cmd_delete_branch(_args(repo, ["feat"])) == 1
        err = capsys.readouterr().err
        assert "nothing was deleted" in err
        assert "no recovery bundle was kept" in err.lower()
        assert "feat" in _git(repo, "branch", "--list", "feat")
