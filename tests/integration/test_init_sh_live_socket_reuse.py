"""Plan 00127: init.sh start_daemon() must not destroy a live socket.

The legacy ``start_daemon()`` ran ``rm -f "$SOCKET_PATH"`` unconditionally
before spawning the CLI. On the host+container shared-``untracked/`` path this
bash line deletes a LIVE incumbent's socket file before the python liveness
gate ever runs, defeating the core fix. Decision 1 requires the bash layer to
leave a live socket alone and let the python server's liveness-gated unlink be
the single source of truth for stale cleanup.

Verified via static analysis of init.sh (the boot-race suite already covers the
PID-file behaviour; this file guards the socket-unlink change).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INIT_SH = REPO_ROOT / "init.sh"


def _read_init_sh() -> str:
    return INIT_SH.read_text()


def _extract_start_daemon_body() -> str:
    content = _read_init_sh()
    match = re.search(
        r"^start_daemon\(\)\s*\{(.*?)^\}",
        content,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, "start_daemon() not found in init.sh"
    return match.group(1)


def test_start_daemon_does_not_unconditionally_rm_live_socket() -> None:
    """start_daemon() must not unconditionally ``rm -f "$SOCKET_PATH"``.

    The unconditional socket unlink deletes a live incumbent's socket on the
    shared-untracked host+container path. Either remove the line entirely
    (preferred — let the python server's liveness-gated unlink handle stale
    cleanup) or guard it so it only runs on a not-running branch.
    """
    body = _extract_start_daemon_body()
    lines = body.splitlines()

    for idx, line in enumerate(lines):
        # Ignore comment lines (the NOTE explaining the removal references the
        # old command in prose).
        if line.lstrip().startswith("#"):
            continue
        if re.search(r'rm\s+-f\s+"?\$\{?SOCKET_PATH\}?"?', line):
            preceding = "\n".join(lines[max(0, idx - 6) : idx])
            assert "is_daemon_running" in preceding, (
                "start_daemon() unlinks SOCKET_PATH without a not-running "
                'guard. Remove the unconditional `rm -f "$SOCKET_PATH"` so a '
                "live incumbent's socket is never destroyed by the bash layer. "
                "See Plan 00127."
            )


def test_start_daemon_reuses_when_already_running() -> None:
    """start_daemon() must short-circuit (return 0) when is_daemon_running.

    The early-return reuse guard is what keeps a healthy incumbent untouched at
    the bash layer (no spawn, no socket deletion).
    """
    body = _extract_start_daemon_body()
    # The first guard in the function must be an is_daemon_running short-circuit.
    guard = re.search(
        r"if\s+is_daemon_running;\s*then\s*\n\s*return\s+0",
        body,
    )
    assert guard is not None, (
        "start_daemon() must return 0 early when is_daemon_running so a live "
        "shared daemon is reused rather than respawned. See Plan 00127."
    )
