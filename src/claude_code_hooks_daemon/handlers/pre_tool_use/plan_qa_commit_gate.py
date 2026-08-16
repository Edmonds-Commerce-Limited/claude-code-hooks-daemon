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
import shlex
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.plan_qa.context import staged_context
from claude_code_hooks_daemon.plan_qa.report import format_advisory, format_block_reason
from claude_code_hooks_daemon.plan_qa.runner import run_stage
from claude_code_hooks_daemon.plan_qa.types import Level, Stage
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command_for_docs
from claude_code_hooks_daemon.utils.git_repo import GitRepo

logger = logging.getLogger(__name__)

_MODE_BLOCK: Final[str] = "block"
_MODE_OFF: Final[str] = "off"

_GIT_TOKEN: Final[str] = "git"
_COMMIT_TOKEN: Final[str] = "commit"
_FIELD_COMMAND: Final[str] = "command"
_CWD_FIELD: Final[str] = "cwd"

_MESSAGE_FLAGS: Final[frozenset[str]] = frozenset({"-m", "--message"})
_MESSAGE_FLAG_PREFIXES: Final[tuple[str, ...]] = ("-m", "--message=")
_MESSAGE_JOINER: Final[str] = "\n\n"

# git-commit flags that take a SEPARATE value token (not a pathspec). Kept
# narrow to the flags realistically seen on a commit line — sufficient to
# stop e.g. the -m message text or an --author value from being mistaken
# for a path, without attempting a full git-commit(1) CLI parse.
_VALUE_FLAGS: Final[frozenset[str]] = frozenset(
    {
        "-m",
        "--message",
        "-F",
        "--file",
        "-c",
        "-C",
        "--reuse-message",
        "--reedit-message",
        "--fixup",
        "--squash",
        "--author",
        "--date",
        "-u",
        "--untracked-files",
    }
)
_PATHSPEC_SEPARATOR: Final[str] = "--"


def _tokenise(command: str) -> list[str]:
    """Shell-tokenise ``command``; empty list when unparseable."""
    try:
        return shlex.split(command)
    except ValueError:
        return []


def _is_git_commit(tokens: list[str]) -> bool:
    """True when a ``commit`` token follows a ``git`` token.

    Tokenisation keeps quoted strings whole, so prose like
    ``echo 'git commit is fun'`` does not match.
    """
    for index, token in enumerate(tokens):
        if token == _GIT_TOKEN and _COMMIT_TOKEN in tokens[index + 1 :]:
            return True
    return False


def _extract_commit_message(tokens: list[str]) -> str | None:
    """The ``-m``/``--message`` payload(s), joined; None when absent."""
    parts: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in _MESSAGE_FLAGS and index + 1 < len(tokens):
            parts.append(tokens[index + 1])
            index += 2
            continue
        if token.startswith(_MESSAGE_FLAG_PREFIXES[1]):
            parts.append(token[len(_MESSAGE_FLAG_PREFIXES[1]) :])
        index += 1
    return _MESSAGE_JOINER.join(parts) if parts else None


def _extract_commit_pathspecs(tokens: list[str]) -> list[str]:
    """Trailing pathspec arguments to ``git commit`` (paths, not flags/values).

    A ``git commit <pathspec>...`` form commits the CURRENT WORKING TREE
    content of exactly those paths, regardless of what is (or isn't)
    staged for them — different semantics from a bare ``git commit``, which
    commits the index. Empty when the invocation has no trailing paths (a
    bare commit, or ``-a``).
    """
    try:
        commit_index = tokens.index(_COMMIT_TOKEN)
    except ValueError:
        return []

    pathspecs: list[str] = []
    seen_separator = False
    index = commit_index + 1
    while index < len(tokens):
        token = tokens[index]
        if not seen_separator and token == _PATHSPEC_SEPARATOR:
            seen_separator = True
            index += 1
            continue
        if not seen_separator and token.startswith("-"):
            flag = token.split("=", 1)[0]
            if flag in _VALUE_FLAGS and "=" not in token:
                index += 2  # skip the flag AND its separate value token
                continue
            index += 1  # boolean flag, or `flag=value` (no separate token)
            continue
        pathspecs.append(token)
        index += 1
    return pathspecs


class PlanQaCommitGateHandler(Handler):
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

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        project_root = ProjectContext.project_root()
        plan_dir_rel = str(self._track_plans_in_project)

        if self._is_foreign_repo(hook_input, project_root):
            return HookResult(decision=Decision.ALLOW, context=[])

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
            return HookResult(
                decision=Decision.ALLOW,
                context=[
                    f"⚠️  PLAN QA: configured plan directory {plan_dir_rel}/ does not exist — "
                    "commit-gate checks skipped. Create it or fix plan_workflow.directory."
                ],
            )

        findings = run_stage(Stage.COMMIT, context)
        if not findings:
            return HookResult(decision=Decision.ALLOW, context=[])

        blockers = [finding for finding in findings if finding.level == Level.BLOCK]
        if blockers and self._plan_qa.commit_gate_mode == _MODE_BLOCK:
            return HookResult(decision=Decision.DENY, reason=format_block_reason(blockers))
        return HookResult(decision=Decision.ALLOW, context=[format_advisory(findings)])

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
