"""PlanQaEditHandler — Stage 1 plan QA lint at Write/Edit time (Plan 00144).

Runs the edit-stage plan QA checks against the WOULD-BE content of a
``PLAN.md`` under the plan directory: for Write that is the payload itself;
for Edit the old/new replacement is applied to the current file first. In
``edit_mode: block`` any block-level finding denies the tool call with the
exact remediation; ``warn`` downgrades everything to advisory context;
grandfathered legacy plans (``legacy_plan_allowlist``) only ever advise.

Deliberately hot-path cheap for LINTING: no tree scan, no git subprocess —
single-file invariants only (cross-file invariants belong to the commit gate
and sweep).

One exception, and it is not a lint: creating a new ``PLAN.md`` advances the
per-repo plan counter, which does touch git. That writer lived on
``validate_plan_number`` until Plan 00237 removed it, and it has to live
somewhere — the counter is the value the commit-stage ``counter-sanity`` check
reads, so a plan created with no writer on this path leaves the counter behind
and blocks the NEXT plan's commit. It fires only on CREATION of a plan
document, not on edits, so the hot path is unchanged.
"""

import logging
from datetime import date
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.utils.plan_numbering import record_new_plan_document
from claude_code_hooks_daemon.plan_qa.context import edit_context
from claude_code_hooks_daemon.plan_qa.model import PLAN_DOC_FILENAME, README_FILENAME
from claude_code_hooks_daemon.plan_qa.remedy import remedy_sentence
from claude_code_hooks_daemon.plan_qa.report import format_advisory, format_block_reason
from claude_code_hooks_daemon.plan_qa.runner import run_stage
from claude_code_hooks_daemon.plan_qa.types import Finding, Level, Stage
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command_for_docs

logger = logging.getLogger(__name__)

_EDIT_MODE_BLOCK: Final[str] = "block"
_EDIT_MODE_OFF: Final[str] = "off"

_FIELD_FILE_PATH: Final[str] = "file_path"
_FIELD_CONTENT: Final[str] = "content"
_FIELD_OLD_STRING: Final[str] = "old_string"
_FIELD_NEW_STRING: Final[str] = "new_string"
_FIELD_REPLACE_ALL: Final[str] = "replace_all"

_SINGLE_REPLACEMENT: Final[int] = 1

