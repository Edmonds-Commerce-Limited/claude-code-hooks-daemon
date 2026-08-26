"""Plan 00265 Phase 1: a result type that cannot hold an undeliverable decision.

``HookResult`` is one event-agnostic type serving all 31 wired events, so
nothing at the type level stops a ``SessionStart`` handler constructing a DENY.
The existing guards all detect that AFTER someone writes it — runtime
enforcement in ``to_json``, a derived sweep over built-in handlers, and
``validate-project-handlers`` for a client's own. None makes it unwritable.

These three narrowed types are the first half of making it unwritable (the
second is the per-event handler bases in Phase 2). Each constrains ``decision``
to a ``Literal`` of the decisions its tier can actually deliver, which mypy
rejects statically AND Pydantic rejects at runtime — ``validate_assignment`` is
already on, so mutation is covered as well as construction.

**All three extend ``HookResult`` directly, never each other.** Deriving
``BlockingResult`` from ``AdvisoryResult`` would WIDEN the field, and mypy
rejects a widened override (measured: ``Incompatible types in assignment
(expression has type "Literal[ALLOW, CONTINUE, DENY]", base class defined the
type as "Literal[ALLOW, CONTINUE]")``). The tiers are siblings, not a chain.

**On ``Decision.CONTINUE``**: it appears in every tier because it is deliverable
on every event — verified across all 31. It is also vestigial: no handler in
``src/`` returns it, no formatter branches on it, and no response schema has a
``continue`` key, so it serialises to ``{}``. Both ``chain.py`` and
``verdict_log.py`` already treat it as lax/advisory, i.e. ALLOW-equivalent.
Excluding it would break nothing today but would be a gratuitous incompatibility
for any client handler that names it.
"""

from typing import Literal, get_args, get_type_hints

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.core.hook_result import (
    REFUSAL_CAPABLE_EVENTS,
    Decision,
    HookResult,
)
from claude_code_hooks_daemon.core.response_schemas import RESPONSE_SCHEMAS, validate_response
from claude_code_hooks_daemon.core.result_types import (
    AdvisoryResult,
    BlockingResult,
    GatingResult,
    decisions_carried_by,
    decisions_of,
    result_type_for_event,
)

_TIERS: dict[type[HookResult], set[Decision]] = {
    AdvisoryResult: {Decision.ALLOW, Decision.CONTINUE},
    BlockingResult: {Decision.ALLOW, Decision.CONTINUE, Decision.DENY},
    GatingResult: {
        Decision.ALLOW,
        Decision.CONTINUE,
        Decision.DENY,
        Decision.ASK,
        Decision.DEFER,
    },
}


class TestEachTierAcceptsItsOwnDecisions:
    """The tier must not be so narrow that correct code cannot compile."""

    @pytest.mark.parametrize("result_type,allowed", list(_TIERS.items()))
    def test_every_in_tier_decision_constructs(
        self, result_type: type[HookResult], allowed: set[Decision]
    ) -> None:
        for decision in allowed:
            assert result_type(decision=decision).decision == decision

    @pytest.mark.parametrize("result_type", list(_TIERS))
    def test_the_default_is_allow(self, result_type: type[HookResult]) -> None:
        """A bare construction must stay the harmless one."""
        assert result_type().decision == Decision.ALLOW


class TestEachTierRejectsWhatItCannotDeliver:
    """The property: an undeliverable decision cannot be held at all."""

    @pytest.mark.parametrize("result_type,allowed", list(_TIERS.items()))
    def test_an_out_of_tier_decision_cannot_be_constructed(
        self, result_type: type[HookResult], allowed: set[Decision]
    ) -> None:
        for decision in set(Decision) - allowed:
            with pytest.raises(ValidationError):
                result_type(decision=decision, reason="should be impossible")

    @pytest.mark.parametrize("result_type,allowed", list(_TIERS.items()))
    def test_an_out_of_tier_decision_cannot_be_assigned(
        self, result_type: type[HookResult], allowed: set[Decision]
    ) -> None:
        """Construction is not the only way in — ``merge_pseudo_results`` mutates.

        This is what closes that path: ``validate_assignment`` is on, so writing
        a DENY into an advisory result raises rather than silently succeeding.
        """
        for decision in set(Decision) - allowed:
            result = result_type()
            with pytest.raises(ValidationError):
                result.decision = decision


