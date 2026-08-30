"""Transport rung availability probe (Plan 00290, DESIGN-socket-relay.md §6.3).

Read-only and cheap — never mutates the filesystem, never spawns the daemon,
never builds or downloads anything. Reports the facts the fallback ladder
needs to decide, at deploy time, which rungs are actually usable on this
machine:

- Is the relay binary present, executable, and (when a release manifest is
  available) digest-verified?
- Is ``nc`` on ``PATH`` and Unix-socket-capable (``-U`` flag advertised)?
- Are the daemon's per-event listeners bound right now (diagnostic only —
  this is a point-in-time snapshot, not a guarantee for the next hook call)?

``render_env_lines`` turns the result into the two deploy-time facts
``hooks-daemon.env`` needs (:doc:`DESIGN-socket-relay.md` §6.3):
``HOOKS_DAEMON_NC_UNIX_CAPABLE`` and a human-readable comment recording
whether each configured rung is actually usable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from claude_code_hooks_daemon.daemon.paths import get_event_socket_dir
from claude_code_hooks_daemon.install.relay_deploy import check_musl_toolchain, read_deployed_route

#: Timeout for the cheap `nc -h` capability probe (subprocess, not a socket).
_NC_HELP_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class TransportProbeResult:
    """Snapshot of transport rung availability on this machine."""

    relay_binary_present: bool
    relay_binary_executable: bool
    #: True = digest matched a release manifest; False = mismatched;
    #: None = no manifest available to check against (unknown, not a failure).
    relay_digest_verified: bool | None
    nc_present: bool
    nc_unix_capable: bool
    event_socket_dir_present: bool
    #: True when a musl-capable rustc toolchain is available (Plan 00290
    #: Phase 5, Task 5.2) — the build-from-source route's own precondition.
    toolchain_present: bool = False
    #: "build"/"download" naming which route deployed the binary currently on
    #: disk (read from its sidecar marker); None when unknown/undeployed.
    deployed_route: str | None = None

    def as_dict(self) -> dict[str, bool | str | None]:
        return asdict(self)


def _verify_digest(binary: Path, sha256sums_path: Path) -> bool | None:
    """Check ``binary``'s sha256 against a ``sha256sum``-format manifest.

    Returns:
        True/False if the manifest exists and names this binary; None if no
        manifest is available (nothing to verify against — not a failure).
    """
    if not sha256sums_path.is_file() or not binary.is_file():
        return None
    try:
        digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    except OSError:
        return None
    for line in sha256sums_path.read_text().splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        recorded_digest, recorded_name = parts
        if recorded_name.strip().lstrip("*") == binary.name:
            return recorded_digest.strip().lower() == digest.lower()
    return None


def _probe_nc() -> tuple[bool, bool]:
    """Return ``(nc_present, nc_unix_capable)``.

    Capability is inferred from ``nc -h``'s own usage/help text advertising a
    ``-U`` flag (Unix-domain-socket mode) — the same signal design §6.3
    specifies. Never attempts an actual connection.
    """
    nc_path = shutil.which("nc")
    if nc_path is None:
        return False, False
    try:
        result = subprocess.run(
            [nc_path, "-h"],
            capture_output=True,
            text=True,
            timeout=_NC_HELP_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError):
        return True, False
    combined = f"{result.stdout}\n{result.stderr}"
    return True, "-U" in combined


def probe_transport(
    *,
    project_root: Path,
    relay_binary: Path,
    sha256sums_path: Path | None = None,
) -> TransportProbeResult:
    """Probe transport rung availability for ``project_root``.

    Args:
        project_root: The target project's root directory.
        relay_binary: Where the relay binary would be deployed (resolved
            caller-side from ``daemon.transport.relay_binary`` override or
            the ``{untracked}/bin/hooks-relay`` default).
        sha256sums_path: Path to a ``sha256sum``-format manifest to verify
            ``relay_binary`` against. Defaults to this repository's own
            ``relay/SHA256SUMS.released`` when omitted (present only from
            Phase 5 onward; absent today, which is reported as "unknown"
            rather than a failure).

    Returns:
        A read-only snapshot of what is actually usable right now.
    """
    if sha256sums_path is None:
        sha256sums_path = Path(__file__).resolve().parents[3] / "relay" / "SHA256SUMS.released"

    relay_present = relay_binary.is_file()
    relay_executable = relay_present and os.access(relay_binary, os.X_OK)
    digest_verified = _verify_digest(relay_binary, sha256sums_path) if relay_present else None

    nc_present, nc_unix_capable = _probe_nc()

    events_dir = get_event_socket_dir(project_root)
    event_socket_dir_present = events_dir.is_dir()

    toolchain_present = check_musl_toolchain()
    deployed_route = read_deployed_route(relay_binary)

    return TransportProbeResult(
        relay_binary_present=relay_present,
        relay_binary_executable=relay_executable,
        relay_digest_verified=digest_verified,
        nc_present=nc_present,
        nc_unix_capable=nc_unix_capable,
        event_socket_dir_present=event_socket_dir_present,
        toolchain_present=toolchain_present,
        deployed_route=deployed_route,
    )


def render_env_lines(
    result: TransportProbeResult, *, relay_enabled: bool, nc_enabled: bool
) -> list[str]:
    """Render the deploy-time facts ``hooks-daemon.env`` needs (design §6.3).

    Only ``HOOKS_DAEMON_NC_UNIX_CAPABLE`` is a fact ``init.sh``'s nc rung
    actually reads at runtime; it is emitted only when ``nc_enabled`` (no
    point recording a fact nothing consults). Empty when neither rung is
    configured on — keeps ``hooks-daemon.env`` untouched for the default
    config, matching the byte-identical-by-default contract.
    """
    if not (relay_enabled or nc_enabled):
        return []
    lines: list[str] = []
    if nc_enabled:
        flag = "1" if result.nc_unix_capable else "0"
        lines.append(f'HOOKS_DAEMON_NC_UNIX_CAPABLE="{flag}"')
    return lines


def render_table(result: TransportProbeResult) -> str:
    digest = (
        "unknown (no manifest)"
        if result.relay_digest_verified is None
        else ("verified" if result.relay_digest_verified else "MISMATCH")
    )
    rows = [
        ("Relay binary present", str(result.relay_binary_present)),
        ("Relay binary executable", str(result.relay_binary_executable)),
        ("Relay binary digest", digest),
        ("Relay binary deployed via", result.deployed_route or "unknown"),
        ("Build toolchain present (musl rustc)", str(result.toolchain_present)),
        ("nc on PATH", str(result.nc_present)),
        ("nc Unix-socket capable (-U)", str(result.nc_unix_capable)),
        ("Per-event socket dir present", str(result.event_socket_dir_present)),
    ]
    width = max(len(label) for label, _ in rows)
    return "\n".join(f"{label:<{width}} : {value}" for label, value in rows)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: ``bin/hooks-daemon transport-probe``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--relay-binary", required=True, type=Path)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table")
    args = parser.parse_args(argv)

    result = probe_transport(
        project_root=args.project_root.resolve(), relay_binary=args.relay_binary
    )
    if args.json:
        print(json.dumps(result.as_dict()))
    else:
        print(render_table(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
