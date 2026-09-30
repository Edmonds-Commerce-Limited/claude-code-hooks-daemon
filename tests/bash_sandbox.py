"""Run a bash-differential probe where no git it reaches can touch a real repository.

A ``PATH`` that holds only a recording ``git`` is not containment: ``env -i``
and ``command -p`` fall back to ``/bin:/usr/bin`` and run the real git, which
once reached the main checkout. So every probe here runs with its cwd in a
throwaway ``git init`` sandbox, with ``GIT_DIR``, ``GIT_WORK_TREE`` and
``GIT_CEILING_DIRECTORIES`` pointing at it, and the checkout the tests run
from is compared before and after each run: any change fails the test at
once (Plan 00466 N101 round 13, the coordinator's probe rule).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from claude_code_hooks_daemon.constants.timeout import Timeout

#: The checkout these tests run from.
_CHECKOUT = Path(__file__).resolve().parent.parent


def _git() -> str:
    git = shutil.which("git", path="/usr/bin:/bin")
    assert git is not None
    return git


def _checkout_state() -> tuple[str, ...]:
    """HEAD, the porcelain status and the stash list of the test checkout."""
    return tuple(
        subprocess.run(
            [_git(), "-C", str(_CHECKOUT), *arguments],
            capture_output=True,
            text=True,
            check=False,
            timeout=Timeout.QA_TEST_TIMEOUT,
        ).stdout
        for arguments in (("rev-parse", "HEAD"), ("status", "--porcelain"), ("stash", "list"))
    )


def git_sandbox(directory: Path) -> Path:
    """``directory``, created and made a throwaway git repository."""
    directory.mkdir(parents=True, exist_ok=True)
    if not (directory / ".git").exists():
        subprocess.run(
            [_git(), "init", "-q", str(directory)],
            check=True,
            capture_output=True,
            timeout=Timeout.QA_TEST_TIMEOUT,
        )
    return directory


def run_sandboxed_bash(script: str, sandbox: Path, path: str, bash: str | None = None) -> str:
    """What ``bash -c script`` printed, run in the git sandbox ``sandbox``
    with ``PATH`` set to ``path``. Fails if the test checkout changed."""
    git_sandbox(sandbox)
    executable = bash or shutil.which("bash", path="/usr/bin:/bin")
    assert executable is not None
    before = _checkout_state()
    result = subprocess.run(
        [executable, "--norc", "--noprofile", "-c", script],
        cwd=sandbox,
        env={
            "LC_ALL": "C",
            "PATH": path,
            "GIT_DIR": str(sandbox / ".git"),
            "GIT_WORK_TREE": str(sandbox),
            "GIT_CEILING_DIRECTORIES": str(sandbox.parent),
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=Timeout.QA_TEST_TIMEOUT,
    )
    assert _checkout_state() == before, "a bash probe changed the test checkout"
    return result.stdout + result.stderr
