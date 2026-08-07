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
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.utils.secret_redaction import redact_structure

# The ``_system`` envelope is the CLI's own control channel (logs, status,
# health, handler listing) — never a real Claude Code hook event, so it is never
# captured regardless of configuration.
_SYSTEM_EVENT = "_system"

# Subdirectory under the daemon untracked dir used when no explicit dir is set.
_DEFAULT_SUBDIR = "payload-capture"


def resolve_capture_dir(configured_dir: str | None, untracked_dir: Path) -> Path:
    """Resolve the capture directory.

    Args:
        configured_dir: Explicit directory from config, or ``None`` for default.
        untracked_dir: The daemon's untracked dir (default parent).

    Returns:
        The directory capture files are written under. When ``configured_dir``
        is falsy, ``<untracked_dir>/payload-capture`` is used (never ``/tmp`` —
        runtime files stay in the daemon's untracked area).
    """
    if configured_dir:
        return Path(configured_dir).expanduser()
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

    Returns:
        The file written, or ``None`` when capture was disabled or the event was
        skipped (``_system`` control channel, or not in the ``events`` allow-list).

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

    payload = redact_structure(hook_input, secret_terms) if secret_terms else hook_input

    capture_dir.mkdir(parents=True, exist_ok=True)
    target = capture_dir / f"{_safe_event_name(event)}.jsonl"
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return target