class TestTheTiersStayCompatibleWithHookResult:
    """Everything downstream is typed against HookResult and must keep working."""

    @pytest.mark.parametrize("result_type", list(_TIERS))
    def test_each_tier_is_a_hook_result(self, result_type: type[HookResult]) -> None:
        assert issubclass(result_type, HookResult)

    @pytest.mark.parametrize("result_type", list(_TIERS))
    def test_each_tier_still_serialises(self, result_type: type[HookResult]) -> None:
        response = result_type(context=["note"]).to_json("SessionStart")

        assert response == {"systemMessage": "note"}

    def test_a_blocking_tier_deny_still_denies(self) -> None:
        """Narrowing must not weaken a refusal that IS deliverable."""
        response = BlockingResult(decision=Decision.DENY, reason="nope").to_json("PreToolUse")

        assert not validate_response("PreToolUse", response)
        assert "deny" in str(response) or "block" in str(response)


class TestTheLiteralMatchesTheDeclaredTier:
    """Guard the guard — the Literal is hand-written and can drift.

    ``decisions_of`` reads the Literal back off the model field, so every other
    check here is anchored to what the type ACTUALLY permits rather than to a
    second hand-written list that could disagree with it.
    """

    @pytest.mark.parametrize("result_type,allowed", list(_TIERS.items()))
    def test_the_field_literal_is_exactly_the_tier(
        self, result_type: type[HookResult], allowed: set[Decision]
    ) -> None:
        assert decisions_of(result_type) == allowed

    def test_decisions_of_reads_the_annotation_not_a_declaration(self) -> None:
        """If this drifts, every other assertion here becomes decorative."""
        annotation = AdvisoryResult.model_fields["decision"].annotation

        assert set(get_args(annotation)) == decisions_of(AdvisoryResult)

    def test_the_widest_tier_is_not_the_whole_enum_by_accident(self) -> None:
        """A tier equal to Decision would mean the narrowing does nothing."""
        assert decisions_of(AdvisoryResult) != set(Decision)
        assert decisions_of(BlockingResult) != set(Decision)


class TestTierMembershipIsDerivedFromTheCapabilityTable:
    """One source of truth: the table the runtime guard already uses.

    ``REFUSAL_CAPABLE_EVENTS`` is held to the emitted response by
    ``test_dropped_refusal_is_logged.py``. Deriving the tiers from it means a
    correction there propagates here instead of leaving two tables to reconcile.
    """

    @pytest.mark.parametrize("event_name", sorted(RESPONSE_SCHEMAS))
    def test_every_event_carries_at_least_allow(self, event_name: str) -> None:
        assert Decision.ALLOW in decisions_carried_by(event_name)

    @pytest.mark.parametrize("event_name", sorted(RESPONSE_SCHEMAS))
    def test_carried_decisions_match_the_capability_table(self, event_name: str) -> None:
        expected = {Decision.ALLOW, Decision.CONTINUE}
        for decision, events in REFUSAL_CAPABLE_EVENTS.items():
            if event_name in events:
                expected.add(decision)

        assert decisions_carried_by(event_name) == expected

    @pytest.mark.parametrize("event_name", sorted(RESPONSE_SCHEMAS))
    def test_every_event_maps_to_a_tier_that_fits_it_exactly(self, event_name: str) -> None:
        """A near-fit would either forbid something legal or permit a drop."""
        result_type = result_type_for_event(event_name)

        assert decisions_of(result_type) == decisions_carried_by(event_name)

    def test_the_known_tier_assignments_hold(self) -> None:
        """Spot-check the three tiers against events whose behaviour is settled."""
        assert result_type_for_event("PreToolUse") is GatingResult
        assert result_type_for_event("PermissionRequest") is BlockingResult
        assert result_type_for_event("Stop") is BlockingResult
        assert result_type_for_event("PostToolUse") is BlockingResult
        assert result_type_for_event("SessionStart") is AdvisoryResult
        assert result_type_for_event("Status") is AdvisoryResult

    def test_an_unknown_event_fails_fast(self) -> None:
        """Never guess a tier — guessing wide permits a silent drop."""
        with pytest.raises(ValueError, match="NoSuchEventXYZ"):
            result_type_for_event("NoSuchEventXYZ")


