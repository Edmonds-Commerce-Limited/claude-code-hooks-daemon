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
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from claude_code_hooks_daemon.constants import HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core.bounded_dispatch import (
    BoundedDispatcher,
    DispatchSaturated,
    DispatchTimeout,
    get_default_dispatcher,
)
from claude_code_hooks_daemon.core.handler_scope import scope_admits
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


# The bulk-text ``tool_input`` fields a SAFETY handler actually scans (Plan
# 00466 N34 remedy 3). Deliberately NOT the whole payload -- an unrelated
# large field (e.g. a long transcript_path) must never count against the
# size cap, only the text a handler's own matches()/handle() would work over.
_SIZED_TOOL_INPUT_FIELDS: tuple[str, ...] = ("command", "content", "new_string", "old_string")


def _safety_payload_size(hook_input: dict[str, Any]) -> int:
    """Best-effort byte size of the text a SAFETY handler would scan.

    0 for a ``tool_input`` carrying none of :data:`_SIZED_TOOL_INPUT_FIELDS`
    -- there is no known bulk text for the size cap to bound.
    """
    tool_input = hook_input.get(HookInputField.TOOL_INPUT)
    if not isinstance(tool_input, dict):
        return 0
    total = 0
    for field_name in _SIZED_TOOL_INPUT_FIELDS:
        value = tool_input.get(field_name)
        if isinstance(value, str):
            total += len(value.encode("utf-8"))
    return total


