"""PlanCloseApprovalHandler — a human closes a plan when the project says so.

Plan 00367. ``plan_workflow.close_requires_human_approval`` is OFF by
default: a fully completed plan is closed by the agent that completed it,
because a mandatory sign-off "is just going to lead to lots of plans kept
open for no good reason". A project that turns the key on gets a REAL gate,
not a sentence in a document nobody enforces: an agent's Write/Edit that
flips a ``PLAN.md`` ``**Status**`` to Complete, Cancelled or Superseded is
denied, and the deny names the two routes a human has -- edit the header
themselves outside Claude, or run ``hooks-daemon approve-plan-close NNNNN``
and let the agent retry, which consumes that one-shot approval.

The gate is on the FLIP, not on the terminal state: a plan a human already
closed stays editable (archive moves, index rows, a late journal pointer).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler import WorkspaceScope
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_file_path
from claude_code_hooks_daemon.handlers.utils.would_be_content import would_be_content
from claude_code_hooks_daemon.plan_qa.close_approval import (
    consume_approval,
    format_plan_number,
    plan_number_from_plan_doc_path,
)
from claude_code_hooks_daemon.plan_qa.model import PLAN_DOC_FILENAME, PlanDoc
from claude_code_hooks_daemon.utils.cli_command import (
    daemon_cli_command,
    daemon_cli_command_for_docs,
)
from claude_code_hooks_daemon.utils.path_predicates import path_is_file

_CONFIG_KEY: Final[str] = "plan_workflow.close_requires_human_approval"
_APPROVE_SUBCOMMAND: Final[str] = "approve-plan-close"

_RULE_WHY = (
    "This project requires a human to close a plan; the daemon enforces that "
    "rather than leaving it to a sentence in a document"
)
_RULE_FIX = (
    "Leave the status as it is and report the plan as ready to close; a human "
    "edits the header themselves or runs approve-plan-close NNNNN, after which "
    "the same edit goes through"
)
_RULE_VERBOSE = (
    f"`{_CONFIG_KEY}` is true in this project, so a Write/Edit that flips a "
    "PLAN.md `**Status**:` to Complete, Cancelled or Superseded is denied. Only "
    "the FLIP is gated -- a plan a human already closed stays editable. A human "
    "closes the plan in one of two ways: edit the `**Status**:` header themselves, "
    "outside Claude; or run `hooks-daemon approve-plan-close NNNNN`, which "
    "records a one-shot approval under the daemon's untracked directory that "
    "the very next terminal flip of THAT plan consumes. Do not wait in a loop "
    "for the approval: finish everything else, say the plan is ready to close, "
    "and stop. With the key false (the default) this handler never fires and a "
    "fully completed plan is closed by the agent that completed it."
)


class PlanCloseApprovalHandler(PreToolUseHandlerBase):
    """Deny an agent's terminal status flip of a PLAN.md while the key is on."""

    # REPO-scoped: the plan tree is repository-singular (see
    # CLAUDE/Code/WorkspaceResolution.md).
    workspace_scope: ClassVar[WorkspaceScope] = WorkspaceScope.REPO

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.PLAN_CLOSE_APPROVAL,
            priority=Priority.PLAN_CLOSE_APPROVAL,
            terminal=True,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.PLANNING,
                HandlerTag.BLOCKING,
                HandlerTag.TERMINAL,
            ],
        )
        # Injected by the registry for PLANNING-tagged handlers.
        self._track_plans_in_project: str | None = None
        self._close_requires_human_approval: bool = False
        self._rule = Rule(
            rule_id=RuleID.PLAN_CLOSE_APPROVAL,
            blocked=(
                "a PLAN.md `**Status**:` flip to Complete/Cancelled/Superseded "
                f"while `{_CONFIG_KEY}` is on and no human has approved it"
            ),
            why=_RULE_WHY,
            fix=_RULE_FIX,
            verbose=_RULE_VERBOSE,
        )
        self._formatter = RuleFormatter()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        if not self._close_requires_human_approval:
            return False
        plan_dir_rel = self._track_plans_in_project
        if plan_dir_rel is None:
            return False
        if hook_input.get(HookInputField.TOOL_NAME) not in (ToolName.WRITE, ToolName.EDIT):
            return False
        file_path = get_file_path(hook_input)
        if not file_path:
            return False
        normalised = file_path.replace("\\", "/")
        return f"/{plan_dir_rel}/" in normalised and normalised.endswith(f"/{PLAN_DOC_FILENAME}")

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        file_path = Path(str(get_file_path(hook_input)))
        current = self._current_content(file_path)
        proposed = would_be_content(hook_input, current=current)
        if proposed is None:
            # Edit on a missing file / unmatched old_string: the tool call
            # itself fails with its own error -- nothing to gate.
            return GatingResult(decision=Decision.ALLOW, context=[])

        if not self._is_terminal_flip(current, proposed):
            return GatingResult(decision=Decision.ALLOW, context=[])

        plan_number = plan_number_from_plan_doc_path(file_path, str(self._track_plans_in_project))
        if plan_number is None:
            plan_number = PlanDoc.parse(proposed).plan_number
        if plan_number is not None and consume_approval(
            ProjectContext.daemon_untracked_dir(), plan_number
        ):
            return GatingResult(
                decision=Decision.ALLOW,
                context=[
                    f"plan_close_approval: a human's one-shot approval for plan "
                    f"{format_plan_number(plan_number)} was consumed by this flip."
                ],
            )
        return GatingResult(
            decision=Decision.DENY,
            reason=self._deny_reason(hook_input, plan_number),
        )

    @staticmethod
    def _current_content(file_path: Path) -> str | None:
        # `unreadable_means=None`: a path the daemon cannot stat is treated
        # like a missing file, so a Write still judges its payload and an
        # Edit (which needs the current text) is left to fail on its own.
        if path_is_file(file_path, unreadable_means=None) is not True:
            return None
        return file_path.read_text(encoding="utf-8")

    @staticmethod
    def _is_terminal_flip(current: str | None, proposed: str) -> bool:
        after = PlanDoc.parse(proposed)
        if not after.is_terminal:
            return False
        if current is None:
            return True
        return PlanDoc.parse(current).status != after.status

    def _deny_reason(self, hook_input: dict[str, Any], plan_number: int | None) -> str:
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure
        if transcript_path and tracker.was_disclosed(transcript_path, RuleID.PLAN_CLOSE_APPROVAL):
            prose = self._formatter.terse(self._rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, RuleID.PLAN_CLOSE_APPROVAL)
            prose = self._formatter.verbose(self._rule)

        number = format_plan_number(plan_number) if plan_number is not None else "NNNNN"
        route = (
            f"A human closes plan {number} by editing its `**Status**:` header themselves, "
            f"or by running `{daemon_cli_command(_APPROVE_SUBCOMMAND, number)}` and then "
            "letting this exact edit be retried."
        )
        return f"{prose}\n\n{route}"

    def get_rules(self) -> list[Rule]:
        return [self._rule]

    def get_claude_md(self) -> str | None:
        return (
            "## plan_close_approval — a human closes a plan when the project says so\n"
            "\n"
            f"`{_CONFIG_KEY}` is OFF by default: a fully completed plan is closed\n"
            "by the agent that completed it, in the same commit that archives it.\n"
            "When a project sets the key to `true`, a Write/Edit that flips a\n"
            "`PLAN.md` `**Status**:` to Complete, Cancelled or Superseded is DENIED\n"
            "until a human has approved it. Only the flip is gated; a plan a human\n"
            "already closed stays editable.\n"
            "\n"
            "**The human's route** (not yours): edit the header themselves outside\n"
            "Claude, or run\n"
            f"`{daemon_cli_command_for_docs(_APPROVE_SUBCOMMAND, 'NNNNN')}`, which\n"
            "records a one-shot approval that the very next terminal flip of that\n"
            "plan consumes. When denied, finish everything else, say the plan is\n"
            "ready to close, and stop — do not poll for the approval.\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="plan-close-approval - denies a terminal flip while the key is on",
                command=(
                    f"With `{_CONFIG_KEY}: true` in `.claude/hooks-daemon.yaml` (daemon "
                    "restarted), use the Edit tool to change an active plan's "
                    "`**Status**: In Progress` line to `**Status**: Complete`"
                ),
                harness_cannot_produce=(
                    "The gate is scoped to the configured plan directory and is OFF "
                    "in this project's config, so no scratch-directory payload reaches "
                    "it and a real-tree payload would need a config flip plus a restart. "
                    "Covered by tests/unit/handlers/pre_tool_use/test_plan_close_approval.py."
                ),
                description=(
                    "An agent's flip of a PLAN.md to a terminal status must be denied, "
                    "naming the config key and the approve-plan-close route."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"close_requires_human_approval",
                    r"approve-plan-close",
                ],
                safety_notes="Deny path — no file is written",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="plan-close-approval - allows the flip after approve-plan-close",
                command=(
                    f"With the key on, run `{daemon_cli_command_for_docs(_APPROVE_SUBCOMMAND, 'NNNNN')}` "
                    "for the plan, then retry the same Edit; a second identical flip "
                    "attempt is denied again"
                ),
                harness_cannot_produce=(
                    "Same boundary as its deny sibling: reaching the gate means a "
                    "config flip, a restart and a real plan document."
                ),
                description=("A human's one-shot approval lets exactly one terminal flip through."),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"approval"],
                safety_notes="Consumes the marker; flip the status back afterwards",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
