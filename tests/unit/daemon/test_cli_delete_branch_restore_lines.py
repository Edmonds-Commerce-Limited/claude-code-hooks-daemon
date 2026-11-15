"""``delete-branch`` reports one exact restore line per deleted branch.

A delete leans on no recovery copy: the proof is what permits it. The restore line
(``git branch <name> <sha>``) is only a machine-written pointer back to the tip the
proof named. Real repositories: the subject is what git actually does.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.daemon import branch_safety
from claude_code_hooks_daemon.daemon.cli import cmd_delete_branch

_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "PATH": "/usr/bin:/bin",
}

_RESTORE = re.compile(r"git branch (\S+) ([0-9a-f]{40})")


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


def _merged(repo: Path, name: str) -> str:
    _git(repo, "checkout", "-b", name)
    (repo / f"{name}.txt").write_text(f"{name}\n", encoding="utf-8")
    _git(repo, "add", f"{name}.txt")
    _git(repo, "commit", "-m", f"Add {name}")
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--no-ff", "-m", f"Merge {name}", name)
    return _git(repo, "rev-parse", f"refs/heads/{name}").strip()


def _args(repo: Path, branches: list[str], **overrides: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {
        "project_root": repo,
        "branches": branches,
        "protected_ref": "main",
        "dry_run": False,
        "format": "text",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestRestoreLines:
    def test_each_deleted_branch_gets_a_restore_line_that_restores_the_tip(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        tips = {name: _merged(repo, name) for name in ("a", "b")}
        assert cmd_delete_branch(_args(repo, ["a", "b"])) == 0
        found = dict(_RESTORE.findall(capsys.readouterr().out))
        assert found == tips
        for name, tip in found.items():
            _git(repo, "branch", name, tip)
            assert _git(repo, "rev-parse", f"refs/heads/{name}").strip() == tips[name]

    def test_the_json_output_carries_the_restore_commands(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        tip = _merged(repo, "feat")
        assert cmd_delete_branch(_args(repo, ["feat"], format="json")) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["restore"] == [f"git branch feat {tip}"]
        assert "bundle" not in payload

    def test_a_dry_run_deletes_nothing_and_prints_no_restore_line(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _merged(repo, "feat")
        assert cmd_delete_branch(_args(repo, ["feat"], dry_run=True)) == 0
        assert "git branch feat" not in capsys.readouterr().out
        assert "feat" in _git(repo, "branch", "--list", "feat")


class TestEveryDeleteRefused:
    def test_the_output_says_nothing_was_deleted_and_no_restore_line(
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
        captured = capsys.readouterr()
        assert "nothing was deleted" in captured.err
        assert not _RESTORE.search(captured.out + captured.err)
        assert "feat" in _git(repo, "branch", "--list", "feat")
