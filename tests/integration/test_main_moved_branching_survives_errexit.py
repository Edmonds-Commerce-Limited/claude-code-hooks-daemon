"""The documented ``main-moved`` branching still branches under ``set -euo pipefail``.

Plan 00463 review 4 N3. ``CLAUDE/AgentTeam.md`` (now ``CLAUDE/QA.md``, the one
home of the full-gate batch mechanism) branched on ``case $? in``
straight after ``llm_qa.py main-moved``. The daemon's
``R-BASH-SAFE-MODE-PRELUDE-MISSING`` advisory asks for ``set -euo pipefail``,
and under ``errexit`` any verdict but ``unmoved`` killed the script before the
``case`` ran, so the documented branching was lost exactly when an agent
followed the daemon's advice.

The snippets are taken from the document and EXECUTED, with ``llm_qa.py`` and
``git`` stubbed, for every exit code ``main-moved`` has. A snippet only proves
anything if it is the text an agent copies, so nothing here is restated.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_QA_GUIDE = _REPO_ROOT / "CLAUDE" / "QA.md"

#: A snippet runs from the line ``rc=0`` to the ``esac`` that closes its case.
_SNIPPET = re.compile(r"^rc=0\n.*?^esac$", re.MULTILINE | re.DOTALL)

#: Step 5 of "The Batched Integration Gate" in QA.md.
_DOCUMENTED_SNIPPETS = 1

#: Every exit ``main-moved`` has: unmoved, no verdict, full-gate, docs-only,
#: targeted and head-moved.
_EXIT_CODES = [0, 1, 4, 5, 6, 7]

_UNMOVED = 0
_REACHED = "REACHED rc="
_TIMEOUT_SECONDS = 30

#: What the stubbed ``git rev-parse`` prints: the certified head that lands.
_CERTIFIED_SHA = "c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00"
#: The message each non-zero branch prints before it exits with the verdict.
_BRANCH_MESSAGES = {
    1: "no verdict",
    4: "main moved",
    5: "main moved",
    6: "main moved",
    7: "head-moved",
}


def _snippets() -> list[str]:
    return _SNIPPET.findall(_QA_GUIDE.read_text(encoding="utf-8"))


def _executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _run(
    snippet: str, exit_code: int, workdir: Path
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run ``snippet`` under errexit, with ``main-moved`` exiting ``exit_code``."""
    _executable(workdir / "scripts" / "qa" / "llm_qa.py", f"#!/bin/sh\nexit {exit_code}\n")
    git_log = workdir / "git.log"
    stubs = workdir / "stubs"
    _executable(
        stubs / "git",
        '#!/bin/sh\necho "$@" >> "$GIT_LOG"\n'
        f'case "$1" in rev-parse) echo {_CERTIFIED_SHA} ;; esac\n',
    )
    script = f"set -euo pipefail\n{snippet}\necho {_REACHED}$rc\n"
    completed = subprocess.run(
        ["bash", "-c", script],
        cwd=workdir,
        env={
            **os.environ,
            "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
            "GIT_LOG": str(git_log),
        },
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )
    return completed, git_log


def test_the_qa_guide_documents_each_branching_snippet() -> None:
    assert len(_snippets()) == _DOCUMENTED_SNIPPETS


@pytest.mark.parametrize("index", range(_DOCUMENTED_SNIPPETS))
@pytest.mark.parametrize("exit_code", _EXIT_CODES)
def test_every_verdict_reaches_its_branch_under_errexit(
    tmp_path: Path, index: int, exit_code: int
) -> None:
    """Unmoved goes on; every other verdict prints its branch and ends the block.

    Review 5 n1: a non-zero verdict fell through to the restart, the push and
    ``--finish``. It now exits with the verdict, so nothing after it runs.
    """
    completed, _ = _run(_snippets()[index], exit_code, tmp_path)
    if exit_code == _UNMOVED:
        assert completed.returncode == 0, completed.stderr
        assert f"{_REACHED}{exit_code}" in completed.stdout
    else:
        assert completed.returncode == exit_code, completed.stderr
        assert _BRANCH_MESSAGES[exit_code] in completed.stdout
        assert _REACHED not in completed.stdout


@pytest.mark.parametrize("index", range(_DOCUMENTED_SNIPPETS))
@pytest.mark.parametrize("exit_code", _EXIT_CODES)
def test_only_unmoved_fast_forwards_main(tmp_path: Path, index: int, exit_code: int) -> None:
    _, git_log = _run(_snippets()[index], exit_code, tmp_path)
    merged = git_log.exists() and "merge --ff-only" in git_log.read_text(encoding="utf-8")
    assert merged == (exit_code == _UNMOVED)


@pytest.mark.parametrize("index", range(_DOCUMENTED_SNIPPETS))
def test_unmoved_lands_the_certified_sha_not_the_branch(tmp_path: Path, index: int) -> None:
    """Review 5 m5: the branch could hold a late commit the gate never judged."""
    _, git_log = _run(_snippets()[index], _UNMOVED, tmp_path)
    calls = git_log.read_text(encoding="utf-8")
    assert "rev-parse refs/integration/certified/" in calls
    assert f"merge --ff-only {_CERTIFIED_SHA}" in calls
