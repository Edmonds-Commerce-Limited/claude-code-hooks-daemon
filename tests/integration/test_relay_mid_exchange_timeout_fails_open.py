"""M7 (Plan 00463 round 9d): a mid-exchange relay timeout fails OPEN today.

The coordinator's ruling for round 9d (PLAN.md's "Round 9" section) moved the
guarantee against a full-suite run to a sink inside pytest itself, precisely
because a Bash-text guard (`subagent_full_qa_blocker`) can never see every
route to a full run. That guarantee only holds if the CHAIN that carries the
verdict cannot itself be turned into an allow by starving it -- and today it
can: `mid_exchange_fail` (`relay/hooks_relay.rs`) explicitly fails OPEN on a
post-connect timeout, writing `{}` to stdout and exiting 0, by design (see its
own doc comment). For a PreToolUse event this is read as "no verdict", which
Claude Code defaults to ALLOW.

This is proven here with a DETERMINISTIC probe, not a wall-clock assertion: a
fake Unix-socket server accepts the connection, reads the full request to EOF,
then deliberately never replies. The relay's own `--timeout-ms` is the only
clock in play, and a short one guarantees the timeout fires every run,
independent of host load.

This is a KNOWN, tracked gap, not a silent one: Plan 00466 N24 ("PreToolUse
denies when the daemon cannot be reached at all") is the active, much larger
effort closing it -- 8+ review rounds in progress at the time this test was
written, touching the relay binary, its build/deploy pipeline and CI asset
baking. Plan 00463 is documented to merge AFTER N24 lands (see PLAN.md's
"Round 9" section) rather than fork a duplicate, narrower fix here. This test
pins the CURRENT (pre-N24) behaviour so that whoever lands N24's fix on this
branch sees it fail and must update it deliberately, rather than the gap
silently persisting unnoticed.
"""

from __future__ import annotations

import json
import socket
import subprocess
import threading
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RELAY_BINARY = _REPO_ROOT / "untracked" / "relay-build" / "hooks-relay-x86_64-unknown-linux-musl"
_TIMEOUT_MS = 500
_SUBPROCESS_TIMEOUT_SECONDS = 15


class _HangingServer:
    """Accepts one connection, reads the request to EOF, then replies never.

    Deliberately distinct from a connect failure: the relay's OWN
    `mid_exchange_fail` fail-open path only fires once it is already
    mid-exchange, so the request must be fully received first.
    """

    def __init__(self, sock_path: Path) -> None:
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.settimeout(10.0)
        self._srv.bind(str(sock_path))
        self._srv.listen(1)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _serve(self) -> None:
        try:
            conn, _ = self._srv.accept()
        except OSError:
            return
        with conn:
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
            # Request fully received (half-close seen). Hold the connection
            # open and reply never, until the test releases us.
            self._stop.wait(20)

    def close(self) -> None:
        self._stop.set()
        self._srv.close()


@pytest.mark.skipif(not _RELAY_BINARY.exists(), reason="no built relay binary on this machine")
def test_a_mid_exchange_timeout_for_a_full_qa_command_still_fails_open(tmp_path: Path) -> None:
    """A positively-seen full-QA command (bare `pytest`), relay times out mid-exchange.

    Expected TODAY: exit 0, empty/`{}` stdout -- fail open, an effective
    ALLOW. This is the exact defect Plan 00466 N24 is fixing; see the module
    docstring for why it is not independently re-fixed here.
    """
    sock_path = tmp_path / "daemon.sock"
    server = _HangingServer(sock_path)
    server.start()
    try:
        payload = (
            json.dumps(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "pytest"},
                }
            ).encode()
            + b"\n"
        )

        result = subprocess.run(
            [str(_RELAY_BINARY), str(sock_path), "--timeout-ms", str(_TIMEOUT_MS)],
            input=payload,
            capture_output=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )
    finally:
        server.close()

    # The relay's own budget fired (not some unrelated fast failure): its
    # stderr names the timeout. Review 10 M2: no wall-clock elapsed-time
    # assertion here -- the server hangs until the relay's own budget forces
    # the timeout, so this message is the proof, not a duration guess.
    assert b"timeout" in result.stderr, result.stderr

    # The defect: exit 0 with an empty/`{}` body is indistinguishable from
    # "no verdict", which a PreToolUse hook consumer defaults to ALLOW.
    assert result.returncode == 0
    assert result.stdout.strip() in (b"", b"{}"), (
        "M7 is now fixed (or the relay's fail-open contract changed) -- "
        "this test's own docstring documents Plan 00466 N24 as the tracked "
        "fix; update or remove this pin rather than leaving it red.",
        result.stdout,
    )
