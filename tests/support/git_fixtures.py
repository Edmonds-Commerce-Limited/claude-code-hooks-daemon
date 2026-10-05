"""Shared ``git`` invocation helper for tests that build a scratch repository.

RV4-n4: three test files (``test_git_facts.py``, ``test_goal_injection.py``,
``test_recovery_cron_advisor.py``) each carried their OWN copy of this exact
function, each with its own ``# nosec B603 B607`` suppression. One helper,
one suppression -- reused, not re-derived.
"""

import subprocess
from pathlib import Path
from typing import Final

from tests.load_scaling import scaled_seconds

#: Idle-host budget for a git command that only BUILDS a test fixture. The
#: production git-context timeout (5 s) bounds the daemon's own hook-path git
#: calls and must not be borrowed by setup, which is not what is under test
#: (ledger 00466 N95). Assertions about the product's timing keep the product constant.
GIT_SETUP_BASE_SECONDS: Final[float] = 30.0


def git_setup_timeout(
    *,
    load_averages: tuple[float, float, float] | None = None,
    cpu_count: int | None = None,
) -> float:
    """Load-scaled time budget for a fixture's setup ``git`` subprocess."""
    return scaled_seconds(GIT_SETUP_BASE_SECONDS, load_averages=load_averages, cpu_count=cpu_count)


def run_git(root: Path, *args: str) -> None:
    """Run a real ``git`` command against ``root``; raises on a non-zero exit."""
    subprocess.run(  # nosec B603 B607 - trusted system tool, list form
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        timeout=git_setup_timeout(),
    )
