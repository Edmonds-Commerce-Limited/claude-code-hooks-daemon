"""Append-only verdict log for handler decisions (Plan 00209).

Field report background (CLAUDE/Plan/00209-field-feedback-daemon-self-observability/
FEEDBACK.md, item #3): the daemon makes hundreds of decisions per session and
persists none of them — no record of which handler fired, on which tool call,
with what verdict, so every interesting question about the daemon ("which
handlers earn their keep?", "what is the real false-positive rate per
handler?") is answerable only by anecdote.

This module writes ``verdicts.jsonl``, one line per handler decision:
``{ts, session, event, tool, handler, verdict, rule, mode, overridden}``.

Design (Plan 00209 Task 2.1): the write happens ONCE, in the daemon
controller, reading ``ChainExecutionResult.decisions`` (populated by
``HandlerChain.execute`` — see ``core/chain.py``) — so every handler's
decision is captured without any handler opting in. The helpers here are
deliberately pure (primitives in, no pydantic/ProjectContext coupling),
mirroring ``daemon/payload_capture.py``, so they are trivially testable and
the server/controller does the config + path wiring.

Retention (Plan 00209 Task 2.4): ``verdicts.jsonl`` is a bounded ROLLING
SAMPLE, using the same ``cap_log_file`` primitive as every other daemon JSONL
log (Plan 00181) — NOT a durable lifetime counter. Plan 00206 hit exactly
this trap: a cap that silently discards the oldest half corrupts any
cumulative statistic derived from it. Statistics reported by
``hooks-daemon verdicts`` (see ``daemon/verdict_report.py``) describe the
RETAINED WINDOW only, and say so explicitly — they are not lifetime totals.
This is a deliberate, documented trade-off (simplicity over a second,
never-truncated counters file), not an oversight.

Override detection (Plan 00209 Task 2.3): handlers that implement the
project's ``MUST_..._BECAUSE=`` escape-hatch convention (``git_stash``,
``root_recursion_guard``, ``plan_workflow``, ``comment_size``,
``comment_changelog``, ``plan_qa_edit``, ...) make ``matches()`` return
``False`` when their own hatch is present, so the bypassed handler never
appears in ``ChainExecutionResult.decisions`` for that event at all — there
is no per-handler record to mark "overridden". Detecting the SHARED
``MUST_<NAME>_BECAUSE=`` shape once, here, still surfaces that an override
happened (a synthetic line with ``handler: None, verdict: "override",
overridden: True``) without needing per-handler opt-in; it just cannot name
which specific handler was bypassed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.core.chain import HandlerVerdict
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.utils.retention import cap_log_file

# Filename for the verdict log, resolved by the caller under the daemon's
# untracked logs dir (mirrors notifications.jsonl / subagent_completions.jsonl).
VERDICT_LOG_FILENAME = "verdicts.jsonl"

# Decisions that represent the handler actively restricting the tool call.
# Everything else (ALLOW, CONTINUE) is advisory for verdict-log purposes —
# this is a DERIVED classification, not each handler's own configured
# block/warn option (no uniform way to read that generically), but it is
# accurate for the two decisions that matter: a DENY/ASK always blocked.
_BLOCKING_DECISIONS = frozenset({Decision.DENY, Decision.ASK})
_MODE_BLOCK = "block"
_MODE_ADVISORY = "advisory"

# The synthetic escape-hatch-override record uses this verdict value — never
# a real Decision member, so it cannot be confused with an actual handler
# decision when the verdict-mix report groups by this field.
_OVERRIDE_VERDICT = "override"

# tool_input keys that carry human/agent-authored text where an escape-hatch
# marker plausibly appears: Bash commands, and Write/Edit file content.
_TEXT_FIELDS: tuple[str, ...] = ("command", "content", "new_string")

# Shared shape of the daemon's MUST_..._BECAUSE escape-hatch convention.
# Two flavours exist across handlers, both matched by this looser shared
# pattern: a shell assignment (git_stash's MUST_STASH_BECAUSE="reason";
# command, root_recursion_guard's MUST_SCAN_ROOT_BECAUSE="...") and an
# inline colon annotation (comment_size's
# MUST_EXCEED_COMMENT_SIZE_BECAUSE: reason, plan_qa_edit's
# MUST_EXCEED_PLAN_SIZE_BECAUSE: reason). Matching both is what lets
# override detection run once here instead of needing one regex import per
# handler.
_ESCAPE_HATCH_PATTERN = re.compile(r"MUST_[A-Z][A-Z0-9_]*_BECAUSE\s*[:=]")


def _extract_escape_hatch_text(hook_input: dict[str, Any]) -> str:
    """Concatenate the tool_input text fields an escape hatch could appear in."""
    tool_input = hook_input.get("tool_input")
    if not isinstance(tool_input, dict):
        return ""
    parts = [value for key in _TEXT_FIELDS if isinstance(value := tool_input.get(key), str)]
    return "\n".join(parts)


def escape_hatch_used(hook_input: dict[str, Any]) -> bool:
    """True when this event's payload contains a ``MUST_..._BECAUSE=`` marker."""
    return bool(_ESCAPE_HATCH_PATTERN.search(_extract_escape_hatch_text(hook_input)))


