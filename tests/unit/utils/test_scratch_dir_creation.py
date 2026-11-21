"""Plan 00627 Tasks 5.1 and 5.4: which Bash commands create a directory tree, and where."""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.scratch_dir_creation import (
    creates_directory_under,
    directory_creating_targets,
)

CWD = Path("/repo")
SCRATCH = Path("/repo/untracked/scratch")


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("mkdir -p untracked/scratch/a b", ["/repo/untracked/scratch/a", "/repo/b"]),
        ("mkdir --mode=700 /x/y", ["/x/y"]),
        ("git clone https://h/o/repo.git untracked/scratch/r", ["/repo/untracked/scratch/r"]),
        ("git clone --depth 1 -b main https://h/o/repo.git", ["/repo/repo"]),
        ("git -C untracked/scratch clone https://h/o/r.git", ["/repo/untracked/scratch/r"]),
        ("git init untracked/scratch/n", ["/repo/untracked/scratch/n"]),
        ("git init", ["/repo"]),
        ("git worktree add -b x untracked/scratch/w main", ["/repo/untracked/scratch/w"]),
        ("cp -r src untracked/scratch/copy", ["/repo/untracked/scratch/copy"]),
        ("cp -a src dst", ["/repo/dst"]),
        ("tar -xzf a.tgz -C untracked/scratch/t", ["/repo/untracked/scratch/t"]),
        ("tar --extract --file=a.tar --directory=out", ["/repo/out"]),
        ("tar xf a.tar", ["/repo"]),
        ("mktemp -d -p untracked/scratch", ["/repo/untracked/scratch"]),
        ("mktemp -d --tmpdir=untracked/scratch", ["/repo/untracked/scratch"]),
        ("mktemp -d untracked/scratch/t.XXXX", ["/repo/untracked/scratch"]),
        ("cd /tmp && mkdir q; echo hi", ["/repo/q"]),
    ],
)
def test_targets(command: str, expected: list[str]) -> None:
    assert [str(p) for p in directory_creating_targets(command, CWD)] == expected


@pytest.mark.parametrize(
    "command",
    [
        "echo hi > untracked/scratch/notes.md",
        "cat <<'EOF' > untracked/scratch/body.txt\nmkdir untracked/scratch/x\nEOF",
        "cp a untracked/scratch/b",
        "tar -tf a.tar",
        "mktemp",
        "git status",
        "ls untracked/scratch",
        "",
        "mkdir 'unterminated",
    ],
)
def test_not_directory_creating(command: str) -> None:
    assert directory_creating_targets(command, CWD) == ()


def test_under_root() -> None:
    assert creates_directory_under("mkdir untracked/scratch/x", CWD, (SCRATCH,))
    assert creates_directory_under("mkdir -p untracked/scratch", CWD, (SCRATCH,))
    assert not creates_directory_under("mkdir untracked/other", CWD, (SCRATCH,))
    assert not creates_directory_under("mkdir untracked/scratch-x", CWD, (SCRATCH,))
    assert creates_directory_under("mkdir ../repo/untracked/scratch/y", CWD, (SCRATCH,))
