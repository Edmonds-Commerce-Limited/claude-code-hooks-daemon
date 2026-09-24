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
   harness — and it is checked first. A hand-sent probe is marked the same
   way, with :data:`MANUAL_PROBE`; ``hooks-daemon probe`` does it for you.
2. A known synthetic SESSION SHAPE is recognised. This is the fallback: it
   classifies the window written before the marker existed, and covers a
   producer whose events this repository does not construct.

**A probe may also say which thread it stands for** (:data:`PROBE_AS_FIELD`,
read by :func:`probe_thread`). Being marked keeps it out of the real record;
naming a thread is what lets it reach a MAIN- or SUB-scoped handler at all.
Only a probe-class source may do this.

**An unmarked, unrecognised session is REAL.** A dispatch with no session id
at all (recorded as ``default``) is real too. Guessing the other way would
discard an agent's own traffic on no evidence, which is precisely the failure
the record exists to avoid.

The predicate lives here, once, so the writer, the report and any handler that
must decline to act on a probe cannot disagree about what a probe is.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
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

#: A payload a person or agent sends by hand to probe a handler: what
#: ``hooks-daemon probe`` (``daemon/hook_probe.py``) sets, and the value the
#: probing docs tell a raw payload to carry (Plan 00466 N12).
MANUAL_PROBE: Final[str] = "manual-probe"

#: The transport toggle's real-invocation verification probes
#: (``install/transport_verify.py``). Probe-class: its Stop probe exists to
#: see MAIN-scoped ``auto_continue_stop`` block.
TRANSPORT_VERIFY: Final[str] = "transport-verify"

#: An acceptance or integration test, or a QA script, sending its own probe to
#: the live daemon. ``tests/integration/test_live_probes_are_marked.py``
#: requires the marker on every such payload.
TEST_PROBE: Final[str] = "test-probe"

#: Field a PROBE sets to name the thread it stands for. The marker keeps the
#: probe out of the real record, and a synthetic event is neither a main
#: thread nor a subagent, so without this a probe could never reach a MAIN- or
#: SUB-scoped handler (``core/handler_scope.py``).
PROBE_AS_FIELD: Final[str] = "probe_as"

#: The only sources allowed to name a thread, each declared here by name. A
#: probe is sent to exercise handlers, so it may stand for a thread; a harness
#: run, a cron tick or a supervisor-generated event must never pass for one,
#: and keeps the refusal.
PROBE_CLASS_SOURCES: Final[frozenset[str]] = frozenset(
    {MANUAL_PROBE, TRANSPORT_VERIFY, TEST_PROBE, SOCKET_STDIN_TEST}
)

#: The ``agent_id`` a probe standing for a subagent carries. Documented and
#: fixed, so every consumer of ``agent_id`` can tell it from a real teammate,
#: and deliberately not the 17-character shape Claude Code mints.
PROBE_AGENT_ID: Final[str] = "manual-probe-agent"


class ProbeThread(StrEnum):
    """The values :data:`PROBE_AS_FIELD` accepts."""

    MAIN = "main"
    SUB = "sub"


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
        session_id=hook_input.get("session_id"),
    )


def is_synthetic_event(hook_input: Mapping[str, Any]) -> bool:
    """True when this hook event was fabricated by a harness, not by an agent."""
    return event_synthetic_source(hook_input) is not None


def probe_thread(hook_input: Mapping[str, Any]) -> ProbeThread | None:
    """The thread a probe stands for, or None when it may not claim one.

    Only an event whose MARKER is a probe-class source counts; the
    session-shape fallback never does, because a shape is a guess and a
    thread claim reaches safety handlers. The claim must also agree with
    ``agent_id``: a main-thread probe carries none, and a subagent probe
    carries exactly :data:`PROBE_AGENT_ID`, never a real teammate's id. A
    claim that fails any of this is refused whole rather than half-honoured.
    """
    if hook_input.get(SYNTHETIC_SOURCE_FIELD) not in PROBE_CLASS_SOURCES:
        return None
    raw = hook_input.get(PROBE_AS_FIELD)
    thread = next((member for member in ProbeThread if member.value == raw), None)
    if thread is None:
        return None
    agent_id = hook_input.get(HookInputField.AGENT_ID)
    if thread is ProbeThread.MAIN:
        return thread if not agent_id else None
    return thread if agent_id == PROBE_AGENT_ID else None


def record_synthetic_source(record: Mapping[str, Any]) -> str | None:
    """Classify a written ``verdicts.jsonl`` record.

    Falls back to the session shape when the record carries no marker, which
    is every record written before this field existed.
    """
    return classify_synthetic(
        marker=record.get(VERDICT_SYNTHETIC_FIELD),
        session_id=record.get("session"),
    )
