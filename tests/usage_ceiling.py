"""Keep the account's live usage out of a synthetic session's verdicts (Plan 00479).

A test that routes an event through the live daemon, or through the real chain
against this checkout's daemon state, reads the account's real usage. While
that usage is over this host's ceiling every NEW session is paused, so a
synthetic session answers with the pause directive instead of the decision of
the handler under test, and the test fails on a fact about the account rather
than about the code.
"""

from __future__ import annotations

import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from claude_code_hooks_daemon.utils.usage_pause import synthetic_session_exemption

#: The live daemon's untracked directory in this self-install checkout.
DAEMON_UNTRACKED_DIR = Path(__file__).resolve().parents[1] / "untracked"


@contextmanager
def exempt_from_usage_ceiling(session_id: str) -> Generator[None]:
    """Exempt ``session_id`` from the live usage ceiling for the block."""
    with synthetic_session_exemption(DAEMON_UNTRACKED_DIR, session_id, now=time.time()):
        yield
