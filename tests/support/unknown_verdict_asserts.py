"""Assertions every converted 'unknown verdict' route shares (Plan 00478).

A converted route must ALLOW, carry one advisory naming the guard and the cause,
and leave exactly one ``UNKNOWN-VERDICT`` log line (Success Criterion 3).
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.utils.unknown_verdict import UNKNOWN_VERDICT_LOG_PREFIX


def unknown_verdict_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """The ``UNKNOWN-VERDICT`` records captured so far."""
    return [r for r in caplog.records if r.getMessage().startswith(UNKNOWN_VERDICT_LOG_PREFIX)]


def assert_unknown_verdict(
    result: Any, caplog: pytest.LogCaptureFixture, guard: str, *needles: str
) -> str:
    """Assert ``result`` is an unknown-verdict allow; return its advisory text."""
    assert result.decision == Decision.ALLOW
    assert result.rule is None
    advisory = "\n".join(result.context)
    assert guard in advisory
    for needle in needles:
        assert needle in advisory, f"{needle!r} not in advisory: {advisory}"
    records = unknown_verdict_records(caplog)
    assert len(records) == 1, [r.getMessage() for r in records]
    assert records[0].getMessage().startswith(f"{UNKNOWN_VERDICT_LOG_PREFIX} {guard} ")
    return advisory


STAGING_RUN_GIT = "claude_code_hooks_daemon.utils.staging_simulation.run_git"


def failing_add_run_git() -> Any:
    """A ``run_git`` stand-in for the staging simulation whose ``git add`` times out."""
    import subprocess

    from claude_code_hooks_daemon.utils.git_repo import run_git

    def run(directory: Any, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "add" in args[:3]:
            return subprocess.CompletedProcess(["git"], 127, "", "timed out after 5s")
        return run_git(directory, *args, **kwargs)

    return run
