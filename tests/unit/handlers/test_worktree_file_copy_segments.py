"""worktree_file_copy judges each command segment on its own tokens.

Plan 00483 Task 3.2, batch (c). The guard's premise is a relocation verb whose
operands name a worktree path and then a main-repo code dir. The patterns ran
across `&&`/`;` into the NEXT command, and a data command (`grep`, `echo`) that
only prints a worktree path was read as the relocation it describes.
"""

from typing import Any

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.worktree_file_copy import (
    WorktreeFileCopyHandler,
)


def _denied(command: str) -> bool:
    event: dict[str, Any] = {"tool_name": "Bash", "tool_input": {"command": command}}
    return WorktreeFileCopyHandler().matches(event)


ORDINARY = [
    "grep -rn 'mv untracked/worktrees/foo/src/x.py src/' docs/",
    'grep -rn "cp untracked/worktrees/foo/src/x.py src/" docs/',
    'echo "cp untracked/worktrees/foo/src/x.py src/"',
    "echo 'rsync -av untracked/worktrees/foo/src/ src/'",
    "ls untracked/worktrees/foo/src/ && cp README.md src/",
    "ls untracked/worktrees/foo/src/ ; cp README.md src/",
    "mv untracked/worktrees/foo/notes.txt tmp.txt; ls src/x",
    "cat untracked/worktrees/foo/notes.txt | head -n 1; cp README.md src/",
]


@pytest.mark.parametrize("command", ORDINARY)
def test_a_mention_or_an_unrelated_next_command_is_allowed(command: str) -> None:
    assert not _denied(command)


DANGEROUS = [
    "cp untracked/worktrees/foo/src/x.py src/",
    "mv untracked/worktrees/foo/src/x.py src/x.py",
    "rsync -av untracked/worktrees/foo/ src/",
    "sudo cp untracked/worktrees/foo/src/x.py src/",
    "cp -r untracked/worktrees/foo/tests/ tests/",
    "cd x && cp untracked/worktrees/foo/src/x.py src/",
    "ls ; cp untracked/worktrees/foo/src/x.py src/",
    "true || cp untracked/worktrees/foo/src/x.py src/",
    "ls | xargs echo; mv untracked/worktrees/foo/src/x.py src/",
    "echo $(cp untracked/worktrees/foo/src/x.py src/)",
    "bash -c 'cp untracked/worktrees/foo/src/x.py src/'",
    'sh -c "cp untracked/worktrees/foo/src/x.py src/"',
    "FOO=1 cp untracked/worktrees/foo/src/x.py src/",
    "echo 'cp untracked/worktrees/foo/src/x.py src/' | bash",
    "bash <<'EOF'\ncp untracked/worktrees/foo/src/x.py src/\nEOF",
    "for f in a; do cp untracked/worktrees/foo/src/x.py src/; done",
    "cp untracked/worktrees/foo/src/x.py src/ && ls",
    "cp .claude/worktrees/foo/src/x.py src/",
    # Review r2 B1: wrappers in front of the shell.
    "sudo bash -c 'cp untracked/worktrees/X/src/file.py src/x.py'",
    "/bin/bash -c 'cp untracked/worktrees/X/src/file.py src/x.py'",
    "env bash -c 'cp untracked/worktrees/X/src/file.py src/x.py'",
    "bash --login -c 'cp untracked/worktrees/X/src/file.py src/x.py'",
    "bash --norc -c 'cp untracked/worktrees/X/src/file.py src/x.py'",
    "sudo -E env FOO=1 sh -e -c 'mv untracked/worktrees/X/src/file.py src/x.py'",
    # Review r1 B1: a shell wrapper with options before `-c`.
    "sh -e -c 'cp untracked/worktrees/foo/src/x.py src/x.py'",
    "bash -x -c 'cp untracked/worktrees/foo/src/x.py src/x.py'",
    "bash -n -c 'cp untracked/worktrees/foo/src/x.py src/x.py'",
    "bash -n -c 'rsync -a untracked/worktrees/foo/src/ src/'",
    "bash -o pipefail -c 'cp untracked/worktrees/foo/src/x.py src/x.py'",
    "bash -nc 'cp untracked/worktrees/foo/src/x.py src/x.py'",
    'bash -n -c "cp untracked/worktrees/foo/src/x.py src/x.py"',
]


@pytest.mark.parametrize("command", DANGEROUS)
def test_a_real_relocation_stays_denied(command: str) -> None:
    assert _denied(command)


def test_a_move_out_of_a_worktree_to_a_non_code_path_was_never_in_scope() -> None:
    """The premise is worktree -> main-repo code dir, so `tmp.txt` is not one.

    `mv untracked/worktrees/foo/notes.txt tmp.txt` is allowed alone today; the
    trailing `ls src/x` only made it look like a destination.
    """
    assert not _denied("mv untracked/worktrees/foo/notes.txt tmp.txt")
    assert not _denied("mv untracked/worktrees/foo/notes.txt tmp.txt; ls src/x")
