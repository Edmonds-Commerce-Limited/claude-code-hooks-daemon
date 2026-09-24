"""Telling synthetic probe traffic from a real agent session (Plan 00418).

``verdicts.jsonl`` receives every handler decision the daemon makes, and not
all of them come from an agent. The acceptance playbook harness dispatches
hundreds of fabricated events per run, and the forwarder's socket integration
test dispatches a handful more. Nothing on the written line said which was
which, so any figure derived from the log silently blended a harness with a
workflow — and passed review, because nothing required the two to be told
apart. On this project's own log 2,717 of 5,396 records (50%) were synthetic,
and the blend also moved a conclusion: the probes are single-head Bash
fixtures, which dragged the measured "compound command" share down from 93%
to 79%.

**Two ways in, and the precedence matters.**

1. A producer MARKS its own events with :data:`SYNTHETIC_SOURCE_FIELD`. This
   is the truthful route — the harness is the one party that knows it is a
   harness — and it is checked first.
2. A known synthetic SESSION SHAPE is recognised. This is the fallback: it
   classifies the window written before the marker existed, and covers a
   producer whose events this repository does not construct.

**An unmarked, unrecognised session is REAL.** A dispatch with no session id
at all (recorded as ``default``) is real too. Guessing the other way would
discard an agent's own traffic on no evidence, which is precisely the failure
the record exists to avoid.

The predicate lives here, once, so the writer, the report and any handler that
must decline to act on a probe cannot disagree about what a probe is.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from claude_code_hooks_daemon.constants.protocol import HookInputField

#: Field a producer sets on its own hook events to declare them synthetic.
#: The VALUE names the producer, so the report can attribute what it set aside.
SYNTHETIC_SOURCE_FIELD: Final[str] = "synthetic_source"

#: Field the verdict log writes on each record. Named differently from the
#: event field because a record is not an event: it already renames
#: ``session_id`` to ``session``, and a reader of the log should not have to
#: know the event schema.
VERDICT_SYNTHETIC_FIELD: Final[str] = "synthetic"

#: The acceptance-playbook harness (``daemon/playbook_harness.py``).
PLAYBOOK_PROBE: Final[str] = "playbook-probe"

#: The forwarder's socket-stdin integration test.
SOCKET_STDIN_TEST: Final[str] = "socket-stdin-test"

#: Session-id prefixes that identify a synthetic producer. A prefix rather
#: than an exact id because the harness mints one session PER PROBE PER RUN.
_SESSION_PREFIXES: Final[tuple[tuple[str, str], ...]] = ((f"{PLAYBOOK_PROBE}-", PLAYBOOK_PROBE),)

#: Session ids that identify a synthetic producer exactly.
_SESSION_EXACT: Final[dict[str, str]] = {SOCKET_STDIN_TEST: SOCKET_STDIN_TEST}


def _source_for_session(session_id: object) -> str | None:
    """The synthetic producer a session id names, or None when it names none."""
    if not isinstance(session_id, str) or not session_id:
        return None
    exact = _SESSION_EXACT.get(session_id)
    if exact is not None:
        return exact
    for prefix, source in _SESSION_PREFIXES:
        if session_id.startswith(prefix):
            return source
    return None


def classify_synthetic(*, marker: object, session_id: object) -> str | None:
    """Name the synthetic producer behind this traffic, or None when it is real.

    Args:
        marker: The producer's own declaration, if it made one. Only a
            non-empty ``str`` counts — the value becomes a label in a log, so
            stringifying an arbitrary object here would turn the field into a
            channel for whatever a caller happened to pass.
        session_id: The session identifier, matched against the known
            synthetic shapes when no marker is present.

    Returns:
        The producer name (e.g. ``"playbook-probe"``), or ``None`` for real
        traffic.
    """
    if isinstance(marker, str) and marker:
        return marker
    return _source_for_session(session_id)


def event_synthetic_source(hook_input: Mapping[str, Any]) -> str | None:
    """Classify a raw hook-event payload. See :func:`classify_synthetic`."""
    return classify_synthetic(
        marker=hook_input.get(SYNTHETIC_SOURCE_FIELD),
        session_id=hook_input.get(HookInputField.SESSION_ID),
    )


def is_synthetic_event(hook_input: Mapping[str, Any]) -> bool:
    """True when this hook event was fabricated by a harness, not by an agent."""
    return event_synthetic_source(hook_input) is not None


def record_synthetic_source(record: Mapping[str, Any]) -> str | None:
    """Classify a written ``verdicts.jsonl`` record.

    Falls back to the session shape when the record carries no marker, which
    is every record written before this field existed.
    """
    return classify_synthetic(
        marker=record.get(VERDICT_SYNTHETIC_FIELD),
        session_id=record.get("session"),
    )