def _dispatch_matches_and_handle(
    handler: "Handler",
    hook_input: dict[str, Any],
    on_matched: Callable[[], None],
) -> "HookResult | None":
    """One handler's own decision, run on whichever thread calls this.

    The single callable :meth:`BoundedDispatcher.run` dispatches (Plan 00466
    N34): ``matches()`` and ``handle()`` combined, so the caller's ONE
    ``Future.result(timeout=...)`` wait bounds both -- a handler slow inside
    either call is bounded the same way. ``on_matched`` fires the instant
    ``matches()`` returns True, before ``handle()`` runs, mirroring the
    direct synchronous call's own ordering: a handler that matched is
    recorded even when ``handle()`` itself goes on to raise.
    """
    if not handler.matches(hook_input):
        return None
    on_matched()
    return handler.handle(hook_input)


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

    __slots__ = ("_handlers", "_sorted", "allow_is_final", "context_transform")

    def __init__(
        self,
        *,
        allow_is_final: bool = False,
        context_transform: "Callable[[Handler, list[str]], list[str]] | None" = None,
    ) -> None:
        """Initialise empty handler chain.

        Args:
            allow_is_final: Let a terminal ALLOW end the chain (see class
                docstring). Keyword-only so the opt-in is always spelled out.
            context_transform: Optional per-handler post-processing applied to
                a matched handler's OWN context lines, right after
                ``handle()`` returns and before they are flattened into the
                merged response — the only point in dispatch where a context
                line is still paired with the handler that produced it. Never
                called for a handler whose context is empty. ``HandlerChain``
                stays event-agnostic: it knows nothing about what the
                transform does (Plan 00416's SessionStart tier tagging is one
                caller; the router wires that in, not this class).
        """
        self._handlers: list[Handler] = []
        self._sorted = True
        self.allow_is_final = allow_is_final
        self.context_transform = context_transform

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
        deadline_seconds: float | None = None,
        max_safety_input_bytes: int | None = None,
        dispatcher: "BoundedDispatcher[object] | None" = None,
    ) -> ChainExecutionResult:
        """Execute the handler chain for an event.

        Handlers are executed in priority order. Every matched handler's
        context is accumulated. A restrictive decision (deny/ask/defer) from a
        terminal handler ends the chain; an ALLOW never does (unless this
        chain was built with ``allow_is_final=True``).

        A handler tagged both ``HandlerTag.SAFETY`` and ``HandlerTag.BLOCKING``
        that raises always denies, whatever ``strict_mode`` says (Plan 00466
        N24): a safety guard that crashed has not judged the call, so
        treating that as "no match" would be a bypass. A non-safety or
        advisory handler that raises keeps the ``strict_mode`` behaviour
        below unchanged.

        ``deadline_seconds`` (Plan 00466 N25) closes a related gap: the
        CLIENT's own socket timeout (30s, well above any daemon-side budget
        here) fails the WHOLE chain open on expiry, so a merely slow handler
        bypassed every guard behind it, not just itself. Checked once per
        handler, before it runs: once exceeded, a SAFETY+BLOCKING handler not
        yet run is treated exactly like N24's raise -- DENY, naming the
        handler, "not judged in time" -- and a non-SAFETY+BLOCKING handler is
        skipped with a context note instead of denied. Deliberately NOT
        `collect_all`-aware: collect_all assumes there is budget left to keep
        evaluating, which is precisely what has run out here.

        Args:
            hook_input: Hook input dictionary to process
            strict_mode: If True, FAIL FAST on handler exceptions (fail-closed).
                        If False, log and continue (fail-open) — except for a
                        SAFETY+BLOCKING handler, which always fails closed.
            collect_all: ``daemon.chain.collect_all_violations`` (Plan 00242
                Phase 3). When True a deny no longer ends the chain either:
                every matching handler runs and the response is ONE merged
                report — the first deny leads, the other denies follow as
                bounded excerpts, the advisories are summarised in a table.
            deadline_seconds: ``daemon.chain.deadline_seconds`` (Plan 00466
                N25). None (the default for every existing caller that does
                not pass it) leaves the chain unbounded, matching the
                pre-existing behaviour. When set, EVERY handler's own
                ``matches()``/``handle()`` call is also individually bounded
                (Plan 00466 N34) -- see :mod:`core.bounded_dispatch` -- not
                only the gap between handlers.
            max_safety_input_bytes: ``daemon.chain.max_safety_input_bytes``
                (Plan 00466 N34 remedy 3). A SAFETY handler whose bulk-text
                input exceeds this is denied (SAFETY+BLOCKING) or skipped
                (otherwise) BEFORE dispatch is even attempted. None (the
                default) disables this check; ``deadline_seconds`` still
                applies regardless.
            dispatcher: The :class:`BoundedDispatcher` to run handlers on
                when ``deadline_seconds`` is set. None (the default for
                every real caller) uses the shared, process-lifetime pool.
                Tests that need to control or observe pool capacity directly
                (e.g. saturation) inject their own instance instead.

        Returns:
            ChainExecutionResult with final result and metadata
        """
        # Resolved once per call, not per handler: the shared, process-lifetime
        # pool by default (Plan 00466 N34), or an injected one for tests that
        # need to control/observe its capacity directly (e.g. saturation).
        active_dispatcher = dispatcher if dispatcher is not None else get_default_dispatcher()
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

        def _record_unjudged(handler: "Handler", reason: str, note: str) -> bool:
            """Record a "could not be judged" verdict for ``handler``.

            Shared core for every reason a handler might not get a real
            verdict (Plan 00466 N24/N25/N34): a deadline already gone before
            it was even considered, its own dispatch timing out, the
            dispatch pool being saturated, or its input exceeding the SAFETY
            size cap. A handler tagged both SAFETY and BLOCKING is denied
            with ``reason`` -- exactly like N24's raise, because "no
            verdict" must never read as "allowed". Anything else is skipped
            with ``note`` as a context line; the client's own (much larger)
            timeout is still the true backstop for those.

            Returns:
                True when the chain must stop (a terminal deny was recorded).
            """
            nonlocal final_result, terminated_by, decided_by
            is_safety_blocking = (
                HandlerTag.SAFETY in handler.tags and HandlerTag.BLOCKING in handler.tags
            )
            if is_safety_blocking:
                unjudged_result = HookResult.deny(reason=reason)
                accumulated_context.append(note)
                unjudged_result.add_handler(handler.name)
                unjudged_result.context = list(accumulated_context)
                decisions.append(
                    HandlerVerdict(
                        handler=handler.name,
                        decision=unjudged_result.decision,
                        terminal=handler.terminal,
                    )
                )
                handlers_executed.append(handler.name)
                final_result = unjudged_result
                terminated_by = handler.name
                if decided_by is None:
                    decided_by = handler.name
                return True
            accumulated_context.append(note)
            return False

        def _apply_deadline_exceeded(handler: "Handler", detail: str) -> bool:
            """``_record_unjudged`` for a timing reason (deadline/dispatch)."""
            return _record_unjudged(
                handler,
                reason=f"{handler.name}: not judged in time ({detail})",
                note=(
                    f"Handler {handler.name} not judged in time: {detail}"
                    if (HandlerTag.SAFETY in handler.tags and HandlerTag.BLOCKING in handler.tags)
                    else f"Handler {handler.name} skipped: {detail}"
                ),
            )

        def _apply_oversized_input(handler: "Handler", payload_size: int, limit: int) -> bool:
            """``_record_unjudged`` for the SAFETY input-size cap (Plan 00466
            N34 remedy 3): defence in depth alongside the deadline -- a huge
            payload can exhaust a handler's OWN budget regardless of how fast
            its per-byte cost is, so this is checked BEFORE any dispatch is
            even attempted, not after a timeout.
            """
            detail = f"{payload_size} bytes exceeds the {limit}-byte SAFETY evaluation limit"
            return _record_unjudged(
                handler,
                reason=f"{handler.name}: input too large to evaluate safely ({detail})",
                note=(
                    f"Handler {handler.name} input too large to evaluate safely: {detail}"
                    if (HandlerTag.SAFETY in handler.tags and HandlerTag.BLOCKING in handler.tags)
                    else f"Handler {handler.name} skipped: input too large to evaluate safely ({detail})"
                ),
            )

        def _record_matched_result(handler: "Handler", result: HookResult) -> bool:
            """Post-``handle()`` bookkeeping shared by the direct-call and
            bounded-dispatch paths below. Returns True when the chain must
            stop (a terminal handler produced a decision that ends it).
            """
            nonlocal final_result, decided_by
            logger.debug(
                "Handler %s returned decision=%s, terminal=%s",
                handler.name,
                result.decision,
                handler.terminal,
            )
            if self.context_transform is not None and result.context:
                result.context = self.context_transform(handler, result.context)
            handlers_executed.append(handler.name)
            executed_handlers.append(handler)
            matched_results.append(result)
            result.add_handler(handler.name)

            # Record THIS handler's own verdict now, before any later
            # handler's laxer/stricter result can change what the eventual
            # merged chain decision looks like (Plan 00209).
            decisions.append(
                HandlerVerdict(
                    handler=handler.name,
                    decision=result.decision,
                    terminal=handler.terminal,
                    rule=result.rule,
                )
            )

            restrictive = is_restrictive(result.decision)

            # First restrictive decision wins: it owns the reason shown AND
            # the "To disable:" attribution, so the two can never disagree
            # (Plan 00190 Task 0.5, made deliberate by Plan 00242 Task 3.3).
            # A later, laxer result never overwrites it (Plan 00144
            # regression: plan_qa_edit's deny at priority 44 was lost when
            # markdown_organization's ALLOW landed at priority 50).
            if decided_by is None and restrictive:
                decided_by = handler.name
            accumulated_context.extend(result.context)
            if final_result is None or (restrictive and not is_restrictive(final_result.decision)):
                final_result = result
            if restrictive:
                denials.append((handler.name, result))
            elif result.context:
                advisories.append((handler.name, result))

            # Terminality belongs to the DECISION (Plan 00242): a restrictive
            # result from a terminal handler ends the chain (unless
            # collect-all mode wants every violation); an ALLOW continues
            # unless this event opted in to "approve and stop"
            # (allow_is_final).
            ends_on_restrictive = restrictive and not collect_all
            ends_on_allow = self.allow_is_final and not restrictive
            return bool(handler.terminal and (ends_on_restrictive or ends_on_allow))

        def _make_dispatch_call(handler: "Handler") -> Callable[[], "HookResult | None"]:
            """A zero-argument closure over THIS ``handler`` for
            :meth:`BoundedDispatcher.run` (Plan 00466 N34).

            A named factory taking ``handler`` as a real parameter, not a
            ``lambda h=handler: ...`` default-argument trick, is deliberate:
            the latter both defeats type inference on the generic dispatcher
            call and is easy to get subtly wrong for the classic
            loop-variable-closure reason (a default argument binds it, but a
            typo dropping the default silently reintroduces the bug).
            """

            def _call() -> "HookResult | None":
                return _dispatch_matches_and_handle(
                    handler, hook_input, lambda: handlers_matched.append(handler.name)
                )

            return _call

        # Computed once per call, not per handler (Plan 00466 N34 remedy 3):
        # a cheap O(field count) measurement, not a scan of the whole payload.
        payload_size = _safety_payload_size(hook_input) if max_safety_input_bytes is not None else 0

        for handler in self.handlers:
            if (
                deadline_seconds is not None
                and (time.perf_counter() - start_time) >= deadline_seconds
            ):
                # Out of budget before this handler even ran (Plan 00466 N25).
                if _apply_deadline_exceeded(
                    handler, f"chain deadline ({deadline_seconds}s) exceeded"
                ):
                    break
                continue

            if (
                max_safety_input_bytes is not None
                and payload_size > max_safety_input_bytes
                and HandlerTag.SAFETY in handler.tags
            ):
                # Defence in depth (Plan 00466 N34 remedy 3): fail before
                # dispatch is even attempted, not after paying its overhead.
                if _apply_oversized_input(handler, payload_size, max_safety_input_bytes):
                    break
                continue

            try:
                # Scope gate (Plan 00423), BEFORE matches(). A handler the
                # scope refuses is skipped entirely — not matched, not
                # executed, no context, no verdict — because a handler that ran
                # and allowed is not the same as one that never ran: the chain
                # aggregates the former under most-restrictive-wins and the
                # verdict log records it.
                #
                # Here rather than in each handler's matches(): that would be
                # 142 chances to forget one, and a handler that forgets is a
                # handler still nudging subagents, which is the defect this
                # exists to close. It is also the right seam — matches() is the
                # handler's question about the PAYLOAD; whether to consult the
                # handler at all is the registry's question about POLICY.
                if not scope_admits(handler.scope, hook_input):
                    logger.debug(
                        "Handler %s skipped - scope %s excludes this event",
                        handler.name,
                        handler.scope,
                    )
                    continue

                if deadline_seconds is None:
                    # No deadline configured: the original, fully synchronous
                    # call -- unchanged, and zero bounded-dispatch overhead on
                    # what is still every unit test's and every un-configured
                    # install's own path.
                    if handler.matches(hook_input):
                        handlers_matched.append(handler.name)
                        logger.debug("Handler %s matched event", handler.name)
                        result = handler.handle(hook_input)
                        if _record_matched_result(handler, result):
                            terminated_by = handler.name
                            break
                    continue

                # Plan 00466 N34: a chain deadline that only ever checks
                # BETWEEN handlers cannot catch one slow WITHIN its own
                # matches()/handle() -- exactly secret_file_guard's shape on
                # multi-MB input (48.958s measured on 4 MB, past both this
                # deadline and the client's own 30s socket timeout). Below,
                # the handler's own call is bounded too: it runs on the
                # shared pool and this thread waits on it for at most the
                # REMAINING budget, not the handler's own sleep/scan time.
                remaining = max(0.0, deadline_seconds - (time.perf_counter() - start_time))
                outcome = active_dispatcher.run(
                    _make_dispatch_call(handler),
                    timeout=remaining,
                    label=handler.name,
                )
                if isinstance(outcome, DispatchTimeout):
                    if _apply_deadline_exceeded(
                        handler, f"exceeded its {remaining:.2f}s dispatch budget"
                    ):
                        break
                    continue
                if isinstance(outcome, DispatchSaturated):
                    if _apply_deadline_exceeded(handler, "dispatch pool saturated"):
                        break
                    continue
                if outcome is None:
                    # matches() returned False -- nothing to record, exactly
                    # like the direct-call path above.
                    continue
                # The only remaining possibility: `_make_dispatch_call`'s own
                # closure returns `HookResult | None`, and None was just
                # ruled out above -- this narrows `object` (BoundedDispatcher
                # is generic over its DECLARED type, not this call's actual
                # return type) back to what it always really was.
                assert isinstance(outcome, HookResult)
                if _record_matched_result(handler, outcome):
                    terminated_by = handler.name
                    break

            except Exception as e:
                logger.exception("Handler %s raised exception", handler.name)
                handlers_executed.append(handler.name)

                # A SAFETY+BLOCKING handler that raises has not judged the
                # call at all -- "no match" would be a silent bypass of
                # exactly the guard meant to catch this call (Plan 00466
                # N24 M3/m1). This applies whatever `strict_mode` says,
                # because `strict_mode` is inert in every real install
                # today (N24) and every other SAFETY guard has no per-guard
                # fail-closed wrapper of its own. It also covers a raise
                # from `matches()`, not only `handle()` (m1/m2): both sit
                # inside this same try block.
                is_safety_blocking = (
                    HandlerTag.SAFETY in handler.tags and HandlerTag.BLOCKING in handler.tags
                )

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
                elif is_safety_blocking:
                    # Independent of strict_mode: deny with a reason naming
                    # the handler and the underlying error, rather than the
                    # strict-mode "SYSTEM ERROR" wording, so the two paths
                    # stay distinguishable in a verdict log.
                    error_result = HookResult.deny(
                        reason=(
                            f"{handler.name}: evaluation error, denied for safety "
                            f"({type(e).__name__}: {e})"
                        ),
                    )
                    accumulated_context.append(f"Handler exception: {type(e).__name__}: {e}")
                    error_result.add_handler(handler.name)
                    error_result.context = list(accumulated_context)
                    final_result = error_result
                    terminated_by = handler.name
                    if decided_by is None:
                        decided_by = handler.name
                    break
                else:
                    # NON-STRICT MODE, non-safety handler: fail-open - log
                    # error and continue chain
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
