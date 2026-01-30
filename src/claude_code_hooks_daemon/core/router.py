"""Event router for directing events to appropriate handler chains.

This module provides the EventRouter class that routes hook events
to the correct handler chain based on event type.
"""

import logging
from typing import TYPE_CHECKING, Any

from claude_code_hooks_daemon.core.chain import ChainExecutionResult, HandlerChain
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.hook_result import HookResult

if TYPE_CHECKING:
    from claude_code_hooks_daemon.core.handler import Handler

logger = logging.getLogger(__name__)


class EventRouter:
    """Routes hook events to appropriate handler chains.

    Maintains a separate handler chain for each event type and routes
    incoming events to the correct chain for processing.

    Attributes:
        chains: Mapping of event type to handler chain
    """

    __slots__ = ("_chains",)

    def __init__(self) -> None:
        """Initialise router with empty chains for all event types."""
        self._chains: dict[EventType, HandlerChain] = {
            event_type: HandlerChain() for event_type in EventType
        }

    def get_chain(self, event_type: EventType) -> HandlerChain:
        """Get the handler chain for an event type.

        Args:
            event_type: Event type to get chain for

        Returns:
            Handler chain for the event type
        """
        return self._chains[event_type]

    def register(self, event_type: EventType, handler: "Handler") -> None:
        """Register a handler for a specific event type.

        Args:
            event_type: Event type to register handler for
            handler: Handler to register
        """
        chain = self._chains[event_type]
        chain.add(handler)
        logger.debug(
            "Registered handler %s for %s (priority=%d, terminal=%s)",
            handler.name,
            event_type.value,
            handler.priority,
            handler.terminal,
        )

    def register_for_all(self, handler: "Handler") -> None:
        """Register a handler for all event types.

        Args:
            handler: Handler to register
        """
        for event_type in EventType:
            self.register(event_type, handler)

    def unregister(self, event_type: EventType, handler_name: str) -> bool:
        """Unregister a handler by name from a specific event type.

        Args:
            event_type: Event type to unregister from
            handler_name: Name of handler to remove

        Returns:
            True if handler was found and removed
        """
        return self._chains[event_type].remove(handler_name)

    def route(self, event_type: EventType, hook_input: dict[str, Any]) -> ChainExecutionResult:
        """Route an event to its handler chain.

        Args:
            event_type: Type of hook event
            hook_input: Hook input dictionary

        Returns:
            Execution result from the handler chain
        """
        chain = self._chains[event_type]
        logger.debug(
            "Routing %s event to chain with %d handlers",
            event_type.value,
            len(chain),
        )

        # DEBUG: Log full hook_input for PreToolUse to debug pipe blocker
        if event_type == EventType.PRE_TOOL_USE:
            import json

            logger.debug(
                "PRE_TOOL_USE hook_input:\n%s",
                json.dumps(hook_input, indent=2, default=str),
            )

        return chain.execute(hook_input)

    def route_by_string(self, event_type_str: str, hook_input: dict[str, Any]) -> HookResult:
        """Route with string event type.

        Convenience method that converts string event type.

        Args:
            event_type_str: Event type as string
            hook_input: Raw hook input dictionary

        Returns:
            HookResult from chain execution
        """
        event_type = EventType.from_string(event_type_str)
        result = self.route(event_type, hook_input)
        return result.result

    def get_all_handlers(self) -> dict[str, list["Handler"]]:
        """Get all registered handlers grouped by event type.

        Returns:
            Dictionary mapping event type name to list of handlers
        """
        return {
            event_type.value: list(chain.handlers) for event_type, chain in self._chains.items()
        }

    def get_handler_count(self) -> dict[str, int]:
        """Get handler count for each event type.

        Returns:
            Dictionary mapping event type name to handler count
        """
        return {event_type.value: len(chain) for event_type, chain in self._chains.items()}

    def clear(self) -> None:
        """Remove all handlers from all chains."""
        for chain in self._chains.values():
            chain.clear()

    def __repr__(self) -> str:
        """Return string representation."""
        counts = self.get_handler_count()
        total = sum(counts.values())
        return f"EventRouter(total_handlers={total}, by_type={counts})"
