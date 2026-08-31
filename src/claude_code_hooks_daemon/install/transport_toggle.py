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
import logging
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
from claude_code_hooks_daemon.install.forwarder_generator import (
    load_transport_config,
    regenerate_deployed_hooks,
)
from claude_code_hooks_daemon.install.relay_deploy import (
    deploy_relay_if_configured,
    resolve_relay_binary_path,
)
from claude_code_hooks_daemon.install.transport_verify import (
    ProbeResult,
    resolve_events_dir,
    run_probes,
)
from claude_code_hooks_daemon.version import __version__

logger = logging.getLogger(__name__)

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


_TRANSPORT_BLOCK_LINE = re.compile(r"^(?P<indent>[ \t]*)transport:[ \t]*(?:#.*)?$", re.MULTILINE)
_DAEMON_SECTION_LINE = re.compile(r"^daemon:[ \t]*(?:#.*)?$", re.MULTILINE)

#: The exact YAML an operator must add by hand when seeding cannot place it.
_SEED_YAML = "daemon:\n  transport:\n    relay_enabled: false\n"


def _insert_after_line(content: str, line_match_end: int, insertion: str) -> str:
    """Insert ``insertion`` on its own line directly below the matched line."""
    newline_at = content.find("\n", line_match_end)
    if newline_at == -1:
        return content + "\n" + insertion
    return content[: newline_at + 1] + insertion + content[newline_at + 1 :]


def seed_relay_enabled_line(config_path: Path) -> bool:
    """Seed a missing ``relay_enabled: false`` line (defect D3, canary run 4).

    A fresh client config carries no ``daemon.transport`` block at all, so
    the targeted flip used to refuse with "found 0" — safe but unhelpful for
    the documented client-side toggle. This inserts the key with the shipped
    default (``false``), comment-preservingly: under an existing
    ``transport:`` line when there is exactly one, else as a new
    ``transport:`` block directly under a top-level ``daemon:`` section.
    Anything more ambiguous refuses with the exact YAML to add by hand.

    Returns:
        True when the file was modified; False when the key already exists.
    """
    if not config_path.is_file():
        raise TransportToggleError(f"config file not found: {config_path}")
    content = config_path.read_text()
    if _RELAY_ENABLED_LINE.search(content):
        return False
    transport_matches = list(_TRANSPORT_BLOCK_LINE.finditer(content))
    if len(transport_matches) == 1:
        match = transport_matches[0]
        child_indent = match.group("indent") + "  "
        seeded = _insert_after_line(content, match.end(), f"{child_indent}relay_enabled: false\n")
    elif not transport_matches:
        daemon_match = _DAEMON_SECTION_LINE.search(content)
        if daemon_match is None:
            raise TransportToggleError(
                f"{config_path} has no daemon.transport.relay_enabled key and no "
                f"daemon: section to seed it under — add this to the config "
                f"first:\n{_SEED_YAML}"
            )
        seeded = _insert_after_line(
            content, daemon_match.end(), "  transport:\n    relay_enabled: false\n"
        )
    else:
        raise TransportToggleError(
            f"{config_path} contains {len(transport_matches)} 'transport:' lines — "
            f"cannot seed relay_enabled unambiguously; add this under "
            f"daemon.transport yourself:\n{_SEED_YAML}"
        )
    config_path.write_text(seeded)
    logger.info("seeded daemon.transport.relay_enabled: false into %s", config_path)
    return True


def state_file_path(project_root: Path) -> Path:
    return get_untracked_dir(project_root) / STATE_FILENAME


def read_last_toggle_state(project_root: Path) -> dict[str, Any] | None:
    """The persisted result of the last real toggle, or None."""
    path = state_file_path(project_root)
    if not path.is_file():
        return None
    try:
        loaded: object = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        # A corrupt/unreadable state file must not break `transport status`;
        # surface it and report the honest answer: no trustworthy record.
        logger.warning(
            "transport toggle state file %s is unreadable (%s); reporting no last toggle",
            path,
            exc,
        )
        loaded = None
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
        # Output goes to DEVNULL, never a pipe: the daemonised child inherits
        # this process's stdio, so a captured pipe would make run() wait for
        # the DAEMON's exit, not the CLI's (the daemon-smoke suite's own
        # hard-learned note). Only the exit code is consumed.
        try:
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
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=_RESTART_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            # A hung restart raises rather than returning a code — surface it
            # as a synthetic non-zero exit so the caller's return-value-driven
            # revert path still fires (a raised exception here must never
            # bypass the revert).
            logger.warning(
                "daemon restart timed out after %s seconds for %s",
                _RESTART_TIMEOUT_SECONDS,
                project_root,
            )
            return -1
        return result.returncode

    return restart


