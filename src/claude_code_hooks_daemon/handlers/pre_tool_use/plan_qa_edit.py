"""PlanQaEditHandler — Stage 1 plan QA lint at Write/Edit time (Plan 00144).

Runs the edit-stage plan QA checks against the WOULD-BE content of a
``PLAN.md`` under the plan directory: for Write that is the payload itself;
for Edit the old/new replacement is applied to the current file first. In
``edit_mode: block`` any block-level finding denies the tool call with the
exact remediation; ``warn`` downgrades everything to advisory context;
grandfathered legacy plans (``legacy_plan_allowlist``) only ever advise.

Deliberately hot-path cheap: no tree scan, no git subprocess — single-file
invariants only (cross-file invariants belong to the commit gate and sweep).
"""

import logging
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.plan_qa.context import edit_context
from claude_code_hooks_daemon.plan_qa.model import PLAN_DOC_FILENAME
from claude_code_hooks_daemon.plan_qa.report import format_advisory, format_block_reason
from claude_code_hooks_daemon.plan_qa.runner import run_stage
from claude_code_hooks_daemon.plan_qa.types import Finding, Level, Stage

logger = logging.getLogger(__name__)

_EDIT_MODE_BLOCK: Final[str] = "block"
_EDIT_MODE_OFF: Final[str] = "off"

_FIELD_FILE_PATH: Final[str] = "file_path"
_FIELD_CONTENT: Final[str] = "content"
_FIELD_OLD_STRING: Final[str] = "old_string"
_FIELD_NEW_STRING: Final[str] = "new_string"
_FIELD_REPLACE_ALL: Final[str] = "replace_all"

_SINGLE_REPLACEMENT: Final[int] = 1


class PlanQaEditHandler(Handler):
    """Blocking/advisory edit-time lint for plan documents."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.PLAN_QA_EDIT,
            priority=Priority.PLAN_QA_EDIT,
            terminal=False,
            tags=[
                HandlerTag.PLANNING,
                HandlerTag.VALIDATION,
                HandlerTag.CONTENT_QUALITY,
            ],
        )
        # Injected by the registry for PLANNING-tagged handlers.
        self._track_plans_in_project: str | None = None
        self._plan_qa: Any = None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        if hook_input.get(HookInputField.TOOL_NAME) not in (ToolName.WRITE, ToolName.EDIT):
            return False
        plan_dir_rel = self._track_plans_in_project
        if plan_dir_rel is None:
            return False
        policy = self._plan_qa
        if policy is None or not policy.enabled or policy.edit_mode == _EDIT_MODE_OFF:
            return False

        file_path = hook_input.get(HookInputField.TOOL_INPUT, {}).get(_FIELD_FILE_PATH, "")
        if not file_path or Path(file_path).name != PLAN_DOC_FILENAME:
            return False
        return f"/{plan_dir_rel}/" in file_path

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        tool_input = hook_input.get(HookInputField.TOOL_INPUT, {})
        file_path = Path(tool_input.get(_FIELD_FILE_PATH, ""))
        exists_before = file_path.is_file()

        content = self._would_be_content(hook_input, file_path, exists_before)
        if content is None:
            # Edit on a missing file / unmatched old_string: the tool call
            # itself will fail with its own error — nothing to lint.
            return HookResult(decision=Decision.ALLOW, context=[])

        context = edit_context(
            project_root=ProjectContext.project_root(),
            plan_dir_rel=str(self._track_plans_in_project),
            policy=self._plan_qa,
            file_path=file_path,
            file_content=content,
            file_exists_before=exists_before,
        )
        findings = run_stage(Stage.EDIT, context)
        if not findings:
            return HookResult(decision=Decision.ALLOW, context=[])

        blockers = [finding for finding in findings if finding.level == Level.BLOCK]
        if blockers and self._plan_qa.edit_mode == _EDIT_MODE_BLOCK:
            return HookResult(decision=Decision.DENY, reason=format_block_reason(blockers))
        return self._advisory_result(findings)

    def _would_be_content(
        self,
        hook_input: dict[str, Any],
        file_path: Path,
        exists_before: bool,
    ) -> str | None:
        """Content the file WOULD have after the tool call, or None to skip."""
        tool_input = hook_input.get(HookInputField.TOOL_INPUT, {})
        if hook_input.get(HookInputField.TOOL_NAME) == ToolName.WRITE:
            raw: Any = tool_input.get(_FIELD_CONTENT, "")
            return str(raw)

        if not exists_before:
            return None
        old_string = str(tool_input.get(_FIELD_OLD_STRING, ""))
        new_string = str(tool_input.get(_FIELD_NEW_STRING, ""))
        current = file_path.read_text(encoding="utf-8")
        if not old_string or old_string not in current:
            return None
        if bool(tool_input.get(_FIELD_REPLACE_ALL, False)):
            return current.replace(old_string, new_string)
        return current.replace(old_string, new_string, _SINGLE_REPLACEMENT)

    @staticmethod
    def _advisory_result(findings: list[Finding]) -> HookResult:
        return HookResult(decision=Decision.ALLOW, context=[format_advisory(findings)])

    def get_claude_md(self) -> str | None:
        return (
            "## plan_qa_edit — PLAN.md writes are linted in real time\n"
            "\n"
            "Every Write/Edit of a `PLAN.md` under the plan directory is checked\n"
            "against the plan QA edit-stage rules on the content the file WOULD\n"
            "have. Block-level violations (in `edit_mode: block`) deny the tool\n"
            "call with the exact remediation; fix the content and retry.\n"
            "\n"
            "**Rules that block new plan material**:\n"
            "\n"
            "- a parseable `**Status**:` line must exist (`status-line-present`)\n"
            "- the status token must be one of: Not Started, In Progress,\n"
            "  Complete, Blocked, Cancelled, Superseded, Dormant\n"
            "  (`status-enum-and-date`)\n"
            "- the header must not contradict the body — do not leave\n"
            "  `Not Started`/`In Progress` above an all-ticked task list or\n"
            '  "ALL DONE" prose; flip the status instead\n'
            "  (`header-body-coherence`)\n"
            "- use the template task grammar `- [ ] ⬜ **Task N.N**:` — not\n"
            "  ad-hoc markers like `[✓]`/`[⏳]` (`task-grammar`)\n"
            "\n"
            "**Advisory rules**: missing Created/Owner/Priority headers on new\n"
            "plans; a terminal status set while the folder is still in the plan\n"
            "root (the same commit must `git mv` it to the archive dir and\n"
            "update the README row); edits to archived plans; backticked\n"
            "`src/...` paths that no longer exist.\n"
            "\n"
            "Grandfathered plans in `plan_workflow.qa.legacy_plan_allowlist`\n"
            "only ever advise. Lint any file on demand:\n"
            "`$PYTHON -m claude_code_hooks_daemon.daemon.cli plan-qa --lint <file>`."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="plan-qa edit lint - blocks PLAN.md without status header",
                command=(
                    "Use the Write tool to create a new PLAN.md under the plan "
                    "directory whose content has a title but NO `**Status**:` line"
                ),
                description=(
                    "Writing a new plan document without a parseable status header "
                    "must be denied with the status-line-present remediation."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"status-line-present", r"\*\*Status\*\*"],
                safety_notes="Deny path — no file is written; retry with a valid header",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="plan-qa edit lint - allows a valid plan document",
                command=(
                    "Use the Write tool to create a PLAN.md under the plan directory "
                    "with a valid `**Status**: Not Started` header and template tasks"
                ),
                description="A well-formed plan document passes the edit lint silently.",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Creates a scratch plan folder; remove it after the test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
