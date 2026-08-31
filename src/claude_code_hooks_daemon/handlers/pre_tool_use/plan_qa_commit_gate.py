"""PlanQaCommitGateHandler — Stage 2 plan QA gate on git commit (Plan 00144).

On a ``git commit`` Bash command, the STAGED tree is evaluated against the
cross-file plan QA checks (index-at-birth, terminal-state atomicity, number
collisions, row/folder bijection, statistics recount, counter sanity,
commit-message hygiene). Most plan rot is cross-file — a single-file edit
hook cannot see that a status flip is missing its ``git mv`` and README row;
this gate can, at exactly the moment the drift would become history.

Rollout is warn-first: ``commit_gate_mode: warn`` renders findings as
advisory context; ``block`` denies with a diffable TODO list. Guard rails:
never fires for commits inside a repo other than the project's own (nested
repos, foreign worktrees), and a missing plan directory degrades to a
structural warning instead of crashing the chain.
"""

import logging
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.plan_qa.context import staged_context
from claude_code_hooks_daemon.plan_qa.report import format_advisory, format_block_reason
from claude_code_hooks_daemon.plan_qa.runner import run_stage
from claude_code_hooks_daemon.plan_qa.types import Level, Stage
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command_for_docs
from claude_code_hooks_daemon.utils.git_commit_parsing import (
    extract_commit_message as _extract_commit_message,
)
from claude_code_hooks_daemon.utils.git_commit_parsing import (
    extract_commit_pathspecs as _extract_commit_pathspecs,
)
from claude_code_hooks_daemon.utils.git_commit_parsing import (
    is_git_commit as _is_git_commit,
)
from claude_code_hooks_daemon.utils.git_commit_parsing import (
    tokenise_command as _tokenise,
)
from claude_code_hooks_daemon.utils.git_repo import GitRepo

logger = logging.getLogger(__name__)

# Single source of truth for the one rule this handler's DENY path enforces
# (Plan 00116, gate-level granularity: one Rule per GATE, not one per plan QA
# cross-file invariant). The per-check findings from format_block_reason()
# are dynamic content and stay FULLY present in both verbose and terse
# forms; only the surrounding teaching prose about the gate itself goes
# terse-after-first-fire.
_RULE_WHY = "Most plan rot is cross-file and a single-file edit hook cannot see it"
_RULE_FIX = "Amend the commit to also stage what each finding's remediation names below"
_RULE_VERBOSE = (
    "Every `git commit` is checked against the STAGED tree's cross-file plan "
    "QA invariants -- index-at-birth, terminal-state atomicity, number "
    "collisions, row/folder bijection, statistics recount, counter sanity, "
    "commit-message hygiene. Each finding below names its own remediation -- "
    "amend the commit to include it and retry."
)

_MODE_BLOCK: Final[str] = "block"
_MODE_OFF: Final[str] = "off"

_FIELD_COMMAND: Final[str] = "command"
_CWD_FIELD: Final[str] = "cwd"


