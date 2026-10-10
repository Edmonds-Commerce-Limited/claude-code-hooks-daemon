"""worktree_file_copy: the careless spellings of a worktree -> main-checkout copy (N385).

The guard's premise is a relocation whose source is a worktree and whose
destination is the main checkout. The original patterns only saw a destination
that is spelled as a main-repo code dir followed by `/`, so a copy into the
checkout root (`.`), a copy behind a wrapper, `cp -t DEST SRC`, and a copy run
by `find -exec` or `xargs` all went through.

How a destination is decided is documented in the handler module; the allow
rows here pin the false positives that decision must not create.
"""

import tempfile
from typing import Any

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.worktree_file_copy import (
    WorktreeFileCopyHandler,
)

WT = "/workspace/.claude/worktrees/agent-x"
# The scratch directory a `cd` into is not the main checkout: the process temp dir.
TMP = tempfile.gettempdir()


def _denied(command: str, cwd: str | None = None) -> bool:
    event: dict[str, Any] = {"tool_name": "Bash", "tool_input": {"command": command}}
    if cwd is not None:
        event["cwd"] = cwd
    return WorktreeFileCopyHandler().matches(event)


MUST_DENY = [
    # A whole-tree copy into the checkout root.
    f"cp -r {WT}/src .",
    f"cp -r {WT}/src ./",
    f"rsync -a {WT}/ ./",
    f"rsync -a {WT}/ .",
    f"cp -a {WT}/. .",
    f"mv {WT}/src/x.py .",
    # The destination after a literal cd to the main checkout.
    f"cd /workspace; cp -r {WT}/src .",
    f"cd /workspace && cp -r {WT}/src .",
    f"cd /workspace\ncp -r {WT}/src .",
    f"cd /workspace/src && cp {WT}/src/x.py .",
    f"cd src && cp {WT}/src/x.py .",
    f"cd src; cp {WT}/src/x.py x.py",
    # A subshell.
    f"(cp -r {WT}/src .)",
    f"cd /workspace && (cp -r {WT}/src .)",
    f"( cd /workspace; cp -r {WT}/src . )",
    # Behind a wrapper.
    f"command cp -r {WT}/src .",
    f"nice cp -r {WT}/src .",
    f"nice -n 5 cp -r {WT}/src .",
    f"sudo -u bob cp -r {WT}/src .",
    f"env FOO=1 cp -r {WT}/src .",
    f"time cp -r {WT}/src .",
    f"timeout 60 rsync -a {WT}/ ./",
    # xargs: the source arrives on stdin from a stage that names the worktree.
    f"ls {WT}/src | xargs -I{{}} cp {{}} src/",
    f"find {WT} -name '*.py' | xargs cp -t src/",
    f"echo {WT}/src/x.py | xargs -n1 cp -t src",
    f"echo {WT}/src/x.py | xargs -I{{}} cp {{}} .",
    # The destination named first.
    f"cp -t src/ {WT}/src/x.py",
    f"cp -t src {WT}/src/x.py {WT}/src/y.py",
    f"cp -rt src/ {WT}/src",
    f"cp --target-directory=src/ {WT}/src/x.py",
    f"cp --target-directory src/ {WT}/src/x.py",
    f"mv -t tests/ {WT}/tests/test_x.py",
    f"install -t src/ {WT}/src/x.py",
    # find -exec.
    f"find {WT}/src -name '*.py' -exec cp {{}} src/ \\;",
    f"find {WT}/src -type f -exec cp -t src/ {{}} +",
    f"find {WT} -name x.py -execdir cp {{}} . \\;",
    f"find {WT}/src -exec rsync -a {{}} src/ \\;",
    # An absolute destination, and a destination with no trailing slash.
    f"cp -r {WT}/src /workspace/src",
    f"cp -r {WT}/tests /workspace/tests",
    f"cp -r {WT}/src src",
    f"cp -r {WT}/src ./src",
    f"cp -r {WT}/tests ./tests/",
]


