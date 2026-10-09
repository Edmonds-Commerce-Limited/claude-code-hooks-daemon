"""PlanFactCheckFeedHandler - feeds plan edits to the debouncer (Plan 00480 Task 4.1).

A burst of edits to one plan should trigger ONE fact check, not one per edit.
This PostToolUse handler watches writes to a plan's tracked documents (a
``Write``/``Edit``, or a Bash command whose written paths
``get_written_file_paths`` can name) and triggers the daemon-wide keyed
debouncer, keyed by plan folder. When the plan has been quiet for
``quiet_seconds`` (default 5), :func:`_on_quiet` runs.

**Delivery (Plan 00480 open question 1, option a).** The daemon runs no model.
:func:`_on_quiet` runs on the debouncer's timer thread, where there is no hook
to speak through, so it dispatches NOTHING: it logs at info level and stores the
diff since the plan's last fact-checked content as a *pending fact-check*
record, via
:func:`~claude_code_hooks_daemon.utils.plan_fact_check.process_quiet_plan`.
The next PostToolUse event of the MAIN thread, whatever the tool, delivers it as
``additionalContext`` telling the session to dispatch the ``plan-fact-checker``
agent with the diff, and to treat REFUTED claims as work to fix. A subagent's
event (one carrying ``agent_id``) feeds the debouncer but never takes the record.
Each record is handed over once per offer (claimed by an atomic rename, so two
events at once cannot both deliver it). The daemon cannot see whether the text
arrived, so the content counts as checked only when the session is then seen
dispatching ``plan-fact-checker`` with the diff path in its prompt; an offer
nobody acts on is re-offered after a wait, a few times.

A plan's first sighting records a baseline and owes nothing; a small edit soon
after a confirmed check is taken for a correction and absorbed; and edits under
a worktree nested in the project root are ignored (they reach this tree by a
merge, not as edits).

The supervisor turn channel (``session_actions_directive``) is deliberately not
used: its signal carries a bare count and its text is a fixed template that
points at ``hooks-daemon session-actions``, which lists SessionStart items only,
so a signal for a fact-check would send the agent to a list that omits it.

Ships default-DISABLED. Never blocks (owner ruling A1).
"""

import logging
import time
from functools import partial
from pathlib import Path
from typing import Any, ClassVar, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.debouncer import DebounceFire, get_debouncer
from claude_code_hooks_daemon.core.handler import WorkspaceScope
from claude_code_hooks_daemon.core.handler_bases import PostToolUseHandlerBase
from claude_code_hooks_daemon.core.handler_scope import in_subagent
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.utils import get_written_file_paths
from claude_code_hooks_daemon.core.worktree_paths import enclosing_checkout
from claude_code_hooks_daemon.utils.plan_fact_check import (
    FACT_CHECKER_AGENT,
    STATE_SUBDIR,
    PlanFactCheckState,
    PlanFolderMatch,
    confirm_dispatch,
    deliver_pending,
    plan_folder_match,
    process_quiet_plan,
)
from claude_code_hooks_daemon.utils.plan_trigger import plan_dir_for

logger = logging.getLogger(__name__)

DEFAULT_QUIET_SECONDS: Final[float] = 5.0
#: Tools that dispatch a sub-agent (the tool's name differs between Claude Code versions).
DISPATCH_TOOLS: Final[frozenset[str]] = frozenset({"Task", "Agent"})


def _on_quiet(fire: DebounceFire, *, plan_root: Path, state_dir: Path) -> None:
    """Debounce callback: record the pending fact-check. Dispatches nothing."""
    process_quiet_plan(
        plan_root,
        str(fire.payload),
        PlanFactCheckState(state_dir),
        trigger_count=fire.trigger_count,
        now=time.time(),
    )


def _in_main_checkout(path: str, project_root: Path) -> bool:
    """True when ``path`` is in the project's own checkout, not a worktree nested under it."""
    located = enclosing_checkout(path, project_root)
    return located is not None and located[0] == project_root


def _checker_dispatch_prompt(hook_input: dict[str, Any]) -> str | None:
    """The prompt of a dispatch of the fact-checker agent, or ``None`` for any other event."""
    if hook_input.get("tool_name") not in DISPATCH_TOOLS:
        return None
    tool_input = hook_input.get("tool_input")
    if not isinstance(tool_input, dict) or tool_input.get("subagent_type") != FACT_CHECKER_AGENT:
        return None
    return str(tool_input.get("prompt", ""))


