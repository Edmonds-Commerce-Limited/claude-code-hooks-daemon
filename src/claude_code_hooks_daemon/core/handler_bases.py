"""Per-event handler bases that carry their event's decision constraint.

``core.result_types`` provides result types that cannot HOLD an undeliverable
decision. On its own that protects nothing, because a handler still has to
choose to use one. A generic ``Handler[ResultT]`` has the same flaw: the
parameter must be declared per handler, so one that FORGOT to declare it
silently loses protection — the exact failure mode this exists to remove.

A base is inherited instead. Subclass ``SessionStartHandlerBase`` and mypy
already rejects both halves of the mistake, with nothing declared:

    class MyHandler(SessionStartHandlerBase):
        def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
            return AdvisoryResult(decision=Decision.DENY)   # error: [arg-type]

    class Sneaky(SessionStartHandlerBase):
        def handle(self, hook_input: dict[str, Any]) -> HookResult:   # error: [override]
            ...

**Why the per-event names are aliases.** mypy enforces a narrowed return type
identically through an alias, so an event costs one line rather than a class
body. The aliases add no type-level strictness over the three tier classes —
they exist so a handler author never has to know which tier their event is in,
which is exactly the knowledge this module removes the need for. Package-to-tier
correctness is enforced by the test sweep, not by the naming.

**Why the ``HandlerBase`` suffix.** ``WorktreeCreateHandler`` and
``WorktreeRemoveHandler`` are already concrete handler class names; the
unsuffixed form would read as though it were one of them.

The bases re-declare ``handle`` as abstract so a subclass that omits it still
fails to instantiate — narrowing a signature must not quietly supply a stub.
"""

from abc import abstractmethod
from typing import Any

from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.result_types import (
    AdvisoryResult,
    BlockingResult,
    GatingResult,
    result_type_for_event,
)
from claude_code_hooks_daemon.core.segment_explanation import SegmentExplanation


class AdvisoryHandler(Handler):
    """For an event that can neither deny nor ask — it can only add context.

    ``SessionStart``, ``SessionEnd``, ``Notification``, both worktree events,
    ``Status`` and the other events with no documented decision control. Their
    responses have no way to carry a refusal, so a DENY here is dropped on the
    wire.
    """

    @abstractmethod
    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Handle the event, advisory only.

        Args:
            hook_input: The hook event payload.

        Returns:
            An advisory result. This event cannot refuse anything.
        """


class BlockingHandler(Handler):
    """For an event that can block but has no ``ask``.

    ``PostToolUse``, ``Stop`` and ``SubagentStop`` carry a refusal as a
    top-level ``decision: "block"``. There is no wire representation for ASK.
    """

    @abstractmethod
    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Handle the event, allowing or blocking.

        Args:
            hook_input: The hook event payload.

        Returns:
            A blocking-tier result. This event cannot ASK.
        """


