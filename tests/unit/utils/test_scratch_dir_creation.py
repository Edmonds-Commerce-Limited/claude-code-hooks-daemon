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

#: Every positive case is also run behind these preludes: a newline is a
#: statement separator, and the safe-mode prelude rule makes the multi-line
#: shape the common one (D-RULE review finding 1).
PRELUDES = (
    "",
    "set -e\n",
    "set -euo pipefail\n\n",
    "echo start;\n",
    "set -e  # strict\n",
    "# don't glue\n",
)

POSITIVE_CASES = [
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
    ("cd /tmp && mkdir q; echo hi", ["/tmp/q"]),
    ("mkdir -p a \\\n  untracked/scratch/b", ["/repo/a", "/repo/untracked/scratch/b"]),
    ("echo one\nmkdir untracked/scratch/two", ["/repo/untracked/scratch/two"]),
    # D-RULE review finding 2: wrappers, other directory makers, cd.
    ("timeout 5 mkdir untracked/scratch/x", ["/repo/untracked/scratch/x"]),
    ("sudo -u me mkdir untracked/scratch/x", ["/repo/untracked/scratch/x"]),
    ("env FOO=1 mkdir untracked/scratch/x", ["/repo/untracked/scratch/x"]),
    ("command mkdir untracked/scratch/x", ["/repo/untracked/scratch/x"]),
    ("FOO=1 nice -n 5 mkdir untracked/scratch/x", ["/repo/untracked/scratch/x"]),
    ('bash -c "mkdir untracked/scratch/x"', ["/repo/untracked/scratch/x"]),
    ("sh -lc 'cd untracked/scratch && mkdir y'", ["/repo/untracked/scratch/y"]),
    ("install -d untracked/scratch/x", ["/repo/untracked/scratch/x"]),
    ("install -D a.txt untracked/scratch/x/a.txt", ["/repo/untracked/scratch/x"]),
    ("rsync -a src/ untracked/scratch/x/", ["/repo/untracked/scratch/x"]),
    ("unzip a.zip -d untracked/scratch/x", ["/repo/untracked/scratch/x"]),
    ("cp -r -t untracked/scratch src", ["/repo/untracked/scratch"]),
    ("cp -r --target-directory=untracked/scratch src", ["/repo/untracked/scratch"]),
    ("cd untracked/scratch && mkdir x", ["/repo/untracked/scratch/x"]),
    ("pushd untracked/scratch; mkdir x", ["/repo/untracked/scratch/x"]),
    ("(cd /tmp && mkdir a) && mkdir b", ["/tmp/a", "/repo/b"]),
    ("mkdir -p -- untracked/scratch/x", ["/repo/untracked/scratch/x"]),
    ("mkdir untracked/scratch/x > untracked/scratch/log 2>&1", ["/repo/untracked/scratch/x"]),
]


@pytest.mark.parametrize("prelude", PRELUDES)
@pytest.mark.parametrize(("command", "expected"), POSITIVE_CASES)
def test_targets(prelude: str, command: str, expected: list[str]) -> None:
    assert [str(p) for p in directory_creating_targets(prelude + command, CWD)] == expected


@pytest.mark.parametrize("prelude", PRELUDES)
def test_under_root_after_prelude(prelude: str) -> None:
    assert creates_directory_under(prelude + "mkdir -p untracked/scratch/x", CWD, (SCRATCH,))


@pytest.mark.parametrize("prelude", PRELUDES)
@pytest.mark.parametrize(
    "command",
    [
        "S=untracked/scratch; mkdir $S/x",
        'mkdir "$DIR/x"',
        "mkdir `pwd`/x",
        "cd $SOMEWHERE && mkdir x",
        "cd - && mkdir x",
        'bash -c \'bash -c "bash -c \\"bash -c mkdir\\""\'',
    ],
)
def test_unresolved_creation_counts_as_under(prelude: str, command: str) -> None:
    """A cap guard fails toward detecting a creation it cannot place."""
    assert creates_directory_under(prelude + command, CWD, (SCRATCH,))


@pytest.mark.parametrize(
    "command",
    [
        'echo "$X" > untracked/scratch/f',
        "cp $A $B",
        "cd $SOMEWHERE && cat x",
        "mv a.txt untracked/scratch/a.txt",
        "ln -s a.txt untracked/scratch/a",
        "rsync a.txt untracked/scratch/a.txt",
    ],
)
def test_file_writes_stay_negative(command: str) -> None:
    assert not creates_directory_under(command, CWD, (SCRATCH,))


def test_mv_and_ln_of_a_directory_count(tmp_path: Path) -> None:
    (tmp_path / "d").mkdir()
    scratch = tmp_path / "untracked" / "scratch"
    assert creates_directory_under("mv d untracked/scratch/d", tmp_path, (scratch,))
    assert creates_directory_under("mv -t untracked/scratch d", tmp_path, (scratch,))
    assert creates_directory_under(f"ln -s {tmp_path}/d untracked/scratch/l", tmp_path, (scratch,))
    assert not creates_directory_under("mv d elsewhere", tmp_path, (scratch,))


def test_quoted_newline_stays_in_its_word() -> None:
    assert [str(p) for p in directory_creating_targets("mkdir 'a\nb'", CWD)] == ["/repo/a\nb"]


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
