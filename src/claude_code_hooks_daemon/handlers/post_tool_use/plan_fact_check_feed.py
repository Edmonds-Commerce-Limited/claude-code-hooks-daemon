"""PlanFactCheckFeedHandler - feeds plan edits to the debouncer (Plan 00480 Task 4.1).

A burst of edits to one plan should trigger ONE fact check, not one per edit.
This PostToolUse handler watches writes to a plan's tracked documents (a
``Write``/``Edit``, or a Bash command whose written paths
``get_written_file_paths`` can name) and triggers the daemon-wide keyed
debouncer, keyed by plan folder. When the plan has been quiet for
``quiet_seconds`` (default 5), :func:`_on_quiet` runs.

**Delivery boundary (Plan 00480 open question 1).** :func:`_on_quiet` dispatches
NOTHING. It logs at info level and stores the diff since the plan's last
fact-checked content as a *pending fact-check* record, via
:func:`~claude_code_hooks_daemon.utils.plan_fact_check.process_quiet_plan`. A
later task delivers it; until then this handler ships default-DISABLED.

Never blocks and never speaks.
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
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.utils import get_written_file_paths
from claude_code_hooks_daemon.utils.plan_fact_check import (
    STATE_SUBDIR,
    PlanFactCheckState,
    PlanFolderMatch,
    plan_folder_match,
    process_quiet_plan,
)
from claude_code_hooks_daemon.utils.plan_trigger import plan_dir_for

logger = logging.getLogger(__name__)

DEFAULT_QUIET_SECONDS: Final[float] = 5.0


def _on_quiet(fire: DebounceFire, *, plan_root: Path, state_dir: Path) -> None:
    """Debounce callback: record the pending fact-check. Dispatches nothing."""
    process_quiet_plan(
        plan_root,
        str(fire.payload),
        PlanFactCheckState(state_dir),
        trigger_count=fire.trigger_count,
        now=time.time(),
    )


class PlanFactCheckFeedHandler(PostToolUseHandlerBase):
    """Feed plan edits to the debouncer so a burst yields one pending fact-check."""

    # REPO-scoped: the plan tree is repository-singular.
    workspace_scope: ClassVar[WorkspaceScope] = WorkspaceScope.REPO

    # Opt-in: delivery of the check is not built yet (Plan 00480 Task 4.3).
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
        """One match per distinct plan folder the event wrote a tracked document in."""
        plan_dir = plan_dir_for(self._project_layout)
        found: dict[str, PlanFolderMatch] = {}
        for path in get_written_file_paths(hook_input):
            match = plan_folder_match(path, plan_dir)
            if match is not None:
                found[str(match.plan_root)] = match
        return list(found.values())

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True when the event wrote a tracked document of a plan."""
        return bool(self._plan_matches(hook_input))

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Trigger the debouncer once per touched plan. Always ALLOW."""
        matches = self._plan_matches(hook_input)
        if not matches:
            return BlockingResult(decision=Decision.ALLOW)
        state_dir = ProjectContext.daemon_untracked_dir() / STATE_SUBDIR
        debouncer = get_debouncer()
        for match in matches:
            debouncer.trigger(
                str(match.plan_root),
                quiet_seconds=float(self._quiet_seconds),
                callback=partial(_on_quiet, plan_root=match.plan_root, state_dir=state_dir),
                payload=match.folder,
            )
        return BlockingResult(decision=Decision.ALLOW)

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
        ]
