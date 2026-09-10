r"""Plan 00371 — the running daemon's loaded code matches the working tree.

Regression coverage for the exact incident this plan fixes:
``test_playbook_harness.py`` dispatched a probe through the live daemon
socket, the running daemon still held pre-merge code, and the probe failed
for a reason nothing in the harness could name. `bin/hooks-daemon restart`
made the same probe pass with no code change -- the harness was silently
grading the *deployed* daemon while claiming to grade the working tree.

``tests/acceptance/conftest.py``'s ``daemon_running``/``daemon_socket``
fixtures now perform this comparison as a side effect on every acceptance
run that requests them, so every live-dispatch acceptance file (this one
included) already gets it automatically. This file names the mechanism
directly -- a dedicated, discoverable home for the property, not merely an
implicit side effect of a shared fixture -- and proves it fires on a
mismatch using a REAL daemon-reported fingerprint (not two hand-written test
strings, which is what ``tests/unit/daemon/test_source_fingerprint.py``
already covers).
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.daemon.cli import send_daemon_request
from claude_code_hooks_daemon.daemon.source_fingerprint import (
    compute_current_project_fingerprint,
    describe_fingerprint_mismatch,
)
from tests.acceptance.conftest import REPO_ROOT


def _query_running_fingerprint(socket_path: Path) -> str | None:
    """Ask the live daemon for its own source_fingerprint, or None if it has none."""
    response = send_daemon_request(
        socket_path, {"event": "_system", "hook_input": {"action": "health"}}
    )
    if response is None or "result" not in response:
        return None
    return response["result"].get("source_fingerprint")


class TestRunningDaemonSourceMatchesWorkingTree:
    """The literal regression reproduction."""

    def test_running_daemon_fingerprint_matches_the_working_tree(
        self, daemon_socket: Path
    ) -> None:
        """A fresh daemon's reported fingerprint equals the current on-disk one.

        This is the exact incident, reproduced directly: if the daemon
        gating this very test run is stale, THIS test fails, by name,
        instead of an unrelated probe failing for a reason nothing names.
        """
        running_fingerprint = _query_running_fingerprint(daemon_socket)
        current_fingerprint = compute_current_project_fingerprint(REPO_ROOT)

        assert running_fingerprint is not None, (
            "daemon health response carried no source_fingerprint at all"
        )
        assert running_fingerprint == current_fingerprint, describe_fingerprint_mismatch(
            running_fingerprint, current_fingerprint
        )


class TestDescribeMismatchAgainstARealRunningFingerprint:
    """The negative path, proven against a genuine daemon-reported value."""

    def test_a_deliberately_wrong_current_value_is_named_as_stale(
        self, daemon_socket: Path
    ) -> None:
        """Feed the REAL running fingerprint a synthetic "current" mismatch.

        Proves the comparison mechanism fires on a value a live daemon
        actually reported, not just on two hand-written strings -- without
        touching the real installed source, which would risk corrupting the
        daemon gating this very session.
        """
        running_fingerprint = _query_running_fingerprint(daemon_socket)
        assert running_fingerprint is not None

        bogus_current = "0" * 64  # simulate "the working tree moved on"

        message = describe_fingerprint_mismatch(running_fingerprint, bogus_current)

        assert message is not None
        assert "STALE DAEMON" in message
        assert running_fingerprint[:12] in message