class PlanFactCheckFeedHandler(PostToolUseHandlerBase):
    """Feed plan edits to the debouncer so a burst yields one pending fact-check."""

    # REPO-scoped: the plan tree is repository-singular.
    workspace_scope: ClassVar[WorkspaceScope] = WorkspaceScope.REPO

    # Opt-in: it asks the session to spend an agent run per quiet plan edit.
    default_enabled = False

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.PLAN_FACT_CHECK_FEED,
            priority=Priority.PLAN_FACT_CHECK_FEED,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )
        # Option, injected by the registry via setattr; typed and defaulted here.
        self._quiet_seconds: float = DEFAULT_QUIET_SECONDS

    def _plan_matches(self, hook_input: dict[str, Any]) -> list[PlanFolderMatch]:
        """One match per distinct plan folder the event wrote a tracked document in.

        A write inside a worktree nested under the project root (a sub-agent's
        own checkout) is not this session's plan: it reaches the main tree only
        by a merge, so it must not feed the debouncer under the worktree path.
        """
        plan_dir = plan_dir_for(self._project_layout)
        project_root = ProjectContext.project_root().resolve()
        found: dict[str, PlanFolderMatch] = {}
        for path in get_written_file_paths(hook_input):
            match = plan_folder_match(path, plan_dir)
            if match is not None and _in_main_checkout(path, project_root):
                found[str(match.plan_root)] = match
        return list(found.values())

    @staticmethod
    def _state() -> PlanFactCheckState:
        return PlanFactCheckState(ProjectContext.daemon_untracked_dir() / STATE_SUBDIR)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True when the event wrote a plan document, or a fact-check is owed.

        An owed check is delivered on ANY next event of the main thread: the
        debounce fire runs on a timer thread with no hook to speak through, so
        the next event is the earliest the session can be told. A subagent's
        event is never that: a worker told to dispatch the fact-checker would
        consume the record, and the session that owns the plan would never hear.
        """
        if self._plan_matches(hook_input):
            return True
        if in_subagent(hook_input):
            return False
        state = self._state()
        return bool(state.pending_folders() or state.offered_folders())

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Feed the debouncer, confirm a dispatch, and deliver what is owed. Always ALLOW."""
        state = self._state()
        debouncer = get_debouncer()
        for match in self._plan_matches(hook_input):
            debouncer.trigger(
                str(match.plan_root),
                quiet_seconds=float(self._quiet_seconds),
                callback=partial(_on_quiet, plan_root=match.plan_root, state_dir=state.state_dir),
                payload=match.folder,
            )
        if in_subagent(hook_input):
            return BlockingResult(decision=Decision.ALLOW)
        prompt = _checker_dispatch_prompt(hook_input)
        if prompt is not None:
            confirm_dispatch(state, prompt, now=time.time())
        instructions = deliver_pending(state)
        if not instructions:
            return BlockingResult(decision=Decision.ALLOW)
        return BlockingResult(decision=Decision.ALLOW, context=instructions)

    def get_claude_md(self) -> str | None:
        """Silent sensor: nothing an agent acts on, so no resident guidance."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="a plan edit feeds the debouncer without blocking",
                command=(
                    "Edit any document under the plan directory, wait six seconds, "
                    "then list '<daemon untracked dir>/plan-fact-check/' and verify "
                    "a '<plan folder>.pending.json' record exists."
                ),
                harness_cannot_produce=(
                    "The outcome is a file written by a debounce timer seconds after "
                    "the hook returns, and the harness compares only the hook's "
                    "immediate decision and message patterns. Covered by "
                    "tests/unit/handlers/post_tool_use/test_plan_fact_check_feed.py."
                ),
                description=(
                    "The handler always allows; the quiet-period fire stores a "
                    "pending fact-check record and dispatches nothing."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Opt-in handler; writes only under the daemon untracked dir.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="an owed plan fact-check is delivered to the session once",
                command=(
                    "After the plan edit above has gone quiet, run any tool call "
                    "(for example Read a small file) and verify the tool result "
                    "carries an instruction to dispatch the 'plan-fact-checker' "
                    "agent with a '<plan folder>.diff' path, and that a second "
                    "tool call carries no such instruction."
                ),
                harness_cannot_produce=(
                    "The owed check is a record written by a debounce timer "
                    "seconds before this event, and the harness feeds one event "
                    "with no timer. Covered by "
                    "tests/unit/handlers/post_tool_use/test_plan_fact_check_feed.py "
                    "(TestDelivery)."
                ),
                description=(
                    "The next hook event after a debounced fire delivers the "
                    "fact-check as additionalContext, once, and never blocks."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"plan-fact-checker", r"REFUTED"],
                safety_notes="Opt-in handler; advisory only, never blocks.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
