"""DocsQaCommitGateHandler — STAGED docs QA gate on git commit (Plan 00284).

On a ``git commit`` Bash command, the STAGED tree is evaluated against the
STAGED-stage docs QA checks (currently ``pointer-resolves`` and
``quote-drift``; ``generated-doc-hand-edit`` deliberately stays EDIT+SWEEP,
see its module docstring). Most doc rot that matters at commit time is
exactly what a single-file edit hook cannot see: a link that resolves
today but points at a file this SAME commit also renames, or a quote
verified against yesterday's source but never re-checked against what is
about to become history.

Rollout is warn-first, mirroring ``plan_qa_commit_gate``:
``commit_gate_mode: warn`` renders findings as advisory context; ``block``
denies with a diffable list. Never fires for a commit inside a repo other
than the project's own (nested repos, foreign worktrees).
"""

import shlex
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.docs_qa.context import staged_context
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy
from claude_code_hooks_daemon.docs_qa.report import format_advisory, format_block_reason
from claude_code_hooks_daemon.docs_qa.runner import run_stage
from claude_code_hooks_daemon.docs_qa.types import CheckStage, Finding, Severity
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command_for_docs
from claude_code_hooks_daemon.utils.git_repo import GitRepo

_MODE_BLOCK: Final[str] = "block"

# Single source of truth for the one rule this handler's DENY path enforces
# (Plan 00116, gate-level granularity: one Rule per GATE, not one per docs QA
# check). The per-check findings from format_block_reason() are dynamic
# content and stay FULLY present in both verbose and terse forms; only the
# surrounding teaching prose about the gate itself goes terse-after-first-fire.
_RULE_WHY = (
    "Most doc rot that matters at commit time is cross-file drift a single-file "
    "edit hook cannot see"
)
_RULE_FIX = "Fix the content per each finding's remediation below and amend the commit"
_RULE_VERBOSE = (
    "Every `git commit` is checked against the STAGED tree's docs QA "
    "invariants (currently `pointer-resolves` and `quote-drift`). Each "
    "finding below names its own remediation -- fix the content accordingly "
    "and amend the commit. Commits inside nested/vendor repos or foreign "
    "worktrees are exempt."
)

_GIT_TOKEN: Final[str] = "git"
_COMMIT_TOKEN: Final[str] = "commit"
_FIELD_COMMAND: Final[str] = "command"
_CWD_FIELD: Final[str] = "cwd"

_MESSAGE_FLAGS: Final[frozenset[str]] = frozenset({"-m", "--message"})
_MESSAGE_FLAG_PREFIXES: Final[tuple[str, ...]] = ("-m", "--message=")
_MESSAGE_JOINER: Final[str] = "\n\n"

# git-commit flags that take a SEPARATE value token (not a pathspec) — see
# plan_qa_commit_gate's identical table for the rationale.
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
    """True when a ``commit`` token follows a ``git`` token."""
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
    """Trailing pathspec arguments to ``git commit`` (paths, not flags/values)."""
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


