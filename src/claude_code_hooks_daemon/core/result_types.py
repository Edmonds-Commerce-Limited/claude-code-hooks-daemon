"""Result types narrowed to the decisions their event can actually deliver.

``HookResult`` is one event-agnostic type serving all 31 wired events, so
nothing at the type level stops a ``SessionStart`` handler constructing a DENY.
The wire response then drops the refusal: the handler believes it blocked, and
nothing blocked.

Three guards catch that today — runtime enforcement in ``to_json``, a derived
sweep over built-in handlers, and ``validate-project-handlers`` for a client's
own. Every one of them detects a bug someone has ALREADY written. These types
make it unwritable instead, on both axes at once:

- **statically**, because mypy rejects an out-of-tier ``Decision`` argument, and
  rejects widening the field back in a subclass;
- **at runtime**, because the ``Literal`` is a Pydantic constraint and
  ``validate_assignment`` is already on — so construction AND mutation raise.

That second axis is what closes ``merge_pseudo_results``, which writes
``result.decision`` directly rather than constructing a new result.

**The tiers are siblings, never a chain.** Deriving ``BlockingResult`` from
``AdvisoryResult`` would WIDEN the field, and mypy rejects a widened override.
All three extend ``HookResult`` directly.

**A note on pyright.** It reports ``reportIncompatibleVariableOverride`` here:
it demands invariance for a mutable attribute, where mypy demands only a
subtype. This project's QA gate is mypy, so nothing fails — but do NOT "fix" the
warning by widening the field, which would undo the entire guarantee.

**A note on ``Decision.CONTINUE``.** It is in every tier because it is
deliverable on every event. It is also vestigial: nothing in ``src/`` returns
it, no formatter branches on it, and no response schema has a ``continue`` key,
so it serialises to ``{}``. ``chain.py`` and ``verdict_log.py`` both already
treat it as lax/advisory — ALLOW-equivalent. Excluding it would break nothing
today but would be a gratuitous incompatibility for a client handler naming it.
"""

from typing import Final, Literal, Self, get_args

from claude_code_hooks_daemon.core.hook_result import REFUSAL_CAPABLE_EVENTS, Decision, HookResult

#: The decisions every event can carry, whatever else it can express.
_UNIVERSAL: Final[frozenset[Decision]] = frozenset({Decision.ALLOW, Decision.CONTINUE})

#: The model field the tiers narrow.
_DECISION_FIELD: Final[str] = "decision"


class AdvisoryResult(HookResult):
    """For an event that can neither deny nor ask — it can only add context.

    ``SessionStart``, ``SessionEnd``, ``PreCompact``, ``Notification``, both
    worktree events, ``Status`` and every newly-wired event route through
    ``_format_system_message_response``, which has no way to express a refusal.
    """

    decision: Literal[Decision.ALLOW, Decision.CONTINUE] = Decision.ALLOW


class BlockingResult(HookResult):
    """For an event that can block but has no ``ask``.

    ``PostToolUse``, ``Stop`` and ``SubagentStop`` express a refusal as a
    top-level ``decision: "block"``. There is no wire representation for ASK.
    """

    decision: Literal[Decision.ALLOW, Decision.CONTINUE, Decision.DENY] = Decision.ALLOW

    @classmethod
    def deny(cls, reason: str, *, context: list[str] | None = None) -> Self:
        """Create a deny result of THIS tier.

        Overrides the base only to narrow the return type: the base returns the
        wide ``HookResult`` on purpose, so that a tier which cannot refuse is
        rejected for calling it. This tier can, so it gets its own type back and
        is usable from a handler declared to return it.

        Args:
            reason: Reason for denial (required)
            context: Optional context lines

        Returns:
            A result of the calling class, with the deny decision.
        """
        return cls(decision=Decision.DENY, reason=reason, context=context or [])


