"""Send one hand-built hook payload through the project's entry point, marked (Plan 00466 N12).

Probing a handler by piping a payload into ``.claude/hooks/<event>`` is the
fastest way to read its verdict, and every such dispatch lands in
``verdicts.jsonl`` beside a real agent's. The Plan 00467 plugin audit did
exactly that with unmarked payloads, under session ids no rule recognises, so
``synthetic_traffic`` recorded the probes as REAL — including the
orchestrator-simulate records Plan 00418's enforcement decision is read from.

``hooks-daemon probe`` removes the step a prober can forget: it sets
:data:`~claude_code_hooks_daemon.daemon.synthetic_traffic.SYNTHETIC_SOURCE_FIELD`
to :data:`~claude_code_hooks_daemon.daemon.synthetic_traffic.MANUAL_PROBE`
before the event leaves. A caller that already marked its payload keeps its
own value, because the producer is the one party that knows what it is.

The dispatch goes through the PRODUCTION forwarder as a subprocess, the same
route the acceptance harness uses, so the verdict is the one the daemon would
really give — relay or bash transport, whichever the project runs.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants.events import EventIDMeta, wired_event_metas
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core.handler_scope import event_supports_scope
from claude_code_hooks_daemon.daemon.playbook_harness import (
    daemon_error,
    wrapper_unreachable_reason,
)
from claude_code_hooks_daemon.daemon.synthetic_traffic import (
    MANUAL_PROBE,
    SYNTHETIC_SOURCE_FIELD,
    classify_synthetic,
)

#: A wrapper that finds no live daemon starts one before answering, so the
#: bound covers a startup as well as a slow request.
PROBE_TIMEOUT_SECONDS: Final[int] = Timeout.DAEMON_STARTUP + Timeout.REQUEST_LONG

#: Length of the random suffix on a default probe session id.
_SESSION_SUFFIX_LENGTH: Final[int] = 8

#: The decision a response with no decision at all stands for. A handler
#: chain in which nothing matched answers ``{}``; that is an allow by silence.
_SILENT_DECISION: Final[str] = "allow"


class ProbeInputError(ValueError):
    """The probe was not sent, because what it was asked to send is wrong."""


@dataclass(frozen=True)
class ProbeOutcome:
    """What the entry point did with the event: its exit code and both streams."""

    returncode: int
    stdout: str
    stderr: str


def resolve_probe_event(name: str) -> EventIDMeta:
    """The wired event ``name`` means, in any spelling a surface already uses.

    ``PreToolUse`` (the payload's own spelling), ``pre-tool-use`` (the
    forwarder's file name) and ``pre_tool_use`` (the config key) all name the
    same event. ``Status``, the status line's wire name, resolves too.
    """
    for meta in wired_event_metas():
        spellings = {meta.json_key, meta.bash_key, meta.config_key, meta.wire_key.value}
        if name in spellings:
            return meta
    valid = ", ".join(meta.json_key for meta in wired_event_metas())
    raise ProbeInputError(f"unknown hook event {name!r}. Valid events: {valid}")


def probe_session_id() -> str:
    """A fresh session per probe, so a once-per-session handler answers as on a first fire."""
    return f"{MANUAL_PROBE}-{uuid.uuid4().hex[:_SESSION_SUFFIX_LENGTH]}"


def build_probe_event(
    payload: object,
    *,
    event: EventIDMeta,
    project_root: Path,
    session_id: str,
) -> dict[str, Any]:
    """The event to send: the caller's payload, marked and framed like Claude Code's.

    Framing the caller left out is filled in (``hook_event_name``,
    ``session_id``, ``cwd``); framing the caller supplied is kept, so a
    prober can choose a session to probe a repeat fire.

    Raises:
        ProbeInputError: The payload is not a JSON object, names a different
            event, or carries a marker the classifier would ignore. Sending
            that last one would record the probe as real traffic, which is
            the defect this helper exists to prevent.
    """
    if not isinstance(payload, dict):
        raise ProbeInputError(f"the payload must be a JSON object, not {type(payload).__name__}")
    named = payload.get("hook_event_name")
    accepted = {event.json_key, event.wire_key.value}
    if named is not None and named not in accepted:
        raise ProbeInputError(
            f"the payload names hook_event_name {named!r}, but it would be sent to the "
            f"{event.json_key} entry point"
        )
    if SYNTHETIC_SOURCE_FIELD in payload:
        marker = payload[SYNTHETIC_SOURCE_FIELD]
        if classify_synthetic(marker=marker, session_id=None) is None:
            raise ProbeInputError(
                f"{SYNTHETIC_SOURCE_FIELD} must be a non-empty string naming the producer, "
                f"got {marker!r}; omit it and the probe is marked {MANUAL_PROBE!r}"
            )

    hook_event: dict[str, Any] = dict(payload)
    hook_event.setdefault("hook_event_name", event.json_key)
    hook_event.setdefault("session_id", session_id)
    hook_event.setdefault("cwd", str(project_root))
    hook_event.setdefault(SYNTHETIC_SOURCE_FIELD, MANUAL_PROBE)
    return hook_event


def entry_point_for(project_root: Path, event: EventIDMeta) -> Path:
    """The project's forwarder for ``event``: ``.claude/hooks/<bash_key>``.

    Raises:
        ProbeInputError: The forwarder is not there, so there is nothing to probe.
    """
    entry = project_root / ".claude" / "hooks" / event.bash_key
    if not entry.is_file():
        raise ProbeInputError(
            f"no hook entry point at {entry} (.claude/hooks/{event.bash_key}); "
            "is the daemon installed in this project?"
        )
    return entry


def dispatch_probe(
    entry_point: Path,
    hook_event: Mapping[str, Any],
    *,
    project_root: Path,
    timeout: float = PROBE_TIMEOUT_SECONDS,
) -> ProbeOutcome:
    """Pipe ``hook_event`` into the entry point, exactly as Claude Code does.

    Raises:
        subprocess.TimeoutExpired: The entry point did not answer in time.
    """
    result = subprocess.run(
        ["bash", str(entry_point)],
        input=json.dumps(dict(hook_event)),
        capture_output=True,
        text=True,
        cwd=str(project_root),
        timeout=timeout,
        check=False,
    )
    return ProbeOutcome(result.returncode, result.stdout or "", result.stderr or "")


def response_decision(payload: Mapping[str, Any]) -> str:
    """The decision a hook response carries, or ``""`` when it carries none."""
    hook_specific = payload.get("hookSpecificOutput") or {}
    return str(hook_specific.get("permissionDecision") or payload.get("decision") or "")


def response_text(payload: Mapping[str, Any]) -> str:
    """Every place a handler's message can land, concatenated.

    A deny reason, an advisory context and a system message are different
    keys, and a reader wants all of them.
    """
    hook_specific = payload.get("hookSpecificOutput") or {}
    parts = [
        hook_specific.get("permissionDecisionReason"),
        hook_specific.get("additionalContext"),
        payload.get("reason"),
        payload.get("systemMessage"),
    ]
    return "\n".join(str(part) for part in parts if part)


def render_verdict(
    *,
    event: EventIDMeta,
    entry_point: Path,
    hook_event: Mapping[str, Any],
    outcome: ProbeOutcome,
) -> tuple[int, str]:
    """Report what the daemon decided, and the exit code the CLI should return.

    0 means the daemon answered, whatever it decided. 1 means it gave no
    verdict at all: the wrapper never reached it, it rejected the event, or
    its answer was not JSON. Reading any of those as an allow would report a
    handler as passing when it was never asked.

    The exit code of the entry point itself is not the test: the Stop
    forwarder exits 2 on a block, which is a verdict, not a failure.
    """
    header = [
        f"probe: {event.json_key} -> {entry_point}",
        f"{SYNTHETIC_SOURCE_FIELD}: {hook_event.get(SYNTHETIC_SOURCE_FIELD)}",
        f"session_id: {hook_event.get('session_id')}",
    ]
    if event_supports_scope(event.json_key):
        # `scope_admits` refuses a synthetic event for MAIN and SUB, so an
        # allow here says nothing about those handlers. Measured on Stop: `{}`
        # marked, a block unmarked.
        header.append(
            "note: handlers scoped MAIN or SUB never see a marked probe, so their "
            "verdict is not in this answer (CLAUDE/DEBUGGING_HOOKS.md)"
        )
    unreachable = wrapper_unreachable_reason(outcome.stderr)
    if unreachable is not None:
        return 1, "\n".join([*header, f"error: the daemon was not reached: {unreachable}"])

    raw = outcome.stdout.strip()
    if event.raw_stdout:
        return 0, "\n".join([*header, "response (raw):", raw])
    if not raw:
        return 0, "\n".join([*header, f"decision: {_SILENT_DECISION} (no response)"])
    try:
        response = json.loads(raw)
    except json.JSONDecodeError:
        return 1, "\n".join([*header, f"error: the response was not JSON: {raw}"])
    if not isinstance(response, dict):
        return 1, "\n".join([*header, f"error: the response was not a JSON object: {raw}"])

    rejected = daemon_error(response)
    if rejected is not None:
        return 1, "\n".join([*header, f"error: the daemon rejected the event: {rejected}"])

    lines = [*header, f"decision: {response_decision(response) or _SILENT_DECISION}"]
    text = response_text(response)
    if text:
        lines.extend(["reason:", text])
    lines.append(f"response: {raw}")
    return 0, "\n".join(lines)
