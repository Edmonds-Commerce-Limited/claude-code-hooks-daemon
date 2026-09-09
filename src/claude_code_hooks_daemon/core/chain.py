"""Handler chain execution logic.

This module provides the HandlerChain class that executes handlers in
priority order and merges their results into one response.

Terminality is a property of the DECISION, not of the handler (Plan 00242):

- A restrictive decision (deny/ask/defer) from a ``terminal`` handler may end
  the chain — nothing later can un-deny it, so stopping is safe and cheap.
- An ALLOW/advisory result NEVER ends the chain, whatever the handler's
  ``terminal`` flag says. "I allow this, therefore nobody else may look" is
  not a coherent claim, and honouring it is how a terminal advisory ALLOW
  silently disabled every successor (the Plan 00241 defect class).
- The one exception is per-EVENT, not global: a chain built with
  ``allow_is_final=True`` (PermissionRequest, where "approve and stop" IS the
  semantic) lets a terminal ALLOW conclude the request.

The merge is most-restrictive-wins (Plan 00144); the FIRST restrictive handler
owns both the reason shown and the ``To disable:`` attribution (Task 3.3).
"""

import logging
import time
from collections.abc import Iterator, Sequence
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


def is_restrictive(decision: Decision | str | None) -> bool:
    """True when ``decision`` restricts the tool call (deny/ask/defer)."""
    return decision in _RESTRICTIVE_DECISIONS


# Result fields that carry INFORMATION rather than a decision, and so travel
# like ``context``: whichever result wins the decision, the first handler to
# set one of these owns it. Without this merge a contentless early ALLOW —
# the shape produced by a deliberately broad matches() whose handle() finds
# nothing — becomes the incumbent under most-restrictive-wins and every later
# handler's remedy text and input rewrite is dropped from the response.
_ACCUMULATED_RESULT_FIELDS: tuple[str, ...] = ("guidance", "updated_input", "worktree_path")


def carry_accumulated_fields(winner: HookResult, results: Sequence[HookResult]) -> None:
    """Merge every matched result's information fields onto the winning result.

    ``guidance``, ``updated_input`` and ``worktree_path`` are accumulated
    information, not a decision. The winner's own value always takes
    precedence — an ALLOW's guidance never displaces a DENY's, and nothing
    here touches ``reason`` — and any of the three the winner leaves unset is
    filled from the FIRST matched result that set it, the same first-wins rule
    the reason and the ``To disable:`` footer already follow.

    ``rule`` is deliberately treated differently: it sub-classifies the ONE
    decision that produced it, so it is only carried between results that
    agree on restrictiveness. An advisory's rule must never be reported as
    the rule that denied a call.

    Args:
        winner: The merged result the chain will return; mutated in place.
        results: Every matched handler's result, in chain order.
    """
    for field_name in _ACCUMULATED_RESULT_FIELDS:
        if getattr(winner, field_name) is not None:
            continue
        for result in results:
            value = getattr(result, field_name)
            if value is not None:
                setattr(winner, field_name, value)
                break

    if winner.rule is None:
        winner_restrictive = is_restrictive(winner.decision)
        for result in results:
            if result.rule is not None and is_restrictive(result.decision) == winner_restrictive:
                winner.rule = result.rule
                break


# Collect-all response bounds (Plan 00242 Task 3.4). The lead deny is never
# cut; everything after it is. Worst case beyond the lead is
# 4 x 1500 + 8 x 160 + framing, a little under 8 KB — well inside what a
# single deny reason already reaches today (sed_blocker's runs to ~5 KB).
COLLECT_ALL_MAX_EXTRA_DENIES = 4
COLLECT_ALL_DENY_EXCERPT_CHARS = 1500
COLLECT_ALL_MAX_ADVISORY_ROWS = 8
COLLECT_ALL_ADVISORY_EXCERPT_CHARS = 160

_COLLECT_ALL_DENY_HEADER = "--- Also denied by: {handler} ---"
_COLLECT_ALL_TRUNCATED = "\n[... truncated: {dropped} more characters]"
_COLLECT_ALL_ADVISORY_HEADER = "Advisories from this call (full text in additionalContext):"


def _excerpt(text: str, limit: int) -> str:
    """The first ``limit`` characters of ``text``, flagged when cut."""
    if len(text) <= limit:
        return text
    return text[:limit] + _COLLECT_ALL_TRUNCATED.format(dropped=len(text) - limit)