class GatingResult(HookResult):
    """For an event that gates an action and can deny or ask.

    ``PreToolUse`` (``permissionDecision``) and ``PermissionRequest``
    (``decision.behavior``) are the only two.
    """

    decision: Literal[Decision.ALLOW, Decision.CONTINUE, Decision.DENY, Decision.ASK] = (
        Decision.ALLOW
    )

    @classmethod
    def deny(cls, reason: str, *, context: list[str] | None = None) -> Self:
        """Create a deny result of THIS tier. See ``BlockingResult.deny``.

        Args:
            reason: Reason for denial (required)
            context: Optional context lines

        Returns:
            A result of the calling class, with the deny decision.
        """
        return cls(decision=Decision.DENY, reason=reason, context=context or [])

    @classmethod
    def ask(cls, reason: str, *, context: list[str] | None = None) -> Self:
        """Create an ask result of THIS tier — the only tier that can.

        Args:
            reason: Reason for asking (required)
            context: Optional context lines

        Returns:
            A result of the calling class, with the ask decision.
        """
        return cls(decision=Decision.ASK, reason=reason, context=context or [])


#: Narrowest first, so ``result_type_for_event`` never returns a wider tier
#: than the event needs even if two tiers were to coincide.
_TIERS: Final[tuple[type[HookResult], ...]] = (AdvisoryResult, BlockingResult, GatingResult)


def decisions_of(result_type: type[HookResult]) -> set[Decision]:
    """The decisions a result type actually permits, read off its annotation.

    Read from the model field rather than from a parallel declaration, so the
    answer cannot drift from what the type really enforces.

    Args:
        result_type: A ``HookResult`` or one of the narrowed tiers.

    Returns:
        The permitted decisions. For unnarrowed ``HookResult`` this is every
        member of ``Decision``.
    """
    annotation = result_type.model_fields[_DECISION_FIELD].annotation
    args = get_args(annotation)
    if not args:
        # Unnarrowed: the annotation is the bare enum, not a Literal.
        return set(Decision)
    return {arg for arg in args if isinstance(arg, Decision)}


def decisions_carried_by(event_name: str) -> frozenset[Decision]:
    """The decisions this event can actually deliver on the wire.

    Derived from ``REFUSAL_CAPABLE_EVENTS`` rather than restated, so a
    correction to the capability table propagates here instead of leaving two
    tables to reconcile by hand.

    Args:
        event_name: The wire event name.

    Returns:
        The deliverable decisions, always including ALLOW and CONTINUE.
    """
    carried = set(_UNIVERSAL)
    for decision, events in REFUSAL_CAPABLE_EVENTS.items():
        if event_name in events:
            carried.add(decision)
    return frozenset(carried)


def result_type_for_event(event_name: str) -> type[HookResult]:
    """The result tier whose permitted decisions match this event exactly.

    Args:
        event_name: The wire event name.

    Returns:
        The matching narrowed result type.

    Raises:
        ValueError: If the event is unknown, or if no tier fits exactly.

    FAIL FAST on an unknown event rather than defaulting to the advisory tier.
    An unrecognised name resolves to ``{ALLOW, CONTINUE}``, which matches
    ``AdvisoryResult`` perfectly — so the wrong answer would look exactly like
    the right one. If the name were a typo for a refusal-capable event, every
    handler built on it would be silently forbidden from denying.

    This is deliberately the OPPOSITE policy to
    ``decision_capability.undeliverable_decisions``, which returns nothing for
    an unknown event. That one is a diagnostic run against a CLIENT's handlers,
    where refusing to judge is the safe failure; this one picks the type a
    handler is built on, where guessing is not.
    """
    from claude_code_hooks_daemon.core.response_schemas import RESPONSE_SCHEMAS

    if event_name not in RESPONSE_SCHEMAS:
        raise ValueError(
            f"Unknown event {event_name!r}: cannot choose a result tier for it. "
            "Every wired event has a response schema, so an unrecognised name is "
            "a typo or an unwired event — both of which must be fixed rather "
            "than defaulted to the advisory tier."
        )

    carried = decisions_carried_by(event_name)
    for result_type in _TIERS:
        if decisions_of(result_type) == carried:
            return result_type

    raise ValueError(
        f"No result tier carries exactly {sorted(d.value for d in carried)} for "
        f"event {event_name!r}. Add the missing tier rather than widening an "
        "existing one — a wider tier permits a decision this event drops."
    )