def _mode_for(decision: Decision) -> str:
    """Derive block/advisory from the decision actually returned this call."""
    return _MODE_BLOCK if decision in _BLOCKING_DECISIONS else _MODE_ADVISORY


def build_verdict_lines(
    *,
    decisions: Sequence[HandlerVerdict],
    hook_input: dict[str, Any],
    event: str,
    tool_name: str,
    session_id: str,
    now: datetime | None = None,
    record_status_events: bool = False,
) -> list[dict[str, Any]]:
    """Build the JSONL-ready dicts for one dispatch's decisions.

    One line per matched handler's own verdict, plus (Task 2.3) one
    additional synthetic line when a ``MUST_..._BECAUSE=`` escape-hatch
    marker is present anywhere in this event's payload — even when
    ``decisions`` is otherwise empty, because the bypassed handler's
    ``matches()`` returned False and so contributed no entry of its own.

    Returns an empty list when there is genuinely nothing to record (no
    matched handlers, no escape hatch) — the caller skips writing entirely.

    Status events are dropped unless ``record_status_events`` is set, because
    they are pure noise in a log whose purpose is "which handlers earn their
    keep?" (Plan 00234). A status handler RENDERS; it has no verdict but
    ``allow``, so its records carry no information — yet they arrive at the
    status line's refresh rate. Measured on this project: 43,929 of 44,180
    retained records were status renders (99.43%), filling the 10 MiB cap in
    **65 minutes**. Excluding them stretches the same cap to roughly 8 days,
    which is the difference between an instrument that can answer the question
    and one that cannot.

    The filter is on the EVENT, not on a ``status-*`` name prefix: what makes
    these records worthless is the event they serve, and a name test would both
    miss a renamed handler and catch an unrelated one.
    """
    if event == EventType.STATUS_LINE.value and not record_status_events:
        return []

    ts = (now or datetime.now(UTC)).isoformat()
    lines: list[dict[str, Any]] = [
        {
            "ts": ts,
            "session": session_id,
            "event": event,
            "tool": tool_name,
            "handler": decision.handler,
            "verdict": decision.decision.value,
            "rule": decision.rule,
            "mode": _mode_for(decision.decision),
            "overridden": False,
        }
        for decision in decisions
    ]

    if escape_hatch_used(hook_input):
        lines.append(
            {
                "ts": ts,
                "session": session_id,
                "event": event,
                "tool": tool_name,
                "handler": None,
                "verdict": _OVERRIDE_VERDICT,
                "rule": None,
                "mode": None,
                "overridden": True,
            }
        )

    return lines


def append_verdicts(
    *,
    enabled: bool,
    decisions: Sequence[HandlerVerdict],
    hook_input: dict[str, Any],
    event: str,
    tool_name: str,
    session_id: str,
    log_dir: Path,
    max_bytes: int,
    retain_bytes: int | None = None,
    record_status_events: bool = False,
) -> Path | None:
    """Append this dispatch's verdict lines to ``<log_dir>/verdicts.jsonl``.

    Fail-open by design is the CALLER's responsibility (mirrors
    ``payload_capture.capture_payload``): this function raises on a genuine
    IO failure so the caller can log and continue rather than let a logging
    failure silently mask itself, but it is never on the safety-decision
    path — handler dispatch has already completed by the time this runs.

    Args:
        enabled: Master toggle; ``False`` is a no-op.
        decisions: Per-handler verdicts from this dispatch.
        hook_input: The raw payload, scanned for an escape-hatch marker.
        event: Hook event name (e.g. "PreToolUse").
        tool_name: Tool name for this event (e.g. "Bash"), may be empty.
        session_id: Session identifier.
        log_dir: Directory verdicts.jsonl is written into.
        max_bytes: Retention cap (Plan 00181 ``cap_log_file``).
        retain_bytes: Bytes to retain on trim (default: ``max_bytes``).
        record_status_events: Include Status renders. Off by default — they
            are 99% of the volume and carry no information (Plan 00234).

    Returns:
        The file written, or ``None`` when disabled or nothing to record.
    """
    if not enabled:
        return None

    lines = build_verdict_lines(
        decisions=decisions,
        hook_input=hook_input,
        event=event,
        tool_name=tool_name,
        session_id=session_id,
        record_status_events=record_status_events,
    )
    if not lines:
        return None

    log_dir.mkdir(parents=True, exist_ok=True)
    target = log_dir / VERDICT_LOG_FILENAME
    with target.open("a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")

    cap_log_file(target, max_bytes=max_bytes, retain_bytes=retain_bytes)
    return target
