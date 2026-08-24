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
        assert handler_base_for_event("PermissionRequest") is GatingHandler
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
