"""Atomic, verified, auto-reverting transport toggle (Plan 00294).

Toggling ``daemon.transport.relay_enabled`` was a three-step manual dance
(config edit, forwarder regeneration, daemon restart) and every mis-sequenced
step during the Plan 00290 dogfood smeared a broken window across live
sessions. :func:`run_toggle` performs the whole sequence as ONE operation —
config flip -> forwarder regeneration -> daemon restart -> real-context
verification (:mod:`transport_verify`) — and AUTO-REVERTS the previous state
end-to-end on any verification failure, re-verifying the revert with the same
probes. A toggle can never strand a session on a broken transport.

The config flip is a TARGETED LINE EDIT of the ``relay_enabled:`` value, not
a YAML load/dump round-trip: the project config carries load-bearing comment
blocks (this repo's own EMERGENCY-suspension note among them) that a
serialising writer would destroy. The edit requires exactly one
``relay_enabled:`` line in the file and preserves every other byte,
including a trailing comment on the value line itself.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re

# SECURITY: subprocess runs only [sys.executable, -m, <this package's CLI>,
# ...] with a fixed argument list, no shell, no user input.
import subprocess  # nosec B404
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.daemon.paths import get_untracked_dir
from claude_code_hooks_daemon.install.forwarder_generator import regenerate_deployed_hooks
from claude_code_hooks_daemon.install.transport_verify import (
    ProbeResult,
    resolve_events_dir,
    run_probes,
)

#: The last toggle's verification result, persisted alongside the daemon's
#: other state in its untracked dir so ``transport status`` can report it.
STATE_FILENAME = "transport-toggle-state.json"

#: Daemon restart budget, seconds — stop + start + verification inside
#: ``cmd_restart`` all fit comfortably; a hang must not strand the toggle.
_RESTART_TIMEOUT_SECONDS = 120

_RELAY_ENABLED_LINE = re.compile(
    r"^(?P<prefix>\s*relay_enabled\s*:\s*)(?P<value>true|false)(?P<suffix>\s*(?:#.*)?)$",
    re.MULTILINE,
)


class TransportToggleError(Exception):
    """A toggle precondition failed (missing/ambiguous config)."""


@dataclass(frozen=True)
class ToggleOutcome:
    """The result of one ``transport on``/``transport off`` invocation."""

    action: str
    changed: bool
    #: True/False = verification ran and passed/failed; None = no-op toggle,
    #: nothing to verify.
    verified: bool | None
    failures: list[str] = field(default_factory=list)
    reverted: bool = False
    revert_verified: bool | None = None

    @property
    def succeeded(self) -> bool:
        return self.verified is None or self.verified

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "changed": self.changed,
            "verified": self.verified,
            "failures": list(self.failures),
            "reverted": self.reverted,
            "revert_verified": self.revert_verified,
        }


def _config_path(project_root: Path) -> Path:
    return project_root / ".claude" / "hooks-daemon.yaml"


def _match_relay_enabled(config_path: Path) -> re.Match[str]:
    if not config_path.is_file():
        raise TransportToggleError(f"config file not found: {config_path}")
    content = config_path.read_text()
    matches = list(_RELAY_ENABLED_LINE.finditer(content))
    if len(matches) != 1:
        raise TransportToggleError(
            f"expected exactly one 'relay_enabled:' line in {config_path}, "
            f"found {len(matches)} — refusing a targeted edit it cannot make safely"
        )
    return matches[0]


def read_relay_enabled(config_path: Path) -> bool:
    """Read the ``relay_enabled`` value via the same targeted-line contract
    the flip uses, so read and write can never disagree on which line rules."""
    return _match_relay_enabled(config_path).group("value") == "true"


def set_relay_enabled(config_path: Path, enabled: bool) -> bool:
    """Flip the ``relay_enabled:`` value in place, preserving every other byte.

    Returns:
        True when the file changed; False when it already held ``enabled``.
    """
    match = _match_relay_enabled(config_path)
    new_value = "true" if enabled else "false"
    if match.group("value") == new_value:
        return False
    content = config_path.read_text()
    replaced = (
        content[: match.start()]
        + match.group("prefix")
        + new_value
        + match.group("suffix")
        + content[match.end() :]
    )
    config_path.write_text(replaced)
    return True


def state_file_path(project_root: Path) -> Path:
    return get_untracked_dir(project_root) / STATE_FILENAME


def read_last_toggle_state(project_root: Path) -> dict[str, Any] | None:
    """The persisted result of the last real toggle, or None."""
    path = state_file_path(project_root)
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _write_toggle_state(project_root: Path, outcome: ToggleOutcome) -> None:
    path = state_file_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = outcome.as_dict()
    record["timestamp"] = datetime.datetime.now(datetime.UTC).isoformat()
    path.write_text(json.dumps(record, indent=2) + "\n")


def _default_restart_fn(project_root: Path) -> Callable[[], int]:
    def restart() -> int:
        # SECURITY: fixed argv — this interpreter, this package's CLI, a
        # resolved project root. No shell, no user input.
        result = subprocess.run(  # nosec B603
            [
                sys.executable,
                "-m",
                "claude_code_hooks_daemon.daemon.cli",
                "--project-root",
                str(project_root),
                "restart",
            ],
            cwd=project_root,
            capture_output=True,
            timeout=_RESTART_TIMEOUT_SECONDS,
        )
        return result.returncode

    return restart


def _failure_lines(probes: list[ProbeResult]) -> list[str]:
    return [f"{probe.name}: {probe.detail}" for probe in probes if not probe.passed]


def run_toggle(
    project_root: Path,
    *,
    enable: bool,
    restart_fn: Callable[[], int] | None = None,
    verify_fn: Callable[[bool], list[ProbeResult]] | None = None,
) -> ToggleOutcome:
    """Toggle the relay transport, verified, with auto-revert on failure.

    Args:
        project_root: The project whose transport is being toggled.
        enable: Target ``relay_enabled`` value.
        restart_fn: Daemon restart, returning its exit code. Injectable for
            tests; defaults to this package's own ``restart`` CLI as a
            subprocess against ``project_root``.
        verify_fn: Verification pass for an expected relay state, returning
            probe results. Defaults to :func:`transport_verify.run_probes`.

    Returns:
        The outcome; ``succeeded`` is False whenever verification failed —
        even when the auto-revert restored and re-verified the prior state.
    """
    config_path = _config_path(project_root)
    hooks_dir = project_root / ".claude" / "hooks"
    action = "on" if enable else "off"
    restart = restart_fn if restart_fn is not None else _default_restart_fn(project_root)
    verify = (
        verify_fn
        if verify_fn is not None
        else lambda expect_relay: run_probes(project_root, hooks_dir, expect_relay=expect_relay)
    )

    current = read_relay_enabled(config_path)
    if current == enable:
        return ToggleOutcome(action=action, changed=False, verified=None)

    failures: list[str] = []
    set_relay_enabled(config_path, enable)
    regenerate_deployed_hooks(project_root, hooks_dir)
    restart_rc = restart()
    if restart_rc != 0:
        failures.append(f"daemon-restart: exit code {restart_rc}")
    else:
        failures.extend(_failure_lines(verify(enable)))

    if not failures:
        outcome = ToggleOutcome(action=action, changed=True, verified=True)
        _write_toggle_state(project_root, outcome)
        return outcome

    # AUTO-REVERT: restore the previous state end-to-end and re-verify it
    # with the same probes — a toggle must never strand a session on a
    # broken transport.
    set_relay_enabled(config_path, current)
    regenerate_deployed_hooks(project_root, hooks_dir)
    revert_restart_rc = restart()
    if revert_restart_rc != 0:
        revert_verified = False
        failures.append(f"revert daemon-restart: exit code {revert_restart_rc}")
    else:
        revert_failures = _failure_lines(verify(current))
        revert_verified = not revert_failures
        failures.extend(f"revert {line}" for line in revert_failures)

    outcome = ToggleOutcome(
        action=action,
        changed=True,
        verified=False,
        failures=failures,
        reverted=True,
        revert_verified=revert_verified,
    )
    _write_toggle_state(project_root, outcome)
    return outcome


def _relay_binary_facts(project_root: Path, relay_binary_override: str | None) -> dict[str, Any]:
    binary = (
        Path(relay_binary_override)
        if relay_binary_override
        else get_untracked_dir(project_root) / "bin" / "hooks-relay"
    )
    present = binary.is_file()
    sha256 = ""
    if present:
        try:
            sha256 = hashlib.sha256(binary.read_bytes()).hexdigest()
        except OSError:
            sha256 = ""
    return {
        "path": str(binary),
        "present": present,
        "executable": present and os.access(binary, os.X_OK),
        "sha256": sha256,
    }


def status_snapshot(project_root: Path) -> dict[str, Any]:
    """The facts ``transport status`` reports, as one JSON-able snapshot."""
    from claude_code_hooks_daemon.install.forwarder_generator import load_transport_config

    transport = load_transport_config(project_root)
    binary_facts = _relay_binary_facts(project_root, transport.relay_binary)

    if transport.relay_enabled and binary_facts["executable"]:
        rung = "relay"
    elif transport.nc_enabled:
        rung = "nc"
    else:
        rung = "bash+python3"

    events_dir = resolve_events_dir(project_root)
    listener_count = 0
    if events_dir.is_dir():
        listener_count = sum(1 for path in events_dir.glob("*.sock") if path.is_socket())

    return {
        "relay_enabled": transport.relay_enabled,
        "nc_enabled": transport.nc_enabled,
        "rung": rung,
        "events_dir": str(events_dir),
        "listener_count": listener_count,
        "relay_binary": binary_facts,
        "last_toggle": read_last_toggle_state(project_root),
    }


def render_status(snapshot: dict[str, Any]) -> str:
    """Human-readable ``transport status`` table."""
    binary = snapshot["relay_binary"]
    digest = binary["sha256"][:12] if binary["sha256"] else "n/a"
    last = snapshot["last_toggle"]
    if last is None:
        last_line = "never toggled via this command"
    else:
        verdict = "verified" if last.get("verified") else "FAILED"
        reverted = " (auto-reverted)" if last.get("reverted") else ""
        last_line = (
            f"{last.get('timestamp', '?')} transport {last.get('action', '?')}: {verdict}{reverted}"
        )
    rows = [
        ("relay_enabled", str(snapshot["relay_enabled"])),
        ("nc_enabled", str(snapshot["nc_enabled"])),
        ("Active rung", str(snapshot["rung"])),
        ("Per-event listeners", str(snapshot["listener_count"])),
        ("Events dir", str(snapshot["events_dir"])),
        ("Relay binary", binary["path"]),
        ("Relay binary present", str(binary["present"])),
        ("Relay binary executable", str(binary["executable"])),
        ("Relay binary sha256", digest),
        ("Last toggle", last_line),
    ]
    width = max(len(label) for label, _ in rows)
    return "\n".join(f"{label:<{width}} : {value}" for label, value in rows)
