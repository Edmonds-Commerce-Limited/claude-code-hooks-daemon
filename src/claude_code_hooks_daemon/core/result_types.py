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

**Each tier PARAMETERISES the generic ``HookResult[DecisionT]`` rather than
re-declaring ``decision``.** An earlier version of this module declared
``decision: Literal[...] = Decision.ALLOW`` directly in each tier's class
body, overriding the base's ``decision: Decision`` field. pyright's
``reportIncompatibleVariableOverride`` correctly rejected that: it demands
invariance for a mutable attribute, and a ``Literal`` subset is not the same
type as the field it was overriding, only a subtype. mypy accepted it (it
demands only a subtype for an override), so the warning went unfixed for a
time — but the fix is not a pyright/mypy strictness mismatch to shrug off,
it is that overriding a field at all was the wrong shape. Substituting the
type parameter on ``core/hook_result.py``'s generic base instead means no
tier here ever re-declares ``decision``, so there is no override for
pyright to reject in the first place. Do NOT go back to a per-tier field
re-declaration to "simplify" this — see ``HookResult``'s own docstring.

**A note on ``Decision.CONTINUE``.** It is in every tier because it is
deliverable on every event. It is also vestigial: nothing in ``src/`` returns
it, no formatter branches on it, and no response schema has a ``continue`` key,
so it serialises to ``{}``. ``chain.py`` and ``verdict_log.py`` both already
treat it as lax/advisory — ALLOW-equivalent. Excluding it would break nothing
today but would be a gratuitous incompatibility for a client handler naming it.
"""

from typing import Any, Final, Literal, Self, TypeVar, get_args

from claude_code_hooks_daemon.core.hook_result import REFUSAL_CAPABLE_EVENTS, Decision, HookResult
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter

#: The decisions every event can carry, whatever else it can express.
_UNIVERSAL: Final[frozenset[Decision]] = frozenset({Decision.ALLOW, Decision.CONTINUE})

#: The model field the tiers narrow.
_DECISION_FIELD: Final[str] = "decision"


_ResultT = TypeVar("_ResultT", bound=HookResult[Any])  # any tier; only decision/reason are read


def _filed_under_rule(result: _ResultT, rule: Rule, blocked: str | None) -> _ResultT:
    """A denial with ``rule``'s ``BLOCKED [id]`` headline above its reason.

    For a handler whose deny reasons are built in several places and each
    carries its own specifics. Wrapping the verdict once puts on every deny
    path the identifier ``explain-rule`` resolves (Plan 00484 G5). Anything but
    a denial is returned unchanged.
    """
    if result.decision is not Decision.DENY:
        return result
    headline = RuleFormatter().headline(rule, blocked=blocked)
    reason = f"{headline}\n\n{result.reason}" if result.reason else headline
    return result.model_copy(update={"reason": reason, "rule": rule.rule_id})


class AdvisoryResult(HookResult[Literal[Decision.ALLOW, Decision.CONTINUE]]):
    """For an event that can neither deny nor ask — it can only add context.

    ``SessionStart``, ``SessionEnd``, ``Notification``, both worktree events,
    ``Status`` and the other events with no documented decision control route
    through formatters that have no way to express a refusal.
    """


class BlockingResult(HookResult[Literal[Decision.ALLOW, Decision.CONTINUE, Decision.DENY]]):
    """For an event that can block but has no ``ask``.

    ``PostToolUse``, ``Stop``, ``SubagentStop``, ``UserPromptSubmit``,
    ``PreCompact``, ``PermissionRequest`` (``decision.behavior``), the
    wired-extra top-level-block events and the ``continue: false`` pair
    (``TeammateIdle``/``TaskCompleted``). There is no wire representation for
    ASK on any of them.
    """

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

    def under_rule(self, rule: Rule, *, blocked: str | None = None) -> Self:
        """File a denial under ``rule``: its ``BLOCKED [id]`` headline above the reason.

        See :func:`_filed_under_rule`.

        Args:
            rule: The rule the denial belongs to.
            blocked: Headline wording for this one deny, when the rule's own
                ``blocked`` text would misdescribe it (a fail-closed deny).

        Returns:
            A copy of this result with the headline prepended to its reason, or
            this result when it is not a denial.
        """
        return _filed_under_rule(self, rule, blocked)


class GatingResult(
    HookResult[
        Literal[Decision.ALLOW, Decision.CONTINUE, Decision.DENY, Decision.ASK, Decision.DEFER]
    ]
):
    """For an event that gates an action and can deny or ask.

    ``PreToolUse`` (``permissionDecision``) is the only one:
    ``PermissionRequest``'s documented ``decision.behavior`` enum is
    ``allow`` | ``deny`` with no ask outcome, so it sits in the blocking tier
    (Plan 00271 audit item 3).
    """

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
    def deny_and_halt(
        cls,
        reason: str,
        *,
        stop_reason: str | None = None,
        context: list[str] | None = None,
    ) -> Self:
        """Create a deny that ALSO halts the turn (``continue: false``).

        The tool call is denied and Claude Code stops processing, showing
        ``stop_reason`` to the user.

        Args:
            reason: Reason for denial (required)
            stop_reason: Message shown on the halt; defaults to ``reason``
            context: Optional context lines

        Returns:
            A result of the calling class, with the deny decision and halt set.
        """
        return cls(
            decision=Decision.DENY,
            reason=reason,
            context=context or [],
            halt_turn=True,
            stop_reason=stop_reason,
        )

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

    @classmethod
    def defer(cls) -> Self:
        """Create a defer result — exit gracefully so the tool resumes later.

        No arguments by design: the docs ignore ``permissionDecisionReason``,
        ``updatedInput`` and ``additionalContext`` when the decision is defer
        (Plan 00271 item 2), so accepting them would promise delivery the wire
        cannot make.

        Returns:
            A result of the calling class, with the defer decision.
        """
        return cls(decision=Decision.DEFER)

    def under_rule(self, rule: Rule, *, blocked: str | None = None) -> Self:
        """File a denial under ``rule``. See :meth:`BlockingResult.under_rule`."""
        return _filed_under_rule(self, rule, blocked)


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