class GatingHandler(Handler):
    """For an event that gates an action and can deny or ask.

    ``PreToolUse`` (``permissionDecision``) and ``PermissionRequest``
    (``decision.behavior``) are the only two.
    """

    @abstractmethod
    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Handle the event, allowing, denying or asking.

        Args:
            hook_input: The hook event payload.

        Returns:
            A gating-tier result.
        """


# --------------------------------------------------------------------------
# Per-event names. One line each; every wired event must appear, so a handler
# for any of them has a base to inherit from. The test sweep asserts both that
# the list is complete and that each entry matches its event's capability.
# --------------------------------------------------------------------------

# Gating: can deny AND ask.
PreToolUseHandlerBase = GatingHandler

# Blocking: can deny, cannot ask. PermissionRequest sits here because its
# documented decision.behavior enum is allow | deny only (Plan 00271 item 3).
PermissionRequestHandlerBase = BlockingHandler
PostToolUseHandlerBase = BlockingHandler
# UserPromptSubmit: documented top-level decision "block" (Plan 00271 item 5).
UserPromptSubmitHandlerBase = BlockingHandler
# Wired-extra events with documented blocking (Plan 00271 item 9): top-level
# decision "block" for the first five, continue: false for the last two.
UserPromptExpansionHandlerBase = BlockingHandler
PostToolUseFailureHandlerBase = BlockingHandler
PostToolBatchHandlerBase = BlockingHandler
TaskCreatedHandlerBase = BlockingHandler
ConfigChangeHandlerBase = BlockingHandler
TeammateIdleHandlerBase = BlockingHandler
TaskCompletedHandlerBase = BlockingHandler
# PreCompact: a hook can block compaction (Plan 00271 item 7).
PreCompactHandlerBase = BlockingHandler
StopHandlerBase = BlockingHandler
SubagentStopHandlerBase = BlockingHandler

class StatusLineSegmentHandler(AdvisoryHandler):
    """Status-line handler contract: an advisory decision plus a self-description.

    Every concrete status-line handler must be able to explain its own
    segment -- icon(s), what it is, how to read it, and what it currently
    shows -- so ``status-line-explained`` (Plan 00369) can render
    documentation for every segment without a per-handler special case. A
    handler that forgets this method fails to INSTANTIATE (abstract), the
    same protection the tier bases give ``handle()`` -- see the module
    docstring.
    """

    @abstractmethod
    def explain_segment(self) -> SegmentExplanation:
        """Describe this segment for a human, and report its current value.

        Must be read-only: no writes, no mutation of on-disk or in-memory
        state (unlike ``handle()``, which some status-line handlers use to
        record sensor state). Called from a one-shot CLI process, never from
        the render hot path.

        Returns:
            A :class:`SegmentExplanation` describing this segment right now.
        """


# Advisory: can neither deny nor ask.
SessionStartHandlerBase = AdvisoryHandler
SessionEndHandlerBase = AdvisoryHandler
PostCompactHandlerBase = AdvisoryHandler
NotificationHandlerBase = AdvisoryHandler
StatusLineHandlerBase = StatusLineSegmentHandler
WorktreeCreateHandlerBase = AdvisoryHandler
WorktreeRemoveHandlerBase = AdvisoryHandler
SetupHandlerBase = AdvisoryHandler
PermissionDeniedHandlerBase = AdvisoryHandler
MessageDisplayHandlerBase = AdvisoryHandler
SubagentStartHandlerBase = AdvisoryHandler
StopFailureHandlerBase = AdvisoryHandler
InstructionsLoadedHandlerBase = AdvisoryHandler
CwdChangedHandlerBase = AdvisoryHandler
DirectoryAddedHandlerBase = AdvisoryHandler
FileChangedHandlerBase = AdvisoryHandler
ElicitationHandlerBase = AdvisoryHandler
ElicitationResultHandlerBase = AdvisoryHandler


def handler_base_for_event(event_name: str) -> type[Handler]:
    """The handler base a handler for this event should subclass.

    Keyed off ``result_type_for_event`` rather than a second event table, so
    the base and the result tier cannot disagree about an event. A test asserts
    the two agree for every wired event.

    The three arms are written as direct returns rather than a lookup table
    because mypy's ``[type-abstract]`` rejects an ABSTRACT class placed into a
    ``type[Handler]`` container, while returning one is fine. These bases must
    stay abstract — see the class docstrings — so the table is not available.

    Args:
        event_name: The wire event name.

    Returns:
        The tier base class. The per-event aliases above are the same objects,
        so ``handler_base_for_event("SessionStart") is SessionStartHandlerBase``.

    Raises:
        ValueError: If the event is unknown (propagated from
            ``result_type_for_event`` — never guess a tier, because a wrong
            guess either forbids a legal decision or permits a silent drop), or
            if a result tier exists with no base to go with it.
    """
    result_type = result_type_for_event(event_name)
    if result_type is GatingResult:
        return GatingHandler
    if result_type is BlockingResult:
        return BlockingHandler
    if result_type is AdvisoryResult:
        return AdvisoryHandler

    raise ValueError(
        f"No handler base returns {result_type.__name__} for event "
        f"{event_name!r}. Add the missing base rather than widening one."
    )