class TestTheTiersAreSiblingsNotAChain:
    """Widening an override is exactly what mypy rejects, so the shape matters."""

    @pytest.mark.parametrize("result_type", list(_TIERS))
    def test_no_tier_derives_from_another_tier(self, result_type: type[HookResult]) -> None:
        others = set(_TIERS) - {result_type}

        assert not any(issubclass(result_type, other) for other in others), (
            f"{result_type.__name__} derives from another tier, which widens the "
            "decision field — mypy rejects a widened override, so the tiers must "
            "extend HookResult directly"
        )


class TestTheNarrowingIsRealNotDecorative:
    """A Literal that resolves to the whole enum would pass everything above."""

    def test_advisory_literal_is_a_strict_subset(self) -> None:
        literal_args = set(get_args(AdvisoryResult.model_fields["decision"].annotation))

        assert literal_args < set(Decision)
        assert Decision.DENY not in literal_args
        assert Decision.ASK not in literal_args

    def test_the_base_hook_result_is_still_unconstrained(self) -> None:
        """Narrowing must not leak upwards and break every existing handler."""
        for decision in Decision:
            assert HookResult(decision=decision, reason="x").decision == decision


def test_the_literal_type_is_importable_for_annotation_use() -> None:
    """Handlers annotate against these, so they must be real types."""
    assert Literal is not None
    assert all(isinstance(tier, type) for tier in _TIERS)


class TestTheFactoriesReturnTheTierTheyWereCalledOn:
    """Handlers build results through ``allow``/``deny``/``ask``, not ``__init__``.

    A factory that returns the WIDE ``HookResult`` is unusable from a handler
    declared ``-> AdvisoryResult``: mypy rejects the return, so every reparented
    handler would have to construct its results by hand. These assert the
    runtime half; ``test_static_type_safety_is_enforced`` covers the static half,
    which is where the value is.
    """

    @pytest.mark.parametrize("tier", list(_TIERS))
    def test_allow_returns_the_tier(self, tier: type[HookResult]) -> None:
        assert isinstance(tier.allow(context=["fyi"]), tier)

    @pytest.mark.parametrize("tier", [BlockingResult, GatingResult])
    def test_deny_returns_the_tier_where_the_tier_can_deny(self, tier: type[HookResult]) -> None:
        assert isinstance(tier.deny(reason="blocked"), tier)

    def test_ask_returns_the_tier_where_the_tier_can_ask(self) -> None:
        assert isinstance(GatingResult.ask(reason="confirm?"), GatingResult)

    def test_the_base_factories_still_return_the_base(self) -> None:
        """Existing callers must be unaffected by the narrowing."""
        assert type(HookResult.allow()) is HookResult
        assert type(HookResult.deny(reason="x")) is HookResult
        assert type(HookResult.ask(reason="x")) is HookResult


class TestAnOutOfTierFactoryStillRefusesAtRuntime:
    """The inherited factory is the remaining way in, and it must not work.

    ``AdvisoryResult.deny(...)`` resolves to the BASE ``deny``, which is left
    returning the wide ``HookResult`` on purpose: a handler declared
    ``-> AdvisoryResult`` is then rejected by mypy for returning the wrong type.
    Pydantic backs that up here, so the same call fails even in code mypy never
    sees — a client's project handlers, for instance.
    """

    def test_advisory_cannot_be_denied_through_the_factory(self) -> None:
        with pytest.raises(ValidationError):
            AdvisoryResult.deny(reason="blocked")

    def test_advisory_cannot_be_asked_through_the_factory(self) -> None:
        with pytest.raises(ValidationError):
            AdvisoryResult.ask(reason="confirm?")

    def test_blocking_cannot_be_asked_through_the_factory(self) -> None:
        with pytest.raises(ValidationError):
            BlockingResult.ask(reason="confirm?")

    def test_the_base_deny_is_deliberately_left_wide(self) -> None:
        """If it returned ``Self``, an advisory deny would type-check.

        Recorded as an assertion rather than a comment because widening it back
        would silently remove the static half of the guarantee while every
        runtime test above kept passing.
        """
        assert get_type_hints(HookResult.deny)["return"] is HookResult
        assert get_type_hints(HookResult.ask)["return"] is HookResult