class PlanQaCommitGateHandler(PreToolUseHandlerBase):
    """Warn-first cross-file plan QA gate on git commit."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.PLAN_QA_COMMIT_GATE,
            priority=Priority.PLAN_QA_COMMIT_GATE,
            terminal=False,
            tags=[
                HandlerTag.PLANNING,
                HandlerTag.VALIDATION,
                HandlerTag.GIT,
            ],
        )
        # Injected by the registry for PLANNING-tagged handlers.
        self._track_plans_in_project: str | None = None
        self._plan_qa: Any = None
        self._rule = Rule(
            rule_id=RuleID.PLAN_QA_COMMIT,
            blocked="a git commit violates a block-level plan QA cross-file invariant",
            why=_RULE_WHY,
            fix=_RULE_FIX,
            verbose=_RULE_VERBOSE,
        )
        self._formatter = RuleFormatter()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.BASH:
            return False
        if self._track_plans_in_project is None:
            return False
        policy = self._plan_qa
        if policy is None or not policy.enabled or policy.commit_gate_mode == _MODE_OFF:
            return False
        command = hook_input.get(HookInputField.TOOL_INPUT, {}).get(_FIELD_COMMAND, "")
        return _is_git_commit(_tokenise(command))

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        project_root = ProjectContext.project_root()
        plan_dir_rel = str(self._track_plans_in_project)

        if self._is_foreign_repo(hook_input, project_root):
            return GatingResult(decision=Decision.ALLOW, context=[])

        command = hook_input.get(HookInputField.TOOL_INPUT, {}).get(_FIELD_COMMAND, "")
        tokens = _tokenise(command)
        try:
            context = staged_context(
                project_root=project_root,
                plan_dir_rel=plan_dir_rel,
                policy=self._plan_qa,
                commit_message=_extract_commit_message(tokens),
                pathspecs=_extract_commit_pathspecs(tokens),
            )
        except FileNotFoundError:
            return GatingResult(
                decision=Decision.ALLOW,
                context=[
                    f"⚠️  PLAN QA: configured plan directory {plan_dir_rel}/ does not exist — "
                    "commit-gate checks skipped. Create it or fix plan_workflow.directory."
                ],
            )

        findings = run_stage(Stage.COMMIT, context)
        if not findings:
            return GatingResult(decision=Decision.ALLOW, context=[])

        blockers = [finding for finding in findings if finding.level == Level.BLOCK]
        if blockers and self._plan_qa.commit_gate_mode == _MODE_BLOCK:
            return GatingResult(
                decision=Decision.DENY,
                reason=self._blocking_message(blockers, hook_input),
            )
        return GatingResult(decision=Decision.ALLOW, context=[format_advisory(findings)])

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's block-mode denial."""
        return [self._rule]

    def _blocking_message(self, blockers: list[Any], hook_input: dict[str, Any]) -> str:
        """Build the block-mode deny message: verbose-first/terse-after teaching
        prose (Plan 00116, Decision G), with the per-check findings from
        ``format_block_reason`` ALWAYS fully present -- they are dynamic
        content, not the static teaching text the disclosure ladder governs.
        """
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure

        if transcript_path and tracker.was_disclosed(transcript_path, RuleID.PLAN_QA_COMMIT):
            prose = self._formatter.terse(self._rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, RuleID.PLAN_QA_COMMIT)
            prose = self._formatter.verbose(self._rule)

        return f"{prose}\n\n{format_block_reason(blockers)}"

    @staticmethod
    def _is_foreign_repo(hook_input: dict[str, Any], project_root: Path) -> bool:
        """True when the command runs inside a repo other than the project's.

        Nested/vendor repos and other worktrees own their history — this
        gate only polices the project's own plan tree.
        """
        cwd_raw = hook_input.get(_CWD_FIELD)
        if not cwd_raw:
            return False
        repo = GitRepo.resolve_for(Path(cwd_raw))
        return repo is not None and repo.root != project_root

    def get_claude_md(self) -> str | None:
        return (
            "## plan_qa_commit_gate — cross-file plan checks at git commit\n"
            "\n"
            "Every `git commit` is checked against the STAGED tree's plan QA\n"
            "invariants. In `commit_gate_mode: warn` (the rollout default)\n"
            "violations appear as advisory context — read them and amend the\n"
            "commit content BEFORE committing; in `block` mode they deny the\n"
            "commit with a TODO list of what the commit must also contain.\n"
            "\n"
            "**The invariants**:\n"
            "\n"
            "- creating a plan folder ⇒ the SAME commit stages its README\n"
            "  index row (`index-at-birth`) and the number must come from the\n"
            "  git counter / mkplan.bash (`counter-sanity`, `no-new-collisions`)\n"
            "- flipping a plan to Complete/Cancelled/Superseded ⇒ the SAME\n"
            "  commit contains the `git mv` into the archive dir AND the README\n"
            "  row + statistics update (`terminal-state-atomic`)\n"
            "- every folder has a README row in the section matching its\n"
            "  location, and every row's link resolves\n"
            "  (`row-folder-bijection`, `stats-recount`)\n"
            "- every line of the README index stays under 500 characters\n"
            "  (`index-row-length`): a row is a POINTER — a link, a status and\n"
            "  one clause — because the rationale belongs in the linked PLAN.md\n"
            "- a commit claiming `Plan NNNNN` that stages src/tests/config\n"
            "  changes should also update that plan's PLAN.md\n"
            "  (`same-commit-plan-doc`); reference plans as `Plan NNNNN:`\n"
            "  (`plan-ref-format`)\n"
            "- (advise-only, Plan 00163) a commit that changes a plan's PLAN.md\n"
            "  tasks should stage a `JOURNAL/` entry recording what changed\n"
            "  (`journal-entry-with-progress`); a terminal-status flip should\n"
            "  stage a closing journal entry when\n"
            "  `plan_workflow.qa.journal.enforce_on_completion` is on\n"
            "  (`journal-completion-entry`)\n"
            "- (advise-only, Plan 00190) a commit whose PLAN.md loses 2,000+\n"
            "  bytes while staging NO journal entry is flagged\n"
            "  (`plan-shrink-without-journal`): that shape usually means\n"
            "  narrative was DELETED rather than relocated into `JOURNAL/`.\n"
            "  If the content was genuinely obsolete this is fine as it stands\n"
            "  — git keeps the history; the check exists so you notice which\n"
            "  of the two you just did\n"
            "\n"
            "Check the staged tree any time without committing:\n"
            f"`{daemon_cli_command_for_docs('plan-qa', '--check-staged')}`.\n"
            "Commits inside nested/vendor repos or foreign worktrees are exempt."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="plan-qa commit gate - warns on terminal flip without archive move",
                command=(
                    "Stage a PLAN.md change flipping a root plan's status to Complete "
                    "(without git mv or README changes), then run `git commit` on it"
                ),
                description=(
                    "In warn mode the commit proceeds but the PostToolUse context "
                    "contains a terminal-state-atomic finding listing the missing "
                    "git mv + README updates."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"terminal-state-atomic|Plan QA"],
                safety_notes="Warn mode — commit is not blocked; revert the test commit after",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
