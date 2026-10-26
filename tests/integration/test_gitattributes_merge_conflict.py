"""A real merge conflict on a deployed stub leaves no markers (Plan 00552 Task 2.2)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from claude_code_hooks_daemon.install.git_attributes import ensure_managed_block

STUB = "#!/usr/bin/env bash\nset -e\necho base\n"
HOOK = ".claude/hooks/pre-tool-use"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def _commit_change(root: Path, branch: str, body: str) -> None:
    assert _git(root, "checkout", "-q", branch).returncode == 0
    (root / HOOK).write_text(body)
    assert _git(root, "commit", "-aqm", f"change on {branch}").returncode == 0


def _conflicted_repo(root: Path, with_block: bool) -> subprocess.CompletedProcess[str]:
    assert _git(root, "init", "-q", "-b", "main").returncode == 0
    hook = root / HOOK
    hook.parent.mkdir(parents=True)
    hook.write_text(STUB)
    if with_block:
        ensure_managed_block(root)
    assert _git(root, "add", "-A").returncode == 0
    assert _git(root, "commit", "-qm", "base").returncode == 0
    assert _git(root, "branch", "side").returncode == 0
    _commit_change(root, "main", STUB + "echo ours\n")
    _commit_change(root, "side", STUB + "echo theirs\n")
    assert _git(root, "checkout", "-q", "main").returncode == 0
    return _git(root, "merge", "side")


class TestMergeConflictOnDeployedStub:
    """Both branches edit the same stub line region."""

    def test_block_keeps_ours_without_markers_and_git_still_reports(self, tmp_path: Path) -> None:
        result = _conflicted_repo(tmp_path, with_block=True)

        assert result.returncode != 0
        text = (tmp_path / HOOK).read_text()
        assert not any(
            line.startswith(("<<<<<<<", "=======", ">>>>>>>")) for line in text.splitlines()
        )
        assert "echo ours" in text
        syntax = subprocess.run(
            ["bash", "-n", str(tmp_path / HOOK)], capture_output=True, text=True, check=False
        )
        assert syntax.returncode == 0, syntax.stderr

        status = _git(tmp_path, "status", "--porcelain")
        assert any(
            line[:2] in ("UU", "AA") and line.endswith(HOOK) for line in status.stdout.splitlines()
        ), status.stdout
        unmerged = _git(tmp_path, "ls-files", "--unmerged")
        assert HOOK in unmerged.stdout

    def test_without_block_git_writes_markers(self, tmp_path: Path) -> None:
        """Control: proves the block, not git's defaults, removes the markers."""
        result = _conflicted_repo(tmp_path, with_block=False)

        assert result.returncode != 0
        text = (tmp_path / HOOK).read_text()
        assert "<<<<<<<" in text
        syntax = subprocess.run(
            ["bash", "-n", str(tmp_path / HOOK)], capture_output=True, text=True, check=False
        )
        assert syntax.returncode != 0


def test_shell_deploy_step_writes_block_and_is_idempotent(tmp_path: Path) -> None:
    """``deploy_gitattributes_block`` in hooks_deploy.sh drives the Python module."""
    repo_root = Path(__file__).resolve().parents[2]
    script = (
        'print_verbose() { :; }; print_warning() { echo "WARN $*"; }; '
        f'source "{repo_root}/scripts/install/hooks_deploy.sh" && '
        f'deploy_gitattributes_block "{tmp_path}" "$PY" && '
        f'deploy_gitattributes_block "{tmp_path}" "$PY"'
    )
    env = {**os.environ, "PY": sys.executable, "PYTHONPATH": str(repo_root / "src")}
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=False, env=env
    )
    assert result.returncode == 0, result.stderr
    assert "WARN" not in result.stdout
    assert (tmp_path / ".gitattributes").read_text().count("-merge") == 2


@pytest.mark.parametrize("init_content", ["#!/usr/bin/env bash\necho a\n"])
def test_init_sh_is_covered_too(tmp_path: Path, init_content: str) -> None:
    """``.claude/init.sh`` carries the same attribute."""
    ensure_managed_block(tmp_path)
    assert _git(tmp_path, "init", "-q").returncode == 0
    init = tmp_path / ".claude" / "init.sh"
    init.parent.mkdir()
    init.write_text(init_content)
    check = _git(tmp_path, "check-attr", "merge", ".claude/init.sh", HOOK)
    assert check.stdout.count("merge: unset") == 2, check.stdout
