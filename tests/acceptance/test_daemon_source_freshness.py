r"""Plans 00371, 00415 — the running daemon's loaded code and bound config match the working tree.

Regression coverage for the exact incident Plan 00371 fixed:
``test_playbook_harness.py`` dispatched a probe through the live daemon
socket, the running daemon still held pre-merge code, and the probe failed
for a reason nothing in the harness could name. `bin/hooks-daemon restart`
made the same probe pass with no code change -- the harness was silently
grading the *deployed* daemon while claiming to grade the working tree.
Plan 00415 extended the same property to the config the daemon bound at
startup, which a code-only fingerprint could not see.

``tests/acceptance/conftest.py``'s ``daemon_running``/``daemon_socket``
fixtures now perform this comparison as a side effect on every acceptance
run that requests them, so every live-dispatch acceptance file (this one
included) already gets it automatically. This file names the mechanism
directly -- a dedicated, discoverable home for the property, not merely an
implicit side effect of a shared fixture -- and proves it fires on a
mismatch using a REAL daemon-reported payload (not hand-written test
strings, which is what ``tests/unit/daemon/test_config_fingerprint.py``
already covers).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.daemon.cli import send_daemon_request
from claude_code_hooks_daemon.daemon.source_fingerprint import (
    compute_current_project_fingerprints,
    describe_daemon_staleness,
)
from tests.acceptance.conftest import REPO_ROOT

_BOGUS_FINGERPRINT = "0" * 64  # simulate "the working tree moved on"


def _query_running_health(socket_path: Path) -> dict[str, Any] | None:
    """Ask the live daemon for its whole health payload, or None if it gave none."""
    response = send_daemon_request(
        socket_path, {"event": "_system", "hook_input": {"action": "health"}}
    )
    if response is None or "result" not in response:
        return None
    result: dict[str, Any] = response["result"]
    return result


class TestRunningDaemonMatchesWorkingTree:
    """The literal regression reproduction."""

    def test_running_daemon_matches_the_working_tree(self, daemon_socket: Path) -> None:
        """A fresh daemon's reported code AND config match what is on disk now.

        If the daemon gating this very test run is stale in either half, THIS
        test fails, by name, instead of an unrelated probe failing for a
        reason nothing names.
        """
        health = _query_running_health(daemon_socket)
        current = compute_current_project_fingerprints(REPO_ROOT)

        assert health is not None, "daemon returned no health payload at all"
        assert describe_daemon_staleness(health, current) is None, describe_daemon_staleness(
            health, current
        )


class TestStalenessAgainstARealRunningPayload:
    """The negative paths, proven against a genuine daemon-reported payload.

    A synthetic "current" value stands in for an edit on disk, so neither the
    installed source nor the config gating this session is touched.
    """

    def test_moved_code_is_named_as_stale_code(self, daemon_socket: Path) -> None:
        health = _query_running_health(daemon_socket)
        current = replace(
            compute_current_project_fingerprints(REPO_ROOT), source=_BOGUS_FINGERPRINT
        )

        message = describe_daemon_staleness(health, current)

        assert message is not None
        assert "STALE DAEMON" in message
        assert "loaded code" in message

    def test_moved_config_is_named_as_stale_config(self, daemon_socket: Path) -> None:
        health = _query_running_health(daemon_socket)
        current = replace(
            compute_current_project_fingerprints(REPO_ROOT), config=_BOGUS_FINGERPRINT
        )

        message = describe_daemon_staleness(health, current)

        assert message is not None
        assert "STALE DAEMON" in message
        assert "config" in message
        assert "loaded code" not in message