@pytest.mark.parametrize("command", MUST_DENY)
def test_careless_relocation_into_main_is_denied(command: str) -> None:
    assert _denied(command)


MUST_ALLOW = [
    # Main -> worktree.
    f"cp -r /workspace/src {WT}/",
    f"cp -r src {WT}/",
    f"rsync -a ./ {WT}/",
    f"cp -t {WT}/src/ /workspace/src/x.py",
    f"find /workspace/src -name '*.py' -exec cp {{}} {WT}/src/ \\;",
    f"ls src | xargs -I{{}} cp {{}} {WT}/src/",
    # Within one worktree.
    f"cp -r {WT}/src {WT}/backup",
    f"cp {WT}/src/x.py {WT}/src/y.py",
    f"cp -t {WT}/src/ {WT}/tests/x.py",
    f"cd {WT} && cp -r {WT}/src .",
    f"cd {WT}; cp -r src/x.py y.py; cp -r {WT}/src .",
    f"cd .claude/worktrees/agent-x && cp -r {WT}/src ./",
    f"nice cp -r {WT}/src {WT}/copy",
    # Worktree -> scratch / non-code destinations.
    f"cp {WT}/notes.md untracked/scratch/",
    f"cp -r {WT}/src untracked/scratch/src-copy",
    f"cp {WT}/src/x.py untracked/scratch/x.py",
    f"rsync -a {WT}/ untracked/scratch/wt-copy/",
    f"cp {WT}/notes.txt .",
    f"mv {WT}/notes.txt tmp.txt",
    f"cp -t /tmp/out/ {WT}/src/x.py",
    f"ls {WT}/src | xargs cp -t /tmp/out/",
    f"find {WT}/src -exec cp {{}} /tmp/x \\;",
    f"cd {TMP}; cp -r {WT}/src .",
    f"cd {TMP} && command cp -r {WT}/src .",
    # Not a copy at all.
    f"git -C {WT} status",
    f"git -C {WT} diff --stat",
    f"git -C {WT} log --oneline",
    f"ls {WT}/src",
    f"echo 'cp -r {WT}/src .'",
    f"grep -rn x {WT}/src .",
    f"find {WT}/src -name '*.py'",
    f"find {WT} -name x.py -exec grep -l y {{}} \\;",
    f"ls {WT}/src; xargs echo hi",
    # The source is not a worktree.
    "cp -r docs/ .",
    "cp -t src/ README.md",
    "find src -exec cp {} backup/ \\;",
]


@pytest.mark.parametrize("command", MUST_ALLOW)
def test_legitimate_commands_are_still_allowed(command: str) -> None:
    assert not _denied(command)


def test_an_unresolvable_cd_leaves_a_bare_dot_destination_undecided() -> None:
    """A `cd` to a non-literal path cannot say where `.` is, so a bare `.` is not denied.

    The destination is the only thing left undecided: a destination that is
    itself spelled as a main-repo code dir is denied whatever the cwd.
    """
    assert not _denied(f"cd $TARGET; cp -r {WT}/src .")
    assert not _denied(f'cd "$(pwd)/x"; cp -r {WT}/src .')
    assert _denied(f"cd $TARGET; cp -r {WT}/src src/")


def test_a_hook_cwd_inside_a_worktree_makes_a_bare_dot_that_worktree() -> None:
    assert not _denied(f"cp -r {WT}/src .", cwd=WT)
    assert not _denied(f"cp -r {WT}/src .", cwd=f"{WT}/sub")
    assert _denied(f"cp -r {WT}/src .", cwd="/workspace")


def test_a_cd_back_to_main_after_a_worktree_cd_is_main_again() -> None:
    assert _denied(f"cd {WT}; cd /workspace; cp -r {WT}/src .")
    assert not _denied(f"cd /workspace; cd {WT}; cp -r {WT}/src .")


def test_a_cd_inside_a_subshell_does_not_leak() -> None:
    """`(cd tmp)` ends with the subshell, so the next command still runs in main."""
    assert _denied(f"(cd {TMP}); cp -r {WT}/src .")