class DocsQaCommitGateHandler(PreToolUseHandlerBase):
    """Warn-first STAGED docs QA gate on git commit."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.DOCS_QA_COMMIT_GATE,
            priority=Priority.DOCS_QA_COMMIT_GATE,
            terminal=False,
            tags=[
                HandlerTag.DOCUMENTATION,
                HandlerTag.VALIDATION,
                HandlerTag.GIT,
            ],
        )
        # Injected by the registry for DOCUMENTATION-tagged handlers.
        self._documentation: DocumentationPolicy | None = None
        self._rule = Rule(
            rule_id=RuleID.DOCS_QA_COMMIT,
            blocked="a git commit violates a block-level docs QA staged-tree check",
            why=_RULE_WHY,
            fix=_RULE_FIX,
            verbose=_RULE_VERBOSE,
        )
        self._formatter = RuleFormatter()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.BASH:
            return False
        policy = self._documentation
        if policy is None or not policy.enabled:
            return False
        command = hook_input.get(HookInputField.TOOL_INPUT, {}).get(_FIELD_COMMAND, "")
        return _is_git_commit(_tokenise(command))

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        project_root = ProjectContext.project_root()
        policy = self._documentation
        assert policy is not None  # matches() only returns True when this is set

        if self._is_foreign_repo(hook_input, project_root):
            return GatingResult(decision=Decision.ALLOW, context=[])

        command = hook_input.get(HookInputField.TOOL_INPUT, {}).get(_FIELD_COMMAND, "")
        tokens = _tokenise(command)
        context = staged_context(
            project_root=project_root,
            policy=policy,
            commit_message=_extract_commit_message(tokens),
            pathspecs=_extract_commit_pathspecs(tokens),
        )

        findings = run_stage(CheckStage.STAGED, context)
        if not findings:
            return GatingResult(decision=Decision.ALLOW, context=[])

        blockers = [
            finding
            for finding in findings
            if finding.severity == Severity.BLOCK
            and policy.qa.check_modes.get(finding.check_id, policy.qa.commit_gate_mode)
            == _MODE_BLOCK
        ]
        if blockers:
            return GatingResult(
                decision=Decision.DENY,
                reason=self._blocking_message(blockers, hook_input),
            )
        return GatingResult(decision=Decision.ALLOW, context=[format_advisory(findings)])

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's block-mode denial."""
        return [self._rule]

    def _blocking_message(self, blockers: list[Finding], hook_input: dict[str, Any]) -> str:
        """Build the block-mode deny message: verbose-first/terse-after teaching
        prose (Plan 00116, Decision G), with the per-check findings from
        ``format_block_reason`` ALWAYS fully present -- they are dynamic
        content, not the static teaching text the disclosure ladder governs.
        """
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure

        if transcript_path and tracker.was_disclosed(transcript_path, RuleID.DOCS_QA_COMMIT):
            prose = self._formatter.terse(self._rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, RuleID.DOCS_QA_COMMIT)
            prose = self._formatter.verbose(self._rule)

        return f"{prose}\n\n{format_block_reason(blockers)}"

    @staticmethod
    def _is_foreign_repo(hook_input: dict[str, Any], project_root: Path) -> bool:
        """True when the command runs inside a repo other than the project's."""
        cwd_raw = hook_input.get(_CWD_FIELD)
        if not cwd_raw:
            return False
        repo = GitRepo.resolve_for(Path(cwd_raw))
        return repo is not None and repo.root != project_root

    def get_claude_md(self) -> str | None:
        return (
            "## docs_qa_commit_gate — STAGED docs checks at git commit\n"
            "\n"
            "Every `git commit` is checked against the STAGED tree's docs QA\n"
            "invariants: `pointer-resolves` (a new dead link in a staged\n"
            "documentation file) and `quote-drift` (a staged `ssot-quote` block\n"
            "that no longer verifies against its source). In\n"
            "`commit_gate_mode: warn` (the rollout default) violations appear\n"
            "as advisory context — read them and amend the commit content\n"
            "BEFORE committing; in `block` mode they deny the commit with the\n"
            "exact remediation.\n"
            "\n"
            "**Advisory only, never block, cross-file by nature**:\n"
            "`rules-file-orphan-shrink` — a staged `.claude/rules/*.md` shrink\n"
            "with no staged growth anywhere in the canonical agent tree (R7a's\n"
            "promote-then-thin transition rule, mechanically approximated: a\n"
            "false positive is expected when the promotion happened in an\n"
            "earlier commit or the content was genuinely obsolete).\n"
            "`plan-promotion-disposition` — a staged terminal-status flip of a\n"
            "`PLAN.md` whose folder has supporting docs, where the staged\n"
            "closing journal entry mentions none of PROMOTE/HISTORICAL/DELETE\n"
            "(R8; a plain keyword scan — false negatives are expected).\n"
            "\n"
            "`generated-doc-hand-edit` deliberately has no STAGED half — EDIT\n"
            "catches a hand-edit the moment it happens and SWEEP catches\n"
            "anything already on disk at the next session start, so a\n"
            "commit-time check would only ever restate one of those two.\n"
            "\n"
            "Check the staged tree any time without committing:\n"
            f"`{daemon_cli_command_for_docs('docs-qa', '--check-staged')}`.\n"
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
                title="docs-qa commit gate - warns on a new dead link in a staged doc",
                command=(
                    "Stage a new/edited .md file under CLAUDE/ containing a plain "
                    "markdown link to a file that does not exist, then run "
                    "`git commit` on it"
                ),
                description=(
                    "In warn mode the commit proceeds but the PostToolUse context "
                    "contains a pointer-resolves finding naming the dead link."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"pointer-resolves|Docs QA"],
                safety_notes="Warn mode — commit is not blocked; revert the test commit after",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