def _failure_lines(probes: list[ProbeResult]) -> list[str]:
    return [f"{probe.name}: {probe.detail}" for probe in probes if not probe.passed]


def ensure_relay_binary(project_root: Path) -> str | None:
    """When enabling: make sure the relay binary actually exists (defect D2).

    ``relay_source`` was previously honoured only by the installer's Step 7b,
    so a client whose untracked/bin had no ``hooks-relay`` got guards that
    always fell through to legacy while the forwarder probes still passed —
    a "green" enable with no relay engaged. ``transport on`` is an explicit
    operator request for the relay rung, so an absent binary must either be
    provisioned (via the SAME routine the installer uses, per the configured
    ``relay_source``) or fail the toggle loudly.

    Returns:
        A failure line for the toggle report, or ``None`` when the binary is
        present (or was just provisioned) and executable.
    """
    transport = load_transport_config(project_root)
    binary = resolve_relay_binary_path(project_root, transport)
    if binary.is_file() and os.access(binary, os.X_OK):
        return None
    if transport.relay_source is None:
        return (
            f"relay-binary: {binary} is absent and daemon.transport.relay_source "
            "is null — set relay_source: build|download (or put a relay binary "
            "at that path) before enabling the relay rung"
        )
    # Self-install: the daemon checkout IS the project root; client install:
    # .claude/hooks-daemon/. Both are exactly the untracked dir's parent.
    daemon_dir = get_untracked_dir(project_root).parent
    result = deploy_relay_if_configured(
        daemon_dir, project_root, transport, version_tag=f"v{__version__}"
    )
    if not result.deployed:
        details = "; ".join(result.messages) or "no reason reported"
        return f"relay-binary: provisioning via relay_source={transport.relay_source} failed: {details}"
    logger.info("relay binary provisioned via %s route at %s", result.route, binary)
    return None


def run_toggle(
    project_root: Path,
    *,
    enable: bool,
    restart_fn: Callable[[], int] | None = None,
    verify_fn: Callable[[bool], list[ProbeResult]] | None = None,
    provision_fn: Callable[[], str | None] | None = None,
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
        provision_fn: Relay-binary provisioning check run only when ENABLING,
            returning a failure line or ``None``. Defaults to
            :func:`ensure_relay_binary`.

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

    # Defect D3: a fresh client config has no relay_enabled: line at all —
    # seed the documented default instead of refusing.
    seed_relay_enabled_line(config_path)

    current = read_relay_enabled(config_path)
    if current == enable:
        return ToggleOutcome(action=action, changed=False, verified=None)

    if enable:
        # Defect D2: provisioning runs BEFORE anything is flipped, so a
        # build/download failure leaves the project completely untouched —
        # there is nothing to revert, and the failure is still reported
        # loudly with exit-code semantics identical to a probe failure.
        provision = (
            provision_fn if provision_fn is not None else lambda: ensure_relay_binary(project_root)
        )
        provision_error = provision()
        if provision_error is not None:
            outcome = ToggleOutcome(
                action=action,
                changed=False,
                verified=False,
                failures=[provision_error],
            )
            _write_toggle_state(project_root, outcome)
            return outcome

    failures: list[str] = []
    try:
        set_relay_enabled(config_path, enable)
        regenerate_deployed_hooks(project_root, hooks_dir)
        restart_rc = restart()
        if restart_rc != 0:
            failures.append(f"daemon-restart: exit code {restart_rc}")
        else:
            failures.extend(_failure_lines(verify(enable)))
    except Exception as exc:
        # An exception here (a hung restart's subprocess.TimeoutExpired, an
        # unreadable-file OSError from regenerate, ...) must fall through to
        # the SAME revert path as a return-value failure — never propagate
        # and skip the revert. Reported explicitly, never swallowed.
        logger.warning("transport %s raised before verification completed: %s", action, exc)
        failures.append(f"{type(exc).__name__}: {exc}")

    if not failures:
        outcome = ToggleOutcome(action=action, changed=True, verified=True)
        _write_toggle_state(project_root, outcome)
        return outcome

    # AUTO-REVERT: restore the previous state end-to-end and re-verify it
    # with the same probes — a toggle must never strand a session on a
    # broken transport. Also exception-safe, for the same reason as above.
    revert_verified: bool | None
    try:
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
    except Exception as exc:
        logger.warning("transport %s revert raised an exception: %s", action, exc)
        revert_verified = False
        failures.append(f"revert {type(exc).__name__}: {exc}")

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
        except OSError as exc:
            # Status must still render when the binary is unreadable; say so
            # rather than silently reporting "no digest".
            logger.warning("could not hash relay binary %s: %s", binary, exc)
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
