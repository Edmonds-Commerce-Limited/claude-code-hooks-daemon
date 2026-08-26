"""Plan 00265 Phase 2: the constraint must be INHERITED, not declared.

Phase 1 built result types that cannot hold an undeliverable decision. That
alone protects nothing: a handler still has to choose to use one. A generic
``Handler[ResultT]`` would have the same flaw — a handler that FORGOT to declare
its parameter silently loses protection, which is the exact failure mode this
plan exists to remove.

So each event gets a base whose ``handle()`` already returns the right narrowed
type. A handler subclasses it and is constrained with nothing to declare and
nothing to remember; mypy rejects both returning an out-of-tier decision and
widening the signature back (measured: ``Return type "HookResult" of "handle"
incompatible with return type "AdvisoryResult" in supertype``).

**The per-event names are aliases of three real tier classes.** Verified that
mypy enforces the narrowing identically through an alias, so an event costs one
line rather than a class body. The aliases carry no extra type-level strictness
— they exist so a handler author never has to know which tier their event is in,
which is precisely the knowledge this plan removes the need for. Package-to-tier
correctness is enforced by the sweep here, not by the naming.

The ``HandlerBase`` suffix is deliberate: ``WorktreeCreateHandler`` and
``WorktreeRemoveHandler`` are already concrete handler class names, so the
unsuffixed form would collide.
"""

from typing import get_type_hints

import pytest

from claude_code_hooks_daemon.constants.events import (
    STATUS_LINE_JSON_KEY,
    STATUS_SCHEMA_KEY,
    EventID,
    EventIDMeta,
)
from claude_code_hooks_daemon.core import handler_bases
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.handler_bases import (
    AdvisoryHandler,
    BlockingHandler,
    GatingHandler,
    handler_base_for_event,
)
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.core.response_schemas import RESPONSE_SCHEMAS
from claude_code_hooks_daemon.core.result_types import (
    AdvisoryResult,
    BlockingResult,
    GatingResult,
    decisions_carried_by,
    decisions_of,
    result_type_for_event,
)
from tests.integration.test_every_handler_response_validates import (
    _concrete_handlers_in,
    _handlers_with_event_names,
)

_TIER_BASES: dict[type[Handler], type[HookResult]] = {
    AdvisoryHandler: AdvisoryResult,
    BlockingHandler: BlockingResult,
    GatingHandler: GatingResult,
}

#: Suffix distinguishing a base from a concrete handler of the same event name.
_SUFFIX = "HandlerBase"


def _wired_event_metas() -> list[EventIDMeta]:
    return [meta for meta in vars(EventID).values() if isinstance(meta, EventIDMeta)]


def _schema_key(meta: EventIDMeta) -> str:
    if meta.json_key == STATUS_LINE_JSON_KEY:
        return str(STATUS_SCHEMA_KEY)
    return str(meta.json_key)


class TestEachTierBaseDeclaresItsResultType:
    """The base is the only place the narrowing is written down."""

    @pytest.mark.parametrize("base,result_type", list(_TIER_BASES.items()))
    def test_handle_returns_the_tier_result_type(
        self, base: type[Handler], result_type: type[HookResult]
    ) -> None:
        assert get_type_hints(base.handle)["return"] is result_type

    @pytest.mark.parametrize("base", list(_TIER_BASES))
    def test_the_base_is_a_handler(self, base: type[Handler]) -> None:
        assert issubclass(base, Handler)

    @pytest.mark.parametrize("base", list(_TIER_BASES))
    def test_handle_is_still_abstract(self, base: type[Handler]) -> None:
        """Narrowing must not accidentally make ``handle`` concrete.

        If the base implemented ``handle``, a subclass could forget to and
        silently inherit a stub rather than failing to instantiate.
        """
        assert "handle" in getattr(base, "__abstractmethods__", frozenset())

    @pytest.mark.parametrize("base", list(_TIER_BASES))
    def test_the_other_abstract_methods_survive(self, base: type[Handler]) -> None:
        """Re-declaring one abstract method must not drop the rest."""
        required = {"matches", "handle", "get_claude_md", "get_acceptance_tests"}

        assert required <= set(getattr(base, "__abstractmethods__", frozenset()))


class TestEveryWiredEventHasABase:
    """A missing base means that event's handlers get no protection at all."""

    @pytest.mark.parametrize("meta", _wired_event_metas(), ids=lambda m: str(m.json_key))
    def test_the_event_has_a_named_base(self, meta: EventIDMeta) -> None:
        assert hasattr(handler_bases, f"{meta.json_key}{_SUFFIX}"), (
            f"no {meta.json_key}{_SUFFIX} — a handler for this event has no base "
            "to inherit its constraint from"
        )

    @pytest.mark.parametrize("meta", _wired_event_metas(), ids=lambda m: str(m.json_key))
    def test_the_base_matches_the_events_capability(self, meta: EventIDMeta) -> None:
        base = getattr(handler_bases, f"{meta.json_key}{_SUFFIX}")
        returned = get_type_hints(base.handle)["return"]

        assert decisions_of(returned) == decisions_carried_by(_schema_key(meta)), (
            f"{meta.json_key}{_SUFFIX} returns {returned.__name__}, which does not "
            "match what this event can deliver — it either forbids a legal "
            "decision or permits one the event drops"
        )

    def test_the_base_agrees_with_the_result_tier_mapping(self) -> None:
        """Two routes to the same answer must not disagree."""
        for meta in _wired_event_metas():
            base = getattr(handler_bases, f"{meta.json_key}{_SUFFIX}")
            returned = get_type_hints(base.handle)["return"]

            assert returned is result_type_for_event(_schema_key(meta))


