"""A test file must not leave ``ProjectContext`` patched for the next one.

``ProjectContext`` is a process-wide singleton. A test that patches one of its
classmethods and fails to restore it does not fail itself — it fails whatever
runs next, with a value belonging to a file the reader is not looking at:

    assert PosixPath('.../test_ledger_failure_never_bloc0/untracked')
        == PosixPath('.../test_initialize_with_valid_con0/project/.claude/...')

That is the worst shape a test failure can take. It accuses correct, unchanged
code, and the accusation is convincing enough that the first response is to go
looking for a bug in the innocent file. This was found during Plan 00347's
regression testing and cost a clean worktree at an earlier commit to attribute.

**The measured mechanism** (Plan 00348 Task 1.2), confirmed by reading
``ProjectContext.__dict__`` after the fact rather than reasoning about
monkeypatch internals: when a test-level ``monkeypatch`` patches the SAME
attribute an autouse fixture has already patched, the fixture's context exits
first and restores the original — then the test-level patch is undone, and
pytest faithfully restores what IT recorded as the previous value, which is the
FIXTURE's patch. The fixture's lambda is left installed on the class for the
rest of the process.

This runs pytest in a SUBPROCESS on purpose. Asserting it in-process would only
report on the ambient run's ordering, which ``pytest-randomly`` shuffles — the
pair has to be forced.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

_VICTIM: Final[str] = "tests/unit/core/test_project_context.py"

# Every file that leaked, found by sweeping each handler test file against the
# victim. `test_goal_injection.py` was the first and was NOT the only one --
# three more had the identical shape, which is why the fix is paired with a
# check rather than left as four corrections.
_LEAKERS: Final[tuple[str, ...]] = (
    "tests/unit/handlers/post_tool_use/test_goal_injection.py",
    "tests/unit/handlers/pre_compact/test_compaction_signal.py",
    "tests/unit/handlers/status_line/test_context_sidecar.py",
    "tests/unit/handlers/stop/test_goal_ledger_stop_defence.py",
)
_LEAKER: Final[str] = _LEAKERS[0]


def _run_pair(first: str, second: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            first,
            second,
            "-q",
            "-p",
            "no:randomly",
            "--no-cov",
        ],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


class TestTheHarnessIsNotVacuous:
    def test_both_files_exist(self) -> None:
        """A mistyped path would make the run below fail for the wrong reason,
        or pass by collecting nothing."""
        assert (_REPO_ROOT / _LEAKER).is_file()
        assert (_REPO_ROOT / _VICTIM).is_file()

    def test_each_file_passes_on_its_own(self) -> None:
        """Establishes that neither file is simply broken. The defect is in the
        COMBINATION, and this is what makes that claim checkable."""
        for path in (_LEAKER, _VICTIM):
            result = _run_pair(path, path)
            assert result.returncode == 0, f"{path} does not pass alone:\n{result.stdout[-2000:]}"


class TestPatchedProjectContextDoesNotSurvive:
    @pytest.mark.parametrize("leaker", _LEAKERS)
    def test_the_victim_passes_after_each_known_leaker(self, leaker: str) -> None:
        result = _run_pair(leaker, _VICTIM)

        assert result.returncode == 0, (
            f"ProjectContext is still patched after {leaker} finished, so "
            f"{_VICTIM} sees another file's tmp_path. The failure below names "
            "the victim, but the defect is in the leaker:\n"
            f"{result.stdout[-3000:]}"
        )