_MARKDOWN_SUFFIX: Final[str] = ".md"
_JOURNAL_MODE_OFF: Final[str] = "off"


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
                # BLOCKING because `edit_mode: block` is the SHIPPED default in
                # .claude/hooks-daemon.yaml, so a block-level finding denies the
                # write in a default install. (Its sibling plan_qa_commit_gate
                # ships `warn` and is deliberately NOT tagged blocking.)
                HandlerTag.BLOCKING,
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
        if not file_path or f"/{plan_dir_rel}/" not in file_path:
            return False
        return self._is_lintable_plan_file(file_path, policy)

    def _is_lintable_plan_file(self, file_path: str, policy: Any) -> bool:
        """True for a PLAN.md, the plan INDEX, or a journal day-file.

        Journal files are ``*.md`` directly inside a ``{journal_dir_name}/``
        directory (Plan 00163); the per-check target resolvers do the precise
        folder-structure validation, so this stays a cheap string gate.

        The plan index (``{plan_dir}/README.md``, Plan 00218) is admitted
        because it has a shape rule of its own — ``index-row-length`` — whose
        only other enforcement is a full test-suite run. Widening the gate is
        safe: every plan-DOCUMENT check scopes itself through ``edit_target()``,
        which returns ``None`` for anything that is not a ``PLAN.md``, so none
        of them can fire on a README.
        """
        path = Path(file_path)
        if path.name == PLAN_DOC_FILENAME:
            return True
        if self._is_plan_index(path):
            return True
        journal = getattr(policy, "journal", None)
        if journal is None or not journal.enabled or journal.mode == _JOURNAL_MODE_OFF:
            return False
        return path.suffix == _MARKDOWN_SUFFIX and path.parent.name == journal.dir_name

    def _is_plan_index(self, path: Path) -> bool:
        """True only for the README at the plan directory ROOT.

        A README inside a plan folder is a supporting document, not the index,
        so the parent directory must be the plan directory itself. ``matches()``
        has already established that the path is under the plan directory.
        """
        if path.name != README_FILENAME:
            return False
        plan_dir_rel = self._track_plans_in_project
        if plan_dir_rel is None:
            return False
        return path.parent.name == Path(plan_dir_rel).name

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        tool_input = hook_input.get(HookInputField.TOOL_INPUT, {})
        file_path = Path(tool_input.get(_FIELD_FILE_PATH, ""))
        exists_before = file_path.is_file()

        content = self._would_be_content(hook_input, file_path, exists_before)
        if content is None:
            # Edit on a missing file / unmatched old_string: the tool call
            # itself will fail with its own error — nothing to lint.
            return HookResult(decision=Decision.ALLOW, context=[])

        if not exists_before:
            self._record_allocation(file_path)

        content_before = file_path.read_text(encoding="utf-8") if exists_before else None
        context = edit_context(
            project_root=ProjectContext.project_root(),
            plan_dir_rel=str(self._track_plans_in_project),
            policy=self._plan_qa,
            file_path=file_path,
            file_content=content,
            file_exists_before=exists_before,
            file_content_before=content_before,
            today=date.today(),
        )
        findings = run_stage(Stage.EDIT, context)
        if not findings:
            return HookResult(decision=Decision.ALLOW, context=[])

        blockers = [finding for finding in findings if finding.level == Level.BLOCK]
        if blockers and self._plan_qa.edit_mode == _EDIT_MODE_BLOCK:
            return HookResult(decision=Decision.DENY, reason=format_block_reason(blockers))
        return self._advisory_result(findings)

    def _record_allocation(self, file_path: Path) -> None:
        """Advance the per-repo plan counter for a newly-created plan document.

        Relocated from ``validate_plan_number`` (Plan 00237). The helper does
        the deciding — whether this path is a new plan document at all, and
        whether its number is inside the window the counter could have
        allocated — so a non-plan write costs one cheap path check here.

        FAIL-SAFE, and the asymmetry is the point: losing the counter is
        recoverable (the next read re-bootstraps it from a filesystem scan),
        while losing the agent's plan document because git config misbehaved
        is not. So the failure is logged with its traceback and the write
        proceeds. Logged rather than swallowed — a writer that has silently
        stopped working looks exactly like one with nothing to do.
        """
        try:
            recorded = record_new_plan_document(
                file_path,
                str(self._track_plans_in_project),
                ProjectContext.project_root(),
            )
        except Exception:
            logger.warning(
                "plan_qa_edit: failed to record plan allocation for %s",
                file_path,
                exc_info=True,
            )
        else:
            if recorded is not None:
                logger.info("plan_qa_edit: plan counter advanced to %d", recorded)

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
            "The plan-index `README.md` is linted too, against ONE rule:\n"
            "`index-row-length`. Keep every line under 500 characters — an index\n"
            "row is a POINTER (a link, a status and one clause), not a summary,\n"
            "because the rationale belongs in the linked `PLAN.md` and a second\n"
            "copy in the index is the one that goes stale. Only an edit that\n"
            "makes the index WORSE is blocked (more over-long lines, or a longer\n"
            "worst offender), so an index that already has one stays editable —\n"
            "including by the edit that fixes it. No other plan-document rule\n"
            "applies to the index: it has no `**Status**:` line and needs none.\n"
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
            "- a `PLAN.md` must stay under the size tiers (`plan-doc-size`):\n"
            "  advisory above 18,000 bytes / 350 lines, escalated warning above\n"
            "  25,000 / 500, and edits BLOCKED above 35,000 / 900. "
            f"{remedy_sentence()} Only an edit that\n"
            "  GROWS the file can be blocked (shrinking is silent, same-size\n"
            "  only advises), so an oversized plan can always be updated and\n"
            "  refactored down; declare a genuine exception in the file with\n"
            "  `<!-- MUST_EXCEED_PLAN_SIZE_BECAUSE: <reason> -->`. Journals,\n"
            "  supporting docs and the plan-index README are exempt at any\n"
            "  size — if the advisory notes the folder has none, that is a\n"
            "  hint the bulk may want a named supporting document, not proof.\n"
            "\n"
            "**Advisory rules**: missing Created/Owner/Priority headers on new\n"
            "plans; a terminal status set while the folder is still in the plan\n"
            "root (the same commit must `git mv` it to the archive dir and\n"
            "update the README row); edits to archived plans; backticked\n"
            "`src/...` paths that no longer exist.\n"
            "\n"
            "**Journal day-files** (`JOURNAL/NNNNN-Journal-YY-MM-DD.md`) are also\n"
            "linted: the name must match the grammar and the enclosing plan\n"
            "number (`journal-dayfile-naming`, ADVISE), and edits must APPEND —\n"
            "never rewrite or remove earlier entries (`journal-append-only`,\n"
            "ADVISE). Corrections are new dated entries at the bottom, not edits\n"
            "to old ones.\n"
            "\n"
            "**A Write/Edit to a journal day-file dated anything other than\n"
            "TODAY is BLOCKED by default** (`journal-dayfile-is-today`) — this\n"
            "includes yesterday's date. A session that spans midnight must start\n"
            "TODAY's day-file, not keep appending to yesterday's; the block\n"
            "message names the exact today-dated filename to write instead.\n"
            "Controlled independently of the other journal checks via\n"
            "`plan_workflow.qa.journal.today_only_mode` (advise | block | off;\n"
            "default block).\n"
            "\n"
            "A journal is **unbounded by design** — its length is never a problem\n"
            "and it must not be tidied or trimmed. It is safe to grow forever\n"
            "precisely because it is never read whole: grep it, `tail -n N` the\n"
            "newest day-file directly, or send a sub-agent. `PLAN.md` is the\n"
            "opposite — read in full every session, so keep it lean and curated,\n"
            "with history in git rather than in the file body.\n"
            "\n"
            "Grandfathered plans in `plan_workflow.qa.legacy_plan_allowlist`\n"
            "only ever advise. Lint any file on demand:\n"
            f"`{daemon_cli_command_for_docs('plan-qa', '--lint', '<file>')}`."
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
            AcceptanceTest(
                title="plan-qa edit lint - blocks a stale-dated journal day-file",
                command=(
                    "Use the Write tool to write to an existing plan's "
                    "`JOURNAL/NNNNN-Journal-YY-MM-DD.md` day-file whose date is "
                    "YESTERDAY (or any other non-today date), not today's"
                ),
                description=(
                    "A journal day-file edit dated anything other than today must be "
                    "denied with the journal-dayfile-is-today remediation naming the "
                    "exact today-dated filename to use instead."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"journal-dayfile-is-today", r"not today"],
                safety_notes="Deny path — no file is written; retry against today's day-file",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="plan-qa edit lint - allows today's journal day-file",
                command=(
                    "Use the Write tool to append to (or create) a plan's "
                    "`JOURNAL/NNNNN-Journal-YY-MM-DD.md` day-file dated TODAY"
                ),
                description="A today-dated journal day-file edit passes the recency check.",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Creates/appends a scratch journal entry; remove it after the test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
