"""Daemon-side hook-payload capture for dogfooding (Plan 00158).

The forwarder is dumb transport; the daemon receives every ``{event,
hook_input}`` envelope. So payload capture — appending the raw ``hook_input``
Claude Code sent to ``<dir>/<event>.jsonl`` — belongs here, driven by the
tracked ``hooks-daemon.yaml`` config and applied by a daemon restart. No Claude
Code relaunch is ever required.

Primary use case: capturing the ``Status`` event reveals the ``session_id`` /
``transcript_path`` behind each status-line render, which is how a background
agent (a full independent session, own ``session_id``, own bar) is told apart
from a Task-tool subagent (shares the parent session, renders only an
agent-panel row) — empirically, from the captured files.

The helpers here are deliberately pure (primitives in, no pydantic/context
coupling) so they are trivially testable; the server does the config wiring.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils.private_io import make_private_dir, open_private_append
from claude_code_hooks_daemon.utils.repo_relative_path import normalise_repo_relative_path
from claude_code_hooks_daemon.utils.secret_redaction import redact_structure

# The ``_system`` envelope is the CLI's own control channel (logs, status,
# health, handler listing) — never a real Claude Code hook event, so it is never
# captured regardless of configuration.
_SYSTEM_EVENT = "_system"

# Subdirectory under the daemon untracked dir used when no explicit dir is set.
_DEFAULT_SUBDIR = "payload-capture"

# tool_input fields that may name a path, checked against the effective
# protected-path globs (Plan 00272 Task 4-5). Mirrors the guard's own field
# set so a residual-route read (one the guard's deny rule missed, or an
# already-ALLOWed metadata/consumer exemption) never lands the protected
# file's path -- let alone its content -- verbatim in this dogfooding
# capture.
_TOOL_INPUT_PATH_FIELDS: tuple[str, ...] = ("file_path", "notebook_path", "path")
_TOOL_INPUT_KEY = "tool_input"
_COMMAND_KEY = "command"

logger = logging.getLogger(__name__)


def _touches_protected_path(hook_input: dict[str, Any], patterns: tuple[str, ...]) -> bool:
    """True when ``hook_input`` names (or Bash-mentions) a protected path.

    Deliberately conservative and cheap: reuses the SAME matching primitives
    the guard itself uses (single source of truth), so this can never
    disagree with what the guard would have denied. A false positive here
    only means one MORE event is excluded from capture -- never a leak.
    """
    if not patterns:
        return False
    tool_input = hook_input.get(_TOOL_INPUT_KEY)
    if not isinstance(tool_input, dict):
        return False
    for field in _TOOL_INPUT_PATH_FIELDS:
        value = tool_input.get(field)
        if isinstance(value, str) and value and sfm.path_is_protected(value, patterns):
            return True
    command = tool_input.get(_COMMAND_KEY)
    if isinstance(command, str) and command:
        return sfm.find_protected_mention(command, patterns) is not None
    return False


def resolve_capture_dir(configured_dir: str | None, untracked_dir: Path) -> Path:
    """Resolve the capture directory.

    Args:
        configured_dir: Explicit directory from config, or ``None`` for default.
        untracked_dir: The daemon's untracked dir (default parent), used both
            as the repository root for a relative ``configured_dir`` and as
            the fallback when none is configured.

    Returns:
        The directory capture files are written under. When ``configured_dir``
        is falsy, ``<untracked_dir>/payload-capture`` is used (never ``/tmp`` —
        runtime files stay in the daemon's untracked area). An absolute or
        home-relative ``configured_dir`` (Plan 00303: config carries zero
        absolute paths) is rejected -- logged and treated as unset, never
        raised, matching this module's fail-open/advisory contract.
    """
    if configured_dir:
        try:
            relative = normalise_repo_relative_path(configured_dir, "payload_capture.dir")
        except ValueError as exc:
            logger.warning("Ignoring payload_capture.dir: %s", exc)
        else:
            return untracked_dir / relative
    return untracked_dir / _DEFAULT_SUBDIR


def _safe_event_name(event: str) -> str:
    """Sanitise an event name into a safe single-path-segment filename stem."""
    cleaned = "".join(c if (c.isalnum() or c in "-_") else "_" for c in event)
    return cleaned or "unknown"


def capture_payload(
    *,
    enabled: bool,
    events: list[str],
    capture_dir: Path,
    event: str,
    hook_input: dict[str, Any],
    secret_terms: tuple[str, ...] = (),
    protected_patterns: tuple[str, ...] = (),
) -> Path | None:
    """Append ``hook_input`` as one JSON line to ``<capture_dir>/<event>.jsonl``.

    Args:
        enabled: Master toggle; when ``False`` this is a no-op.
        events: Optional allow-list of event names. Empty = capture all events;
            otherwise only events in the list are captured.
        capture_dir: Directory to write per-event JSONL files into.
        event: The hook event name (e.g. ``"Status"``, ``"PreToolUse"``).
        hook_input: The raw payload Claude Code sent for this event.
        secret_terms: Terms from the ``sensitive_content`` handler's secret
            word list (Plan 00201). Every occurrence in any string value —
            however deeply nested — is replaced before writing, so a secret
            pasted into a Write/Edit payload can never survive into this
            dogfooding capture file. Empty (default) is a no-op, preserving
            prior behaviour for callers that do not pass it.
        protected_patterns: The effective protected-path globs from the
            guard's config (Plan 00272 Task 4-5). When ``hook_input`` names
            or Bash-mentions a matching path, the WHOLE event is excluded
            from capture (not written at all) rather than redacted — the
            guard's own patterns tell us nothing about a file's CONTENT, so
            there is nothing safe to write back for the matched event.
            Empty (default) is a no-op, preserving prior behaviour.

    Returns:
        The file written, or ``None`` when capture was disabled, the event was
        skipped (``_system`` control channel, or not in the ``events``
        allow-list), or the payload named a protected path.

    Raises:
        OSError: If the directory or file cannot be written. The caller decides
            how to react (the server logs and continues — best-effort, never
            silently swallowed).
    """
    if not enabled:
        return None
    if event == _SYSTEM_EVENT:
        return None
    if events and event not in events:
        return None
    if _touches_protected_path(hook_input, protected_patterns):
        return None

    payload = redact_structure(hook_input, secret_terms) if secret_terms else hook_input

    # Plan 00239: owner-only. These files hold RAW hook payloads — including the
    # bodies of every Write/Edit — so they are the most sensitive thing the daemon
    # writes, and the explicit mode backs up the daemon umask rather than trusting
    # it alone.
    make_private_dir(capture_dir)
    target = capture_dir / f"{_safe_event_name(event)}.jsonl"
    with open_private_append(target) as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return target
