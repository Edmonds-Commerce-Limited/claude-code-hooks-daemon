"""The documented ``main-moved`` branching still branches under ``set -euo pipefail``.

Plan 00463 review 4 N3. ``CLAUDE/AgentTeam.md`` branched on ``case $? in``
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
_AGENT_TEAM = _REPO_ROOT / "CLAUDE" / "AgentTeam.md"

#: A snippet runs from the line ``rc=0`` to the ``esac`` that closes its case.
_SNIPPET = re.compile(r"^rc=0\n.*?^esac$", re.MULTILINE | re.DOTALL)

#: STEP 5 of "Parent → Main", and Phase 5 of the worked example.
_DOCUMENTED_SNIPPETS = 2

#: Every exit ``main-moved`` has: unmoved, no verdict, full-gate, docs-only,
#: targeted and head-moved.
_EXIT_CODES = [0, 1, 4, 5, 6, 7]

_UNMOVED = 0
_REACHED = "REACHED rc="
_TIMEOUT_SECONDS = 30


def _snippets() -> list[str]:
    return _SNIPPET.findall(_AGENT_TEAM.read_text(encoding="utf-8"))


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
    _executable(stubs / "git", '#!/bin/sh\necho "$@" >> "$GIT_LOG"\n')
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


def test_the_agent_team_guide_documents_each_branching_snippet() -> None:
    assert len(_snippets()) == _DOCUMENTED_SNIPPETS


@pytest.mark.parametrize("index", range(_DOCUMENTED_SNIPPETS))
@pytest.mark.parametrize("exit_code", _EXIT_CODES)
def test_every_verdict_reaches_its_branch_under_errexit(
    tmp_path: Path, index: int, exit_code: int
) -> None:
    completed, _ = _run(_snippets()[index], exit_code, tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert f"{_REACHED}{exit_code}" in completed.stdout


@pytest.mark.parametrize("index", range(_DOCUMENTED_SNIPPETS))
@pytest.mark.parametrize("exit_code", _EXIT_CODES)
def test_only_unmoved_fast_forwards_main(tmp_path: Path, index: int, exit_code: int) -> None:
    _, git_log = _run(_snippets()[index], exit_code, tmp_path)
    merged = git_log.exists() and "merge --ff-only" in git_log.read_text(encoding="utf-8")
    assert merged == (exit_code == _UNMOVED)
