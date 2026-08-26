"""Handler chain execution logic.

This module provides the HandlerChain class that executes handlers
in priority order with support for terminal and non-terminal handlers.
"""

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from claude_code_hooks_daemon.constants import Priority
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult

if TYPE_CHECKING:
    from claude_code_hooks_daemon.core.handler import Handler

logger = logging.getLogger(__name__)

# Decisions that restrict the tool call. Once any handler records one, later
# laxer results (ALLOW/CONTINUE) must never overwrite it — the most
# restrictive decision wins across the whole chain (Plan 00144).
_RESTRICTIVE_DECISIONS: frozenset[Decision] = frozenset(
    {Decision.DENY, Decision.ASK, Decision.DEFER}
)


def _is_restrictive(decision: Decision | str | None) -> bool:
    """True when ``decision`` restricts the tool call (deny/ask/defer)."""
    return decision in _RESTRICTIVE_DECISIONS


@dataclass(frozen=True, slots=True)
class HandlerVerdict:
    """One matched handler's OWN decision from a single chain execution.

    Plan 00209 (verdict log): the chain-level ``ChainExecutionResult.result``
    is the MERGED outcome (most-restrictive-decision-wins, Plan 00144), which
    is the wrong thing to attribute to every matched handler — a non-terminal
    handler whose deny is superseded by nothing still made a real decision,
    and a handler whose result got overridden by an earlier restrictive
    decision still deserves its own accurate record. This is captured once,
    here, in the chain loop — not by each handler opting in.

    Attributes:
        handler: Name of the handler that produced this verdict.
        decision: The handler's OWN decision (never the chain's merged one).
        terminal: Whether this handler is registered as terminal.
        rule: Optional handler-set sub-classification (``HookResult.rule``),
            e.g. pipe_blocker's "blacklisted" vs "unknown". None when the
            handler did not set one — most handlers never do, and that is
            fine; the verdict log records it as null in that case.
    """

    handler: str
    decision: Decision
    terminal: bool
    rule: str | None = None


