"""Hang watchdog loaded into every child pytest ``run_child_pytest`` starts.

``run_child_pytest`` names this module with ``-p`` in ``PYTEST_ADDOPTS``, so a
child imports it while pytest parses its arguments, before output capture
replaces fd 2. It duplicates fd 2 then, so a dump reaches the caller's stderr
pipe even from inside a captured test.

It arms ``faulthandler.dump_traceback_later`` against a wall-clock deadline the
caller sets below its own timeout: a child that hangs prints every thread's
stack before the caller kills it. It re-arms at configure and again at the
last unconfigure, because a test may replace the one process-wide watchdog,
and the N531 hang came after the summary, when only this last arming is left.

Nothing happens on import unless the deadline variable is set, so the helper
can import ``DEADLINE_ENV`` from here without side effects.
"""

from __future__ import annotations

import faulthandler
import os
import time
from typing import Final

import pytest

#: Wall-clock time (``time.time()``) at which the child's stacks are dumped.
DEADLINE_ENV: Final[str] = "CHILD_PYTEST_WATCHDOG_DEADLINE"

_STDERR_FD: int | None = None


def _arm() -> None:
    """Arm, or re-arm, the dump for the time left before the deadline."""
    if _STDERR_FD is None:
        return
    remaining = float(os.environ[DEADLINE_ENV]) - time.time()
    faulthandler.dump_traceback_later(max(remaining, 0.001), file=_STDERR_FD, exit=False)


if DEADLINE_ENV in os.environ:
    _STDERR_FD = os.dup(2)
    _arm()


def pytest_configure(config: pytest.Config) -> None:
    """Re-arm once plugins are configured."""
    _arm()


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config: pytest.Config) -> None:
    """Re-arm as the last thing pytest does before the interpreter exits."""
    _arm()
