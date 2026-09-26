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
failures. So ``MAIN`` means "no ``agent_id`` AND not synthetic", unless a
hand-sent probe names its thread with ``probe_as`` (Plan 00466 N12), which is
the only way a probe can exercise a scoped handler without being recorded as
real traffic.

**Scope only means anything on an event that can carry ``agent_id``.** Five
contracts declare the field in their ``conditional_input_fields`` or
``input_example``: ``PreToolUse``, ``PostToolUse``, ``Stop``, ``SubagentStop``
and ``SubagentStart``. (``Elicitation`` only MENTIONS it, in a prose note about
``PreToolUse``; a text search says six, which is why the set above is derived
from the declared field lists instead.) On any other event
``MAIN`` would admit everything and ``SUB`` nothing — a declared protection
that cannot exist. Rejecting the key there belongs at config validation, where
the author is present to be told; this module answers only the per-event
question.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Final

#: The ``handlers.<event>.<key>.scope`` config key.
SCOPE_CONFIG_KEY: Final[str] = "scope"

#: The payload field that names the subagent a hook fired inside.
AGENT_ID_FIELD: Final[str] = "agent_id"

#: Events whose contract declares ``agent_id``, and therefore the only events on
#: which a restricting scope means anything.
#:
#: A constant rather than a runtime read of ``contracts/``: those files are a
#: repository-side reference and are not shipped with the package, so parsing
#: them at import would work here and fail in every client. The cost of copying
#: is drift, so ``tests/unit/config/test_scope_requires_agent_id_event.py``
#: reads the real contracts and fails if this set stops matching them.
AGENT_ID_EVENTS: Final[frozenset[str]] = frozenset(
    {"PreToolUse", "PostToolUse", "Stop", "SubagentStop", "SubagentStart"}
)


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


def _is_synthetic(hook_input: Mapping[str, Any]) -> bool:
    """Whether a test harness fabricated this event.

    Imported lazily because `config.models` reads :class:`HandlerScope`, and
    `daemon.synthetic_traffic` sits under a package that imports `config` — a
    module-level import here closes that loop and breaks daemon startup. Same
    deferral, for the same reason, as `path_exclusion.resolve_project_root`.
    """
    from claude_code_hooks_daemon.daemon.synthetic_traffic import is_synthetic_event

    return is_synthetic_event(hook_input)


def _probe_stands_for(hook_input: Mapping[str, Any], *, subagent: bool) -> bool:
    """Whether a synthetic event is a probe standing for that thread.

    Lazy for the same import-cycle reason as :func:`_is_synthetic`.
    """
    from claude_code_hooks_daemon.daemon.synthetic_traffic import ProbeThread, probe_thread

    wanted = ProbeThread.SUB if subagent else ProbeThread.MAIN
    return probe_thread(hook_input) is wanted


def acts_as_main_thread(hook_input: Mapping[str, Any]) -> bool:
    """Whether this event is judged as the main thread's.

    A real event: no ``agent_id``. A synthetic one: only a probe that says it
    stands for the main thread (Plan 00466 N12); any other fabricated event is
    neither thread, as before.
    """
    if _is_synthetic(hook_input):
        return _probe_stands_for(hook_input, subagent=False)
    return not in_subagent(hook_input)


def acts_as_subagent(hook_input: Mapping[str, Any]) -> bool:
    """Whether this event is judged as a subagent's. Mirror of :func:`acts_as_main_thread`."""
    if _is_synthetic(hook_input):
        return _probe_stands_for(hook_input, subagent=True)
    return in_subagent(hook_input)


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

    A synthetic event is admitted by ``ALL`` and, as a rule, by neither of the
    others: it is not a real main thread, and it is not a subagent, so
    claiming it for either would be a statement the payload does not support.
    The one exception is a probe that makes that statement itself with
    ``probe_as`` (see ``synthetic_traffic.probe_thread``).
    """
    if scope is HandlerScope.ALL:
        return True
    if scope is HandlerScope.MAIN:
        return acts_as_main_thread(hook_input)
    return acts_as_subagent(hook_input)


def event_supports_scope(event_name: str) -> bool:
    """Whether a restricting scope can mean anything on this event.

    An UNKNOWN event answers False. Assuming support would accept a ``scope``
    that silently does nothing, which is the failure this whole check exists to
    prevent — and a newly-wired event that genuinely carries ``agent_id`` is a
    deliberate addition to :data:`AGENT_ID_EVENTS`, not something to infer.
    """
    return event_name in AGENT_ID_EVENTS


def validate_scope_for_event(event_name: str, handler_key: str, scope: HandlerScope | None) -> None:
    """Raise when ``scope`` restricts on an event that cannot discriminate.

    ``ALL`` and an unset key are accepted everywhere: neither claims anything
    about where the handler runs, so neither can be a false promise.

    ``MAIN`` or ``SUB`` on an event with no ``agent_id`` would admit everything
    or nothing respectively — a declared protection that cannot exist. Refused
    here because config-validation time is the one moment the author is present
    to be told; at dispatch time nobody is, and a setting that quietly does
    nothing is indistinguishable from one that works.
    """
    if scope is None or scope is HandlerScope.ALL:
        return
    if event_supports_scope(event_name):
        return
    eligible = ", ".join(sorted(AGENT_ID_EVENTS))
    raise ValueError(
        f"handler `{handler_key}` on event `{event_name}` sets "
        f"`{SCOPE_CONFIG_KEY}: {scope.value}`, but `{event_name}` payloads never "
        f"carry `{AGENT_ID_FIELD}` — so MAIN would admit every event and SUB "
        f"none, and the setting would state a protection that cannot exist. "
        f"Use `{SCOPE_CONFIG_KEY}: {HandlerScope.ALL.value}` (or remove the "
        f"key) here. A restricting scope works on: {eligible}."
    )


def resolve_scope(handler_config: Mapping[str, Any] | None, default: HandlerScope) -> HandlerScope:
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
