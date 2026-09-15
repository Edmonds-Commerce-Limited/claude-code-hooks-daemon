"""The must-do list: every SessionStart handler whose verifier is failing NOW.

Plan 00416 Task 1.2 introduced this as a private helper inside the
``session-actions`` CLI command. Task 2.3 gave it a second caller -- the
``session_actions_directive`` SessionStart handler, which counts the same
list to decide whether the ccy supervisor should type a directive at all --
and two independent implementations of "what is ACTION_REQUIRED right now"
would be a defect waiting to happen: the directive's entire content is *run
that command*, so a directive that fires while the command reports nothing
teaches the agent to ignore the next one, which is exactly the failure Plan
00416 exists to fix.

Discovery walks the registry directly rather than dispatching a real
SessionStart event, so it works without a running daemon -- that is what lets
a human type ``hooks-daemon session-actions`` to inspect a session.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

logger = logging.getLogger(__name__)

#: The event directory this collector scans -- SessionStart only. The tier
#: mechanism itself (``core.session_start_tiers``) is event-agnostic; this is
#: the one place that says "only SessionStart handlers are asked".
SESSION_START_EVENT_DIR: Final[str] = "session_start"

_CLAUDE_DIR: Final[str] = ".claude"
_CONFIG_FILENAME: Final[str] = "hooks-daemon.yaml"


@dataclass(frozen=True, slots=True)
class SessionActionItem:
    """One currently-ACTION_REQUIRED SessionStart handler.

    Deliberately thin: the full advisory text already reaches the agent
    through the tagged SessionStart block
    (``session_start_tiers.prefix_context_with_tier``) every session start.
    This exists to let the agent re-fetch the SHORT must-do list on demand,
    not to duplicate the advisory prose.
    """

    config_key: str
    class_name: str
    handler_name: str


def _session_start_config(project_root: Path | None) -> dict[str, Any]:
    """The ``handlers.session_start`` config block, or an empty one.

    A project with no config, or an unreadable one, yields ``{}`` -- which
    means "every handler is enabled", the same default registration applies.
    """
    if project_root is None:
        return {}
    config_path = project_root / _CLAUDE_DIR / _CONFIG_FILENAME
    if not config_path.exists():
        return {}
    from pydantic import ValidationError as PydanticValidationError

    from claude_code_hooks_daemon.config.models import Config

    try:
        config = Config.load(config_path)
    except (PydanticValidationError, OSError, ValueError) as exc:
        logger.debug("Could not load config for session-actions: %s", exc)
        return {}
    return config.handlers.model_dump().get(SESSION_START_EVENT_DIR) or {}


def collect_session_action_items(project_root: Path | None) -> list[SessionActionItem]:
    """Every SessionStart handler whose verifier is CURRENTLY failing.

    A handler that fails to instantiate, or is disabled by config, is
    silently excluded rather than reported as an error -- an ACTION_REQUIRED
    item for a handler that cannot even run would be a command with nothing
    actionable to say about it.

    ``compute_tier`` already degrades a raising verifier to the declared tier
    internally, so one broken verifier cannot hide another handler's genuine
    item, and nothing raises out of this loop.

    Args:
        project_root: Resolved project root, or ``None`` if unresolvable.

    Returns:
        Items for handlers computed as ACTION_REQUIRED right now, sorted by
        config key for stable output.
    """
    from claude_code_hooks_daemon.core.session_start_tiers import SessionTier, compute_tier
    from claude_code_hooks_daemon.handlers.registry import (
        HandlerRegistry,
        _get_config_key,
        event_dir_name_matches_module,
        handler_is_enabled,
    )

    event_config = _session_start_config(project_root)

    registry = HandlerRegistry()
    registry.discover()

    items: list[SessionActionItem] = []
    for handler_class_name in registry.list_handlers():
        handler_class = registry.get_handler_class(handler_class_name)
        if handler_class is None:
            continue
        if not event_dir_name_matches_module(SESSION_START_EVENT_DIR, handler_class.__module__):
            continue

        config_key = _get_config_key(handler_class_name)

        try:
            instance = handler_class()
        except Exception:
            logger.exception("Failed to instantiate %s for session-actions", handler_class_name)
            continue

        if not handler_is_enabled(event_config, config_key, instance.tags):
            continue

        if compute_tier(instance) is not SessionTier.ACTION_REQUIRED:
            continue

        items.append(
            SessionActionItem(
                config_key=config_key,
                class_name=handler_class_name,
                handler_name=instance.name,
            )
        )

    items.sort(key=lambda item: item.config_key)
    return items
