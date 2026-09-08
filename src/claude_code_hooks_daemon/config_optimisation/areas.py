"""The areas the config-optimisation report groups handlers into (Plan 00330).

Decision 3: five areas derived by a precedence rule over each handler's
event and tags, plus a sixth catch-all so every registered handler lands
somewhere without a tagging pass. Nothing in the registry names an area;
membership is COMPUTED here, and only here, so a new handler is classified
the moment it exists.

The order of the rules is load-bearing and was measured, not designed
(SURFACE-INVENTORY.md §1.3): ``auto_continue_stop`` carries the ``planning``
tag, and the nitpick pair carry ``content-quality``, so the event rule for
agent-behaviour handlers must run BEFORE any tag rule or those handlers land
in the wrong area.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Final

from claude_code_hooks_daemon.constants.tags import HandlerTag


class Area(StrEnum):
    """A report area. The value is the heading a human reads."""

    SAFETY = "Safety"
    AGENT_BEHAVIOUR = "Agent behaviour & message quality"
    PLAN_DOCS = "Plan & documentation workflow"
    CODE_QUALITY = "Code & content quality"
    SESSION_ENV = "Session, environment & daemon"
    OTHER = "Other guards"


#: Report order. ``OTHER`` is last by construction: it is the remainder.
AREA_ORDER: Final[tuple[Area, ...]] = (
    Area.SAFETY,
    Area.AGENT_BEHAVIOUR,
    Area.PLAN_DOCS,
    Area.CODE_QUALITY,
    Area.SESSION_ENV,
    Area.OTHER,
)

_AGENT_BEHAVIOUR_EVENTS: Final[frozenset[str]] = frozenset({"stop", "subagent_stop", "nitpick"})
_SESSION_ENV_EVENTS: Final[frozenset[str]] = frozenset({"session_start", "status_line"})

_AGENT_BEHAVIOUR_TAGS: Final[frozenset[str]] = frozenset({HandlerTag.CONTEXT_INJECTION})
_SAFETY_TAGS: Final[frozenset[str]] = frozenset({HandlerTag.SAFETY})
_PLAN_DOCS_TAGS: Final[frozenset[str]] = frozenset({HandlerTag.PLANNING, HandlerTag.DOCUMENTATION})
_CODE_QUALITY_TAGS: Final[frozenset[str]] = frozenset(
    {
        HandlerTag.QA_ENFORCEMENT,
        HandlerTag.VALIDATION,
        HandlerTag.CONTENT_QUALITY,
        HandlerTag.TDD,
    }
)
_SESSION_ENV_TAGS: Final[frozenset[str]] = frozenset(
    {HandlerTag.ENVIRONMENT, HandlerTag.DAEMON, HandlerTag.HEALTH}
)


def area_for(event: str, tags: Iterable[str]) -> Area:
    """The area a handler belongs to, from its event directory and tags.

    First match wins, in this order: agent-behaviour EVENTS, then the tag
    rules for safety, plan/docs, code quality, agent behaviour and
    session/environment, then the session/environment EVENTS, and finally
    the catch-all. Total: never raises, never returns None.
    """
    tag_set = frozenset(tags)
    if event in _AGENT_BEHAVIOUR_EVENTS:
        return Area.AGENT_BEHAVIOUR
    if tag_set & _SAFETY_TAGS:
        return Area.SAFETY
    if tag_set & _PLAN_DOCS_TAGS:
        return Area.PLAN_DOCS
    if tag_set & _CODE_QUALITY_TAGS:
        return Area.CODE_QUALITY
    if tag_set & _AGENT_BEHAVIOUR_TAGS:
        return Area.AGENT_BEHAVIOUR
    if tag_set & _SESSION_ENV_TAGS or event in _SESSION_ENV_EVENTS:
        return Area.SESSION_ENV
    return Area.OTHER
