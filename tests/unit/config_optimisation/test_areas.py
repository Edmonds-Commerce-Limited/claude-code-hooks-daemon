"""The optimise report's areas are derived, never hand-assigned (Plan 00330).

Decision 3: the five areas from SURFACE-INVENTORY.md §1.3 stand, membership
computed by a precedence rule over event and tags, plus a sixth "Other
guards" catch-all so no handler is ever unclassified and no tagging pass
gates delivery. The inventory measured that event rules must precede tag
rules (``auto_continue_stop`` carries ``planning``), which is pinned here.
"""

from __future__ import annotations

from claude_code_hooks_daemon.config_optimisation.areas import (
    _AGENT_BEHAVIOUR_EVENTS,
    _SESSION_ENV_EVENTS,
    AREA_ORDER,
    Area,
    area_for,
)
from claude_code_hooks_daemon.constants.events import EventID, all_event_metas
from claude_code_hooks_daemon.constants.tags import HandlerTag
from claude_code_hooks_daemon.handlers.registry import iter_builtin_handler_classes
from claude_code_hooks_daemon.pseudo_events.registry import NITPICK


class TestEventsAreNamedByTheEventCatalogue:
    """The event rules key on the catalogue's own spellings, not copies of them.

    A copy does not fail when an event key is renamed: the set simply stops
    matching, and the handler lands under "Other guards". Nothing raises.
    """

    def test_every_named_event_exists_in_the_catalogue(self) -> None:
        known = {meta.config_key for meta in all_event_metas()} | {NITPICK}
        assert _AGENT_BEHAVIOUR_EVENTS <= known
        assert _SESSION_ENV_EVENTS <= known

    def test_the_named_events_are_the_ones_the_rules_intend(self) -> None:
        assert _AGENT_BEHAVIOUR_EVENTS == {
            EventID.STOP.config_key,
            EventID.SUBAGENT_STOP.config_key,
            NITPICK,
        }
        assert _SESSION_ENV_EVENTS == {
            EventID.SESSION_START.config_key,
            EventID.STATUS_LINE.config_key,
        }


class TestPrecedence:
    def test_stop_event_wins_over_planning_tag(self) -> None:
        assert area_for("stop", [HandlerTag.PLANNING]) is Area.AGENT_BEHAVIOUR

    def test_nitpick_event_wins_over_content_quality_tag(self) -> None:
        assert area_for("nitpick", [HandlerTag.CONTENT_QUALITY]) is Area.AGENT_BEHAVIOUR

    def test_subagent_stop_is_agent_behaviour(self) -> None:
        assert area_for("subagent_stop", []) is Area.AGENT_BEHAVIOUR

    def test_context_injection_tag_is_agent_behaviour(self) -> None:
        assert area_for("user_prompt_submit", [HandlerTag.CONTEXT_INJECTION]) is (
            Area.AGENT_BEHAVIOUR
        )

    def test_safety_tag(self) -> None:
        assert area_for("pre_tool_use", [HandlerTag.SAFETY, HandlerTag.GIT]) is Area.SAFETY

    def test_safety_beats_planning(self) -> None:
        assert area_for("pre_tool_use", [HandlerTag.PLANNING, HandlerTag.SAFETY]) is Area.SAFETY

    def test_planning_and_documentation_tags(self) -> None:
        assert area_for("pre_tool_use", [HandlerTag.PLANNING]) is Area.PLAN_DOCS
        assert area_for("pre_tool_use", [HandlerTag.DOCUMENTATION]) is Area.PLAN_DOCS

    def test_quality_tags(self) -> None:
        for tag in (
            HandlerTag.QA_ENFORCEMENT,
            HandlerTag.VALIDATION,
            HandlerTag.CONTENT_QUALITY,
            HandlerTag.TDD,
        ):
            assert area_for("pre_tool_use", [tag]) is Area.CODE_QUALITY, tag

    def test_session_start_event_and_environment_tags(self) -> None:
        assert area_for("session_start", []) is Area.SESSION_ENV
        assert area_for("status_line", []) is Area.SESSION_ENV
        for tag in (HandlerTag.ENVIRONMENT, HandlerTag.DAEMON, HandlerTag.HEALTH):
            assert area_for("post_tool_use", [tag]) is Area.SESSION_ENV, tag

    def test_untagged_falls_to_other_guards(self) -> None:
        assert area_for("pre_tool_use", []) is Area.OTHER
        assert area_for("pre_tool_use", [HandlerTag.WORKFLOW, HandlerTag.ADVISORY]) is Area.OTHER


class TestTotality:
    def test_order_lists_every_area_once(self) -> None:
        assert sorted(AREA_ORDER, key=str) == sorted(Area, key=str)
        assert AREA_ORDER[-1] is Area.OTHER

    def test_every_registered_handler_has_an_area(self) -> None:
        for ref in iter_builtin_handler_classes():
            instance = ref.handler_cls.__new__(ref.handler_cls)
            tags = getattr(instance, "tags", None)
            # Tags are set in __init__; classify from the class's declared
            # tags when instantiation is avoided, else from the instance.
            area = area_for(ref.event_dir, tags or [])
            assert isinstance(area, Area)