def _advisory_cell(result: HookResult) -> str:
    """One table cell: the first non-empty line of the first context entry."""
    first_line = next(
        (line.strip() for entry in result.context for line in entry.splitlines() if line.strip()),
        "",
    )
    cell = first_line.replace("|", "\\|")
    if len(cell) > COLLECT_ALL_ADVISORY_EXCERPT_CHARS:
        cell = cell[:COLLECT_ALL_ADVISORY_EXCERPT_CHARS].rstrip() + "..."
    return cell


def merge_violations(
    lead_reason: str | None,
    denials: list[tuple[str, HookResult]],
    advisories: list[tuple[str, HookResult]],
) -> str:
    """Build the one merged reason for collect-all mode (Plan 00242 Phase 3).

    ``denials`` are in chain order, so the first is the lead — the highest
    priority deny, which also owns ``decided_by`` and hence the ``To
    disable:`` footer the router appends afterwards. Every other deny follows
    as a bounded excerpt naming its handler; beyond the bound the handlers
    are still NAMED, so no violation is silent. Advisories become one table
    (their full text still travels as ``additionalContext``).

    Args:
        lead_reason: The lead deny's own reason (may be None).
        denials: ``(handler_name, result)`` for every restrictive result.
        advisories: ``(handler_name, result)`` for every advisory result
            that carried context.

    Returns:
        The merged reason text.
    """
    sections: list[str] = [lead_reason or ""]

    extra = denials[1:]
    for name, result in extra[:COLLECT_ALL_MAX_EXTRA_DENIES]:
        sections.append(
            _COLLECT_ALL_DENY_HEADER.format(handler=name)
            + "\n"
            + _excerpt(result.reason or "", COLLECT_ALL_DENY_EXCERPT_CHARS)
        )
    overflow = extra[COLLECT_ALL_MAX_EXTRA_DENIES:]
    if overflow:
        names = ", ".join(name for name, _ in overflow)
        sections.append(f"({len(overflow)} more denies not shown in full: {names})")

    if advisories:
        rows = ["| Handler | Advisory |", "| --- | --- |"]
        for name, result in advisories[:COLLECT_ALL_MAX_ADVISORY_ROWS]:
            rows.append(f"| {name} | {_advisory_cell(result)} |")
        table = _COLLECT_ALL_ADVISORY_HEADER + "\n\n" + "\n".join(rows)
        hidden = advisories[COLLECT_ALL_MAX_ADVISORY_ROWS:]
        if hidden:
            names = ", ".join(name for name, _ in hidden)
            table += f"\n({len(hidden)} more advisories: {names})"
        sections.append(table)

    return "\n\n".join(section for section in sections if section)


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
    - A restrictive decision from a terminal handler ending the chain
    - Every result's context accumulated into the merged response
    - Error handling with fail-open semantics

    Attributes:
        allow_is_final: Event-level opt-in (Plan 00242). When True, a
            terminal handler's ALLOW concludes the chain — the PermissionRequest
            semantic, where an approval IS the answer. False everywhere else:
            an ALLOW never ends the chain.
    """

    __slots__ = ("_handlers", "_sorted", "allow_is_final")

    def __init__(self, *, allow_is_final: bool = False) -> None:
        """Initialise empty handler chain.

        Args:
            allow_is_final: Let a terminal ALLOW end the chain (see class
                docstring). Keyword-only so the opt-in is always spelled out.
        """
        self._handlers: list[Handler] = []
        self._sorted = True
        self.allow_is_final = allow_is_final

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
        self,
        hook_input: dict[str, Any],
        strict_mode: bool = False,
        *,
        collect_all: bool = False,
    ) -> ChainExecutionResult:
        """Execute the handler chain for an event.

        Handlers are executed in priority order. Every matched handler's
        context is accumulated. A restrictive decision (deny/ask/defer) from a
        terminal handler ends the chain; an ALLOW never does (unless this
        chain was built with ``allow_is_final=True``).

        Args:
            hook_input: Hook input dictionary to process
            strict_mode: If True, FAIL FAST on handler exceptions (fail-closed).
                        If False, log and continue (fail-open).
            collect_all: ``daemon.chain.collect_all_violations`` (Plan 00242
                Phase 3). When True a deny no longer ends the chain either:
                every matching handler runs and the response is ONE merged
                report — the first deny leads, the other denies follow as
                bounded excerpts, the advisories are summarised in a table.

        Returns:
            ChainExecutionResult with final result and metadata
        """
        start_time = time.perf_counter()
        accumulated_context: list[str] = []
        handlers_executed: list[str] = []
        handlers_matched: list[str] = []
        executed_handlers: list[Handler] = []
        final_result: HookResult | None = None
        terminated_by: str | None = None
        decided_by: str | None = None
        decisions: list[HandlerVerdict] = []
        # Every matched handler's result, in chain order, so the ALLOW-only
        # information fields can be merged onto the winner afterwards.
        matched_results: list[HookResult] = []
        # Collect-all bookkeeping: every restrictive result and every
        # advisory (non-restrictive result that carried context), in order.
        denials: list[tuple[str, HookResult]] = []
        advisories: list[tuple[str, HookResult]] = []

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
                    executed_handlers.append(handler)
                    matched_results.append(result)
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

                    restrictive = is_restrictive(result.decision)

                    # First restrictive decision wins: it owns the reason shown
                    # AND the "To disable:" attribution, so the two can never
                    # disagree (Plan 00190 Task 0.5, made deliberate by Plan
                    # 00242 Task 3.3). A later, laxer result never overwrites
                    # it (Plan 00144 regression: plan_qa_edit's deny at priority
                    # 44 was lost when markdown_organization's ALLOW landed at
                    # priority 50).
                    if decided_by is None and restrictive:
                        decided_by = handler.name
                    accumulated_context.extend(result.context)
                    if final_result is None or (
                        restrictive and not is_restrictive(final_result.decision)
                    ):
                        final_result = result
                    if restrictive:
                        denials.append((handler.name, result))
                    elif result.context:
                        advisories.append((handler.name, result))

                    # Terminality belongs to the DECISION (Plan 00242): a
                    # restrictive result from a terminal handler ends the chain
                    # (unless collect-all mode wants every violation); an ALLOW
                    # continues unless this event opted in to "approve and
                    # stop" (allow_is_final).
                    ends_on_restrictive = restrictive and not collect_all
                    ends_on_allow = self.allow_is_final and not restrictive
                    if handler.terminal and (ends_on_restrictive or ends_on_allow):
                        terminated_by = handler.name
                        break

            except Exception as e:
                logger.exception("Handler %s raised exception", handler.name)
                handlers_executed.append(handler.name)

                if strict_mode:
                    # STRICT MODE: FAIL FAST - handler crash = BLOCK operation (fail-closed)
                    error_result = HookResult.deny(
                        reason=f"SYSTEM ERROR: Handler {handler.name} crashed - blocking for safety",
                    )
                    accumulated_context.append(f"Handler exception: {type(e).__name__}: {e}")
                    error_result.add_handler(handler.name)

                    # Stop chain immediately - a crash in strict mode is final
                    error_result.context = list(accumulated_context)
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

        if collect_all and is_restrictive(final_result.decision) and denials:
            final_result.reason = merge_violations(final_result.reason, denials, advisories)

        # The merged response carries EVERY matched handler's context, in
        # chain order — the winning result's own lines are already among them.
        if final_result.context != accumulated_context:
            final_result.context = list(accumulated_context)

        # ...and, on the same principle, every matched handler's guidance,
        # input rewrite and worktree path. The decision stays
        # most-restrictive-wins; these fields are information, so the winner
        # only owns the ones it set itself.
        carry_accumulated_fields(final_result, matched_results)

        # Record all matched handlers
        for h in handlers_matched:
            final_result.add_handler(h)

        # Post-decision commit (Plan 00242 Phase 2): every handler that ran
        # hears the merged decision, so a rate limiter can roll back a
        # cooldown it spent on a call that ended up denied. The decision is
        # final by now — a crash here is surfaced, never allowed to change it.
        for handler in executed_handlers:
            try:
                handler.commit_side_effects(hook_input, final_result.decision)
            except Exception as e:
                logger.exception("Handler %s crashed in commit_side_effects", handler.name)
                final_result.context.append(
                    f"Handler side-effect commit exception in {handler.name}: "
                    f"{type(e).__name__}: {e}"
                )

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