@dataclass(slots=True)
class ChainExecutionResult:
    """Result of handler chain execution.

    Attributes:
        result: The final HookResult
        handlers_executed: List of handler names that were executed
        handlers_matched: List of handler names that matched
        execution_time_ms: Total execution time in milliseconds
        terminated_by: Handler name that terminated the chain (if any)
        decisions: Per-handler verdicts (Plan 00209) — one entry per matched
            handler that actually returned a decision (a handler that raised
            an exception made no verdict and is not recorded here).
    """

    result: HookResult
    handlers_executed: list[str] = field(default_factory=list)
    handlers_matched: list[str] = field(default_factory=list)
    execution_time_ms: float = 0.0
    terminated_by: str | None = None
    # Handler that OWNS the restrictive decision (deny/ask), when any — the
    # correct attribution target for the "To disable:" footer (Plan 00144).
    decided_by: str | None = None
    decisions: list[HandlerVerdict] = field(default_factory=list)


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
        """Get handlers in priority order (then alphabetically by name for ties)."""
        if not self._sorted:
            # Defence in depth: fix any None priorities before sorting (Plan 00070)
            for handler in self._handlers:
                if handler.priority is None:
                    logger.warning(
                        "Handler '%s' has None priority — applying default (%d). "
                        "Set an explicit priority in the handler or config.",
                        handler.name,
                        Priority.DEFAULT,
                    )
                    handler.priority = Priority.DEFAULT

            # Check for duplicate priorities and log warnings
            priority_map: dict[int, list[str]] = {}
            for handler in self._handlers:
                if handler.priority not in priority_map:
                    priority_map[handler.priority] = []
                priority_map[handler.priority].append(handler.name)

            # Log warnings for duplicate priorities
            for priority, handler_names in priority_map.items():
                if len(handler_names) > 1:
                    sorted_names = sorted(handler_names)
                    logger.debug(
                        f"Duplicate priority {priority} detected for handlers: {', '.join(sorted_names)}. "
                        f"Using alphabetical order for determinism: {' -> '.join(sorted_names)}"
                    )

            # Sort by priority first, then alphabetically by name for determinism
            self._handlers.sort(key=lambda h: (h.priority, h.name))
            self._sorted = True
        return self._handlers

    def __len__(self) -> int:
        """Return number of handlers in chain."""
        return len(self._handlers)

    def __iter__(self) -> Iterator["Handler"]:
        """Iterate over handlers in priority order."""
        return iter(self.handlers)

    def execute(
        self, hook_input: dict[str, Any], strict_mode: bool = False
    ) -> ChainExecutionResult:
        """Execute the handler chain for an event.

        Handlers are executed in priority order. Terminal handlers stop
        execution and return immediately. Non-terminal handlers accumulate
        context and continue.

        Args:
            hook_input: Hook input dictionary to process
            strict_mode: If True, FAIL FAST on handler exceptions (fail-closed).
                        If False, log and continue (fail-open).

        Returns:
            ChainExecutionResult with final result and metadata
        """
        start_time = time.perf_counter()
        accumulated_context: list[str] = []
        handlers_executed: list[str] = []
        handlers_matched: list[str] = []
        final_result: HookResult | None = None
        terminated_by: str | None = None
        decided_by: str | None = None
        decisions: list[HandlerVerdict] = []

        for handler in self.handlers:
            try:
                if handler.matches(hook_input):
                    handlers_matched.append(handler.name)
                    logger.debug("Handler %s matched event", handler.name)

                    result = handler.handle(hook_input)
                    logger.debug(
                        "Handler %s returned decision=%s, terminal=%s",
                        handler.name,
                        result.decision,
                        handler.terminal,
                    )
                    handlers_executed.append(handler.name)
                    result.add_handler(handler.name)

                    # Record THIS handler's own verdict now, before any later
                    # handler's laxer/stricter result can change what the
                    # eventual merged chain decision looks like (Plan 00209).
                    decisions.append(
                        HandlerVerdict(
                            handler=handler.name,
                            decision=result.decision,
                            terminal=handler.terminal,
                            rule=result.rule,
                        )
                    )

                    # First restrictive decision wins attribution: this is the
                    # handler the "To disable:" footer must name.
                    if decided_by is None and _is_restrictive(result.decision):
                        decided_by = handler.name

                    if handler.terminal:
                        # Terminal handler - stop chain. The chain outcome keeps
                        # the most RESTRICTIVE decision recorded so far: a laxer
                        # terminal result must not wash out an earlier
                        # non-terminal deny (Plan 00144 regression).
                        if (
                            final_result is not None
                            and _is_restrictive(final_result.decision)
                            and not _is_restrictive(result.decision)
                        ):
                            accumulated_context.extend(result.context)
                            final_result.context = list(accumulated_context)
                        else:
                            if accumulated_context:
                                result.context = accumulated_context + result.context
                            final_result = result
                            # This terminal result REPLACES whatever was held,
                            # so attribution must follow it (Plan 00190 Task
                            # 0.5). Otherwise the reason shown comes from this
                            # handler while the "To disable:" footer names an
                            # earlier non-terminal denier — pointing the user
                            # at the wrong config key.
                            if _is_restrictive(result.decision):
                                decided_by = handler.name
                        for h in handlers_matched[:-1]:
                            final_result.add_handler(h)
                        terminated_by = handler.name
                        break
                    else:
                        # Non-terminal - accumulate context. The most restrictive
                        # decision seen so far survives later, laxer results: a
                        # deny from a non-terminal blocking handler cannot be
                        # silently overwritten by a later advisory ALLOW
                        # (Plan 00144 regression: plan_qa_edit's deny at priority
                        # 44 was lost when markdown_organization's ALLOW landed
                        # at priority 50).
                        accumulated_context.extend(result.context)
                        if final_result is None or not _is_restrictive(final_result.decision):
                            final_result = result

            except Exception as e:
                logger.exception("Handler %s raised exception", handler.name)
                handlers_executed.append(handler.name)

                if strict_mode:
                    # STRICT MODE: FAIL FAST - handler crash = BLOCK operation (fail-closed)
                    error_result = HookResult.deny(
                        reason=f"SYSTEM ERROR: Handler {handler.name} crashed - blocking for safety",
                    )
                    error_result.context.append(f"Handler exception: {type(e).__name__}: {e}")
                    error_result.add_handler(handler.name)

                    # Stop chain immediately - this is terminal
                    if accumulated_context:
                        error_result.context = accumulated_context + error_result.context
                    final_result = error_result
                    terminated_by = handler.name
                    if decided_by is None:
                        decided_by = handler.name
                    break
                else:
                    # NON-STRICT MODE: Fail-open - log error and continue chain
                    error_context = f"Handler exception: {type(e).__name__}: {e}"
                    accumulated_context.append(error_context)
                    # Continue to next handler

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
            decided_by=decided_by,
            decisions=decisions,
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
