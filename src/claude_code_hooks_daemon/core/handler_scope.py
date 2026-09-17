"""Where a handler is active: every event, the main thread only, or subagents only.

Issue #40 asked for a per-handler ``scope`` key so a nudge handler stops firing
at subagents — the reported harm being a finished agent told to continue every
plan in the coordinator's ledger, none of which was its assignment.

**The discriminator is the ABSENCE of ``agent_id``, and nothing else.** Plan
00418 established it and Plan 00423 Phase 2 re-measured it against live
payloads: present (a 17-character string, never empty) in all five subagent
stops, absent on the main-thread stop.

``agent_type`` is deliberately NOT consulted. It fails in BOTH directions — the
contract warns a session-wide ``--agent`` sets it on a MAIN-thread stop, and
measurement found it present but EMPTY in 4 of 5 real subagent stops. A handler
keying on it would have misclassified four of five subagents as main-thread,
firing nudges exactly where they were meant to be suppressed.

**``MAIN`` is not simply "no ``agent_id``".** A fabricated event carries none
either, so the acceptance playbook's probes are indistinguishable from the main
thread by that field alone. ``orchestrator_simulate`` learned this the
expensive way and guards with :func:`is_synthetic_event`; its docstring records
that without the guard the suite went red with hundreds of denied probes AND,
under most-restrictive-wins, other handlers' expected ALLOWs turned into
failures. So ``MAIN`` means "no ``agent_id`` AND not synthetic".

**Scope only means anything on an event that can carry ``agent_id``.** Six
contracts declare the field: ``PreToolUse``, ``PostToolUse``, ``Stop``,
``SubagentStop``, ``SubagentStart`` and ``Elicitation``. On any other event
``MAIN`` would admit everything and ``SUB`` nothing — a declared protection
that cannot exist. Rejecting the key there belongs at config validation, where
the author is present to be told; this module answers only the per-event
question.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Final

from claude_code_hooks_daemon.daemon.synthetic_traffic import is_synthetic_event

#: The ``handlers.<event>.<key>.scope`` config key.
SCOPE_CONFIG_KEY: Final[str] = "scope"

#: The payload field that names the subagent a hook fired inside.
AGENT_ID_FIELD: Final[str] = "agent_id"


class HandlerScope(StrEnum):
    """Where a handler may run.

    ``ALL`` is the default everywhere. A handler that has not had its scope
    thought about must keep running exactly as before: the failure mode of a
    wrong default is a guard silently switched off for a whole class of
    session, and a handler that stops firing looks identical to one with
    nothing to report.
    """

    ALL = "ALL"
    MAIN = "MAIN"
    SUB = "SUB"


def in_subagent(hook_input: Mapping[str, Any]) -> bool:
    """Whether this event fired inside a subagent call.

    Truthiness rather than presence: measured, ``agent_id`` is a 17-character
    string whenever it appears and never empty, so the two agree — but an empty
    string is not an agent identity, and reading it as one would classify a
    main-thread event as a subagent.
    """
    return bool(hook_input.get(AGENT_ID_FIELD))


def scope_admits(scope: HandlerScope, hook_input: Mapping[str, Any]) -> bool:
    """Whether a handler with ``scope`` may run for this event.

    A synthetic event is admitted by ``ALL`` and by neither of the others: it
    is not a real main thread, and it is not a subagent, so claiming it for
    either would be a statement the payload does not support.
    """
    if scope is HandlerScope.ALL:
        return True
    if is_synthetic_event(hook_input):
        return False
    if scope is HandlerScope.MAIN:
        return not in_subagent(hook_input)
    return in_subagent(hook_input)


def resolve_scope(
    handler_config: Mapping[str, Any] | None, default: HandlerScope
) -> HandlerScope:
    """The effective scope for a handler, from config or its own default.

    Mirrors ``resolve_priority``: an absent key and an explicit ``None`` both
    mean "use the handler's default", because PyYAML parses a bare ``scope:``
    into ``None`` exactly as it does ``priority:``.

    An UNKNOWN value raises rather than falling back. A typo that quietly
    became ``ALL`` would run a guard where its author meant it not to, and that
    is the direction nobody can notice from the outside — no error, no failing
    test, just a handler firing in sessions it was scoped out of.
    """
    if not handler_config:
        return default
    raw = handler_config.get(SCOPE_CONFIG_KEY)
    if raw is None:
        return default
    if isinstance(raw, HandlerScope):
        return raw
    try:
        return HandlerScope(str(raw).strip().upper())
    except ValueError as exc:
        legal = ", ".join(member.value for member in HandlerScope)
        raise ValueError(
            f"unknown handler scope {raw!r}; expected one of {legal} "
            f"(config key `{SCOPE_CONFIG_KEY}`)"
        ) from exc
