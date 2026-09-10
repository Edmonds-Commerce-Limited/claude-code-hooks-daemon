"""MergeToMainApprovalHandler — a human approves the parent-to-main merge when the project says so.

Plan 00367 Phase 4. The deployed ``Worktree.core.md`` told every agent to
"ask human for approval" before merging a parent worktree into main, eleven
times, and nothing enforced it. The parent-to-main merge now happens once
verification passes; a project that wants a human in that loop sets
``worktree.merge_to_main_requires_human_approval: true`` and gets a REAL
gate: a ``git merge <branch>`` (or ``gh pr merge``) run in the MAIN checkout
while it is on the default branch is denied until a human runs
``hooks-daemon approve-merge <branch>``, a one-shot marker the merge that
follows consumes.

A merge in a linked worktree (child to parent) is never gated: that is the
automatic half of the worktree workflow, and the checkout kind is read from
the ``.git`` entry, never guessed from the path.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.cli_command import (
    daemon_cli_command,
    daemon_cli_command_for_docs,
)
from claude_code_hooks_daemon.utils.command_evasion import (
    GIT_INVOCATION,
    SUBCOMMAND_SEPARATOR_CHARS,
)
from claude_code_hooks_daemon.utils.git_repo import GitRepo, is_linked_worktree
from claude_code_hooks_daemon.utils.git_sync import current_branch, default_branch
from claude_code_hooks_daemon.utils.one_shot_approval import OneShotApprovalStore
from claude_code_hooks_daemon.utils.quoted_spans import blank_shell_literal_spans

_CONFIG_KEY: Final[str] = "worktree.merge_to_main_requires_human_approval"
_APPROVE_SUBCOMMAND: Final[str] = "approve-merge"

#: Directory under the daemon's untracked dir that holds the merge approvals.
APPROVAL_SUBDIR: Final[str] = "merge-approvals"
_STORE: Final[OneShotApprovalStore] = OneShotApprovalStore(APPROVAL_SUBDIR)

# A command segment does not cross a shell sub-command separator, so
# `git merge x && git push` names `x` and nothing from the push.
_SEGMENT: Final[str] = rf"[^{SUBCOMMAND_SEPARATOR_CHARS}]*"
_GIT_MERGE_RE: Final[re.Pattern[str]] = re.compile(
    rf"{GIT_INVOCATION}merge(?=\s|$)({_SEGMENT})",
    re.IGNORECASE,
)
_GH_PR_MERGE_RE: Final[re.Pattern[str]] = re.compile(
    rf"\bgh\s+pr\s+merge(?=\s|$)({_SEGMENT})",
    re.IGNORECASE,
)

#: Merge flags that take a separate value; the value is not the branch.
_VALUED_FLAGS: Final[frozenset[str]] = frozenset(
    {
        "-m",
        "-F",
        "-s",
        "-X",
        "-S",
        "--strategy",
        "--strategy-option",
        "--gpg-sign",
        "--file",
        "--into-name",
        "--cleanup",
        "--log",
        "--subject",
        "--body",
        "-b",
        "-t",
        "--match-head-commit",
    }
)
#: A merge in one of these states is not a merge of a branch at all.
_NON_MERGE_FLAGS: Final[frozenset[str]] = frozenset({"--abort", "--continue", "--quit"})
#: Placeholder key when `gh pr merge` names no PR (it merges the current
#: branch's PR); a human approves it under this name.
_GH_CURRENT_PR: Final[str] = "gh-pr"

_RULE_WHY = (
    "This project requires a human to approve the parent-to-main merge; the "
    "daemon enforces that rather than leaving it to a sentence in a document"
)
_RULE_FIX = (
    "Report the branch as verified and ready to merge, then stop; a human runs "
    "approve-merge <branch>, after which the same merge command goes through"
)
_RULE_VERBOSE = (
    f"`{_CONFIG_KEY}` is true in this project, so a `git merge <branch>` (or "
    "`gh pr merge`) run in the MAIN checkout while it is on the default branch is "
    "denied. A merge in a linked worktree (child into parent) is never gated. A "
    "human approves the merge by running `hooks-daemon approve-merge <branch>`, "
    "which records a one-shot approval under the daemon's untracked directory "
    "that the merge which follows consumes. Do not wait in a loop for it: "
    "finish verification, say the branch is ready to merge, and stop. With the "
    "key false (the default) this handler never fires and the parent-to-main "
    "merge happens once verification passes."
)


def _segment_tokens(segment: str) -> list[str]:
    try:
        return shlex.split(segment)
    except ValueError:
        return segment.split()


def _first_positional(tokens: list[str]) -> str | None:
    skip_value = False
    for token in tokens:
        if skip_value:
            skip_value = False
            continue
        if token in _VALUED_FLAGS:
            skip_value = True
            continue
        if token.startswith("-"):
            continue
        return token
    return None


def merge_target(command: str) -> str | None:
    """The branch (or PR) a merge command would merge, or ``None`` if it is not one.

    ``git merge --abort``/``--continue``/``--quit`` end or resume a merge
    rather than start one; a ``git merge`` with no branch is left to git to
    refuse. Values of flags such as ``-m`` are skipped so a commit message
    can never be read as the branch.

    Matching is scoped to what the shell will EXECUTE: quoted literals are
    blanked first (``utils.quoted_spans.blank_shell_literal_spans``), the same
    idiom ``plan_number_helper`` uses, so ``echo 'git merge x'`` -- which never
    runs a merge -- is not read as one. Blanking preserves string length, so
    the match's span still indexes the ORIGINAL command; the segment is
    re-sliced from there rather than from the blanked copy, which would hand
    a real branch name like ``'feature/x'`` to `shlex` as a run of spaces.
    """
    scannable = blank_shell_literal_spans(command)
    git = _GIT_MERGE_RE.search(scannable)
    if git is not None:
        tokens = _segment_tokens(command[git.start(1) : git.end(1)])
        if any(token in _NON_MERGE_FLAGS for token in tokens):
            return None
        return _first_positional(tokens)
    gh = _GH_PR_MERGE_RE.search(scannable)
    if gh is not None:
        segment = command[gh.start(1) : gh.end(1)]
        return _first_positional(_segment_tokens(segment)) or _GH_CURRENT_PR
    return None


class MergeToMainApprovalHandler(PreToolUseHandlerBase):
    """Deny a merge into the main checkout's default branch while the key is on."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.MERGE_TO_MAIN_APPROVAL,
            priority=Priority.MERGE_TO_MAIN_APPROVAL,
            terminal=True,
            tags=[
                HandlerTag.GIT,
                HandlerTag.WORKFLOW,
                HandlerTag.BLOCKING,
                HandlerTag.TERMINAL,
            ],
        )
        # Injected by the registry for GIT-tagged handlers from `worktree:`.
        self._merge_to_main_requires_human_approval: bool = False
        self._rule = Rule(
            rule_id=RuleID.MERGE_TO_MAIN_APPROVAL,
            blocked=(
                "a `git merge`/`gh pr merge` in the main checkout on the default branch "
                f"while `{_CONFIG_KEY}` is on and no human has approved that branch"
            ),
            why=_RULE_WHY,
            fix=_RULE_FIX,
            verbose=_RULE_VERBOSE,
        )
        self._formatter = RuleFormatter()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        if not self._merge_to_main_requires_human_approval:
            return False
        command = get_bash_command(hook_input)
        if not command or merge_target(command) is None:
            return False
        cwd = hook_input.get(HookInputField.CWD)
        if not cwd:
            return False
        return self._is_main_checkout_on_default_branch(Path(str(cwd)))

    @staticmethod
    def _is_main_checkout_on_default_branch(cwd: Path) -> bool:
        repo = GitRepo.resolve_for(cwd)
        root = repo.root if repo is not None else cwd
        if is_linked_worktree(root):
            return False
        branch = current_branch(cwd)
        if branch is None:
            return False
        return branch == default_branch(cwd)

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        target = merge_target(str(get_bash_command(hook_input)))
        if target is None:
            return GatingResult(decision=Decision.ALLOW, context=[])
        if _STORE.consume(ProjectContext.daemon_untracked_dir(), target):
            return GatingResult(
                decision=Decision.ALLOW,
                context=[
                    f"merge_to_main_approval: a human's one-shot approval for merging "
                    f"`{target}` into main was consumed by this merge."
                ],
            )
        return GatingResult(
            decision=Decision.DENY,
            reason=self._deny_reason(hook_input, target),
        )

    def _deny_reason(self, hook_input: dict[str, Any], target: str) -> str:
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure
        if transcript_path and tracker.was_disclosed(
            transcript_path, RuleID.MERGE_TO_MAIN_APPROVAL
        ):
            prose = self._formatter.terse(self._rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, RuleID.MERGE_TO_MAIN_APPROVAL)
            prose = self._formatter.verbose(self._rule)
        route = (
            f"A human approves merging `{target}` into main by running "
            f"`{daemon_cli_command(_APPROVE_SUBCOMMAND, target)}`; the same merge "
            "command then goes through once."
        )
        return f"{prose}\n\n{route}"

    def get_rules(self) -> list[Rule]:
        return [self._rule]

    def get_claude_md(self) -> str | None:
        return (
            "## merge_to_main_approval — a human approves the parent-to-main merge "
            "when the project says so\n"
            "\n"
            f"`{_CONFIG_KEY}` is OFF by default: the parent worktree is merged into\n"
            "main once verification passes. When a project sets the key to `true`,\n"
            "a `git merge <branch>` (or `gh pr merge`) run in the MAIN checkout while\n"
            "it is on the default branch is DENIED until a human has approved that\n"
            "branch. A merge inside a linked worktree (child into parent) is never\n"
            "gated.\n"
            "\n"
            "**The human's route** (not yours): run\n"
            f"`{daemon_cli_command_for_docs(_APPROVE_SUBCOMMAND, '<branch>')}`, which\n"
            "records a one-shot approval that the merge which follows consumes. When\n"
            "denied, say the branch is verified and ready to merge, and stop — do not\n"
            "poll for the approval.\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="merge-to-main-approval - denies a merge into main while the key is on",
                command=(
                    f"With `{_CONFIG_KEY}: true` in `.claude/hooks-daemon.yaml` (daemon "
                    "restarted) and the main checkout on its default branch, run "
                    "`git merge --no-ff <worktree-branch>` there"
                ),
                harness_cannot_produce=(
                    "The gate is OFF in this project's config and keys on the checkout "
                    "kind and current branch of the shell's cwd, which a scratch payload "
                    "cannot stage; a real run needs a config flip and a restart. Covered by "
                    "tests/unit/handlers/pre_tool_use/test_merge_to_main_approval.py."
                ),
                description=(
                    "A merge into the main checkout's default branch must be denied, "
                    "naming the config key and the approve-merge route."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"merge_to_main_requires_human_approval",
                    r"approve-merge",
                ],
                safety_notes="Deny path — nothing is merged",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="merge-to-main-approval - allows the merge after approve-merge",
                command=(
                    f"With the key on, run `{daemon_cli_command_for_docs(_APPROVE_SUBCOMMAND, '<branch>')}` "
                    "for the branch, then retry the same merge; a second merge of the "
                    "same branch is denied again"
                ),
                harness_cannot_produce=(
                    "Same boundary as its deny sibling: reaching the gate means a "
                    "config flip, a restart and a real merge into main."
                ),
                description="A human's one-shot approval lets exactly one merge through.",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"approval"],
                safety_notes="Consumes the marker; the merge itself is real",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