class TestTheLookupHelperAgreesWithTheNames:
    """``handler_base_for_event`` is what tooling uses; it must not drift."""

    @pytest.mark.parametrize("event_name", sorted(RESPONSE_SCHEMAS))
    def test_the_helper_returns_a_base_matching_the_event(self, event_name: str) -> None:
        base = handler_base_for_event(event_name)
        returned = get_type_hints(base.handle)["return"]

        assert decisions_of(returned) == decisions_carried_by(event_name)

    def test_the_known_assignments_hold(self) -> None:
        assert handler_base_for_event("PreToolUse") is GatingHandler
        assert handler_base_for_event("PermissionRequest") is BlockingHandler
        assert handler_base_for_event("Stop") is BlockingHandler
        assert handler_base_for_event("PostToolUse") is BlockingHandler
        assert handler_base_for_event("SessionStart") is AdvisoryHandler
        assert handler_base_for_event("Status") is AdvisoryHandler

    def test_an_unknown_event_fails_fast(self) -> None:
        """Same reasoning as ``result_type_for_event`` — never guess a tier."""
        with pytest.raises(ValueError, match="NoSuchEventXYZ"):
            handler_base_for_event("NoSuchEventXYZ")


class TestTheAliasesDoNotCollideWithConcreteHandlers:
    """The reason for the ``HandlerBase`` suffix, asserted so it is not undone."""

    def test_no_base_name_matches_a_shipped_handler_class(self) -> None:
        shipped = {name for name, _cls, _event in _handlers_with_event_names()}
        shipped |= {name for name, _cls in _concrete_handlers_in("nitpick")}
        base_names = {f"{meta.json_key}{_SUFFIX}" for meta in _wired_event_metas()}
        base_names |= {base.__name__ for base in _TIER_BASES}

        collisions = sorted(shipped & base_names)

        assert not collisions, f"base name collides with a concrete handler: {collisions}"


class TestEveryHandlerDescendsFromItsEventBase:
    """A base nothing inherits from protects nothing.

    Phase 2 added the bases; this is what makes them binding. Without it a new
    handler can subclass ``Handler`` directly and silently opt out of the whole
    guarantee — no error, no warning, just a handler that can construct a
    decision its event drops.

    The check is derived from the handler PACKAGES, so a handler added later is
    covered on the commit that adds it rather than when someone remembers.
    """

    def test_the_sweep_is_not_vacuous(self) -> None:
        """Every assertion below passes trivially on an empty population."""
        assert len(_handlers_with_event_names()) > 50

    def test_each_handler_subclasses_its_events_base(self) -> None:
        failures: list[str] = []
        for name, handler_class, event_name in _handlers_with_event_names():
            base = handler_base_for_event(event_name)
            if not issubclass(handler_class, base):
                failures.append(
                    f"{name} answers {event_name} but does not descend from " f"{base.__name__}"
                )

        assert not failures, (
            "these handlers subclass Handler directly, so nothing stops them "
            "returning a decision their event cannot deliver:\n  " + "\n  ".join(failures)
        )

    def test_each_handlers_declared_return_matches_its_tier(self) -> None:
        """Inheriting the base is not enough if ``handle`` re-widens the return.

        mypy rejects that as an ``[override]``, but only for code mypy checks —
        and this repository's own QA is the only place that runs. Asserting it
        here means the property holds for the shipped classes themselves.
        """
        failures: list[str] = []
        for name, handler_class, event_name in _handlers_with_event_names():
            declared = get_type_hints(handler_class.handle).get("return")
            expected = result_type_for_event(event_name)
            if declared is not expected:
                failures.append(
                    f"{name} on {event_name} declares "
                    f"{getattr(declared, '__name__', declared)}, expected {expected.__name__}"
                )

        assert not failures, "handle() re-widened past its event's tier:\n  " + "\n  ".join(
            failures
        )


class TestThePseudoEventHandlersAreDeliberatelyExempt:
    """``nitpick`` handlers have no event of their own, so no fixed tier.

    A pseudo-event's decision is delivered under whichever REAL event triggered
    it, and triggers are per-project CONFIG — the same handler is gating under
    one project's config and advisory under another's. There is no single base
    that is correct for it, so these stay on plain ``Handler``.

    What protects them instead is ``merge_pseudo_results``, which clamps to the
    trigger event's tier at dispatch time (Phase 4), plus the trigger sweep in
    ``test_every_handler_response_validates.py``. Recorded as a test rather than
    a comment so the exemption cannot quietly grow to cover something else.
    """

    def test_nitpick_handlers_are_not_reparented(self) -> None:
        for name, handler_class in _concrete_handlers_in("nitpick"):
            assert not issubclass(
                handler_class, (AdvisoryHandler, BlockingHandler, GatingHandler)
            ), (
                f"{name} was given a fixed tier, but its deliverability depends "
                "on a per-project trigger. Clamp at merge time instead."
            )

    def test_the_exemption_names_a_package_that_exists(self) -> None:
        """A stale exemption would silently excuse nothing at all."""
        assert _concrete_handlers_in("nitpick")


class TestTheNarrowingIsRealAtTheBase:
    """A base returning plain HookResult would constrain nothing."""

    @pytest.mark.parametrize("base", list(_TIER_BASES))
    def test_the_return_type_is_not_the_unnarrowed_result(self, base: type[Handler]) -> None:
        assert get_type_hints(base.handle)["return"] is not HookResult

    def test_the_restrictive_tiers_really_restrict(self) -> None:
        """Gating permits every decision by design; the other two must not."""
        assert decisions_of(AdvisoryResult) < set(Decision)
        assert decisions_of(BlockingResult) < set(Decision)
        assert Decision.DENY not in decisions_of(AdvisoryResult)
        assert Decision.ASK not in decisions_of(BlockingResult)
