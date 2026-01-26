"""Handler chain execution logic.

This module provides the HandlerChain class that executes handlers
in priority order with support for terminal and non-terminal handlers.
"""

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from claude_code_hooks_daemon.core.hook_result import HookResult

if TYPE_CHECKING:
    from claude_code_hooks_daemon.core.handler import Handler

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ChainExecutionResult:
    """Result of handler chain execution.

    Attributes:
        result: The final HookResult
        handlers_executed: List of handler names that were executed
        handlers_matched: List of handler names that matched
        execution_time_ms: Total execution time in milliseconds
        terminated_by: Handler name that terminated the chain (if any)
    """

    result: HookResult
    handlers_executed: list[str] = field(default_factory=list)
    handlers_matched: list[str] = field(default_factory=list)
    execution_time_ms: float = 0.0
    terminated_by: str | None = None


class HandlerChain:
    """Executes handlers in priority order.

    Implements the Chain of Responsibility pattern with support for:
    - Priority-based ordering (lower = earlier)
    - Terminal handlers that stop the chain
    - Non-terminal handlers that accumulate context
    - Error handling with fail-open semantics
    """

    __slots__ = ("_handlers", "_sorted")

    def __init__(self) -> None:
        """Initialise empty handler chain."""
        self._handlers: list[Handler] = []
        self._sorted = True

    def add(self, handler: "Handler") -> None:
        """Add a handler to the chain.

        Args:
            handler: Handler to add
        """
        self._handlers.append(handler)
        self._sorted = False

    def remove(self, handler_name: str) -> bool:
        """Remove a handler by name.

        Args:
            handler_name: Name of handler to remove

        Returns:
            True if handler was found and removed
        """
        for i, handler in enumerate(self._handlers):
            if handler.name == handler_name:
                del self._handlers[i]
                return True
        return False

    def get(self, handler_name: str) -> "Handler | None":
        """Get a handler by name.

        Args:
            handler_name: Name of handler to find

        Returns:
            Handler if found, None otherwise
        """
        for handler in self._handlers:
            if handler.name == handler_name:
                return handler
        return None

    def clear(self) -> None:
        """Remove all handlers from the chain."""
        self._handlers.clear()
        self._sorted = True

    @property
    def handlers(self) -> list["Handler"]:
        """Get handlers in priority order."""
        if not self._sorted:
            self._handlers.sort(key=lambda h: h.priority)
            self._sorted = True
        return self._handlers

    def __len__(self) -> int:
        """Return number of handlers in chain."""
        return len(self._handlers)

    def __iter__(self) -> Iterator["Handler"]:
        """Iterate over handlers in priority order."""
        return iter(self.handlers)

    def execute(self, hook_input: dict[str, Any]) -> ChainExecutionResult:
        """Execute the handler chain for an event.

        Handlers are executed in priority order. Terminal handlers stop
        execution and return immediately. Non-terminal handlers accumulate
        context and continue.

        Args:
            hook_input: Hook input dictionary to process

        Returns:
            ChainExecutionResult with final result and metadata
        """
        start_time = time.perf_counter()
        accumulated_context: list[str] = []
        handlers_executed: list[str] = []
        handlers_matched: list[str] = []
        final_result: HookResult | None = None
        terminated_by: str | None = None

        for handler in self.handlers:
            try:
                if handler.matches(hook_input):
                    handlers_matched.append(handler.name)
                    logger.debug("Handler %s matched event", handler.name)

                    result = handler.handle(hook_input)
                    handlers_executed.append(handler.name)
                    result.add_handler(handler.name)

                    if handler.terminal:
                        # Terminal handler - stop chain
                        if accumulated_context:
                            result.context = accumulated_context + result.context
                        for h in handlers_matched[:-1]:
                            result.add_handler(h)
                        terminated_by = handler.name
                        final_result = result
                        break
                    else:
                        # Non-terminal - accumulate context
                        accumulated_context.extend(result.context)
                        final_result = result

            except Exception as e:
                logger.exception("Handler %s raised exception", handler.name)
                handlers_executed.append(handler.name)

                # Fail-open: create error result but don't stop chain
                error_result = HookResult.error(
                    error_type="handler_exception",
                    error_details=f"{handler.name}: {type(e).__name__}: {e}",
                )
                error_result.add_handler(handler.name)
                accumulated_context.extend(error_result.context)

        # Build final result
        if final_result is None:
            final_result = HookResult.allow()

        # Ensure all context is included
        if accumulated_context and final_result.context != accumulated_context:
            if terminated_by:
                # Already merged above
                pass
            else:
                final_result.context = accumulated_context

        # Record all matched handlers
        for h in handlers_matched:
            final_result.add_handler(h)

        execution_time_ms = (time.perf_counter() - start_time) * 1000

        return ChainExecutionResult(
            result=final_result,
            handlers_executed=handlers_executed,
            handlers_matched=handlers_matched,
            execution_time_ms=execution_time_ms,
            terminated_by=terminated_by,
        )

    def execute_legacy(self, hook_input: dict[str, Any]) -> HookResult:
        """Execute chain with legacy dict input.

        For backward compatibility with existing code.

        Args:
            hook_input: Raw hook input dictionary

        Returns:
            HookResult from chain execution
        """
        result = self.execute(hook_input)
        return result.result
