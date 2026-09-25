"""Shared ``git`` invocation helper for tests that build a scratch repository.

RV4-n4: three test files (``test_git_facts.py``, ``test_goal_injection.py``,
``test_recovery_cron_advisor.py``) each carried their OWN copy of this exact
function, each with its own ``# nosec B603 B607`` suppression. One helper,
one suppression -- reused, not re-derived.
"""

import subprocess
from pathlib import Path

from claude_code_hooks_daemon.constants.timeout import Timeout


def run_git(root: Path, *args: str) -> None:
    """Run a real ``git`` command against ``root``; raises on a non-zero exit."""
    subprocess.run(  # nosec B603 B607 - trusted system tool, list form
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        timeout=Timeout.GIT_CONTEXT,
    )
