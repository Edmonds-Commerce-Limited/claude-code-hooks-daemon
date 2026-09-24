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

import logging
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
from claude_code_hooks_daemon.utils.shell_segmentation import strip_inert_spans

logger = logging.getLogger(__name__)

_CONFIG_KEY: Final[str] = "worktree.merge_to_main_requires_human_approval"
_APPROVE_SUBCOMMAND: Final[str] = "approve-merge"

#: Directory under the daemon's untracked dir that holds the merge approvals.
APPROVAL_SUBDIR: Final[str] = "merge-approvals"
_STORE: Final[OneShotApprovalStore] = OneShotApprovalStore(APPROVAL_SUBDIR)

# A command segment does not cross a shell sub-command separator, so
# `git merge x && git push` names `x` and nothing from the push. The separator
# set includes the newline (Plan 00406), so the two-line spelling of that pair
# names `x` as well — this handler captures a merge TARGET rather than denying
# on a flag, so the omission mis-named a branch here rather than inventing a
# violation, but one boundary set serves all three consumers.
_SEGMENT: Final[str] = rf"[^{SUBCOMMAND_SEPARATOR_CHARS}]*"
_GIT_MERGE_RE: Final[re.Pattern[str]] = re.compile(
    rf"{GIT_INVOCATION}merge(?=\s|$)({_SEGMENT})",
    re.IGNORECASE,
)
_GH_PR_MERGE_RE: Final[re.Pattern[str]] = re.compile(
    rf"\bgh\s+pr\s+merge(?=\s|$)({_SEGMENT})",
    re.IGNORECASE,
)
# `git pull <repository> <refspec>` merges that refspec into the checked-out
# branch, so `git pull . feature/x` is a merge of `feature/x` (Plan 00408 Task
# 3.7). A pull naming no refspec updates from the configured upstream instead,
# which is not a merge of anybody's work and is left alone.
_GIT_PULL_RE: Final[re.Pattern[str]] = re.compile(
    rf"{GIT_INVOCATION}pull(?=\s|$)({_SEGMENT})",
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
#: `git pull` flags that take a separate value; the value is not a positional.
_PULL_VALUED_FLAGS: Final[frozenset[str]] = frozenset(
    {
        "-s",
        "-X",
        "-S",
        "-j",
        "-o",
        "--strategy",
        "--strategy-option",
        "--gpg-sign",
        "--jobs",
        "--depth",
        "--deepen",
        "--shallow-since",
        "--shallow-exclude",
        "--upload-pack",
        "--server-option",
        "--negotiation-tip",
        "--refmap",
        "--cleanup",
    }
)
#: A merge in one of these states is not a merge of a branch at all.
_NON_MERGE_FLAGS: Final[frozenset[str]] = frozenset({"--abort", "--continue", "--quit"})
#: Placeholder key when `gh pr merge` names no PR (it merges the current
#: branch's PR); a human approves it under this name.
_GH_CURRENT_PR: Final[str] = "gh-pr"
#: Placeholder key when `git merge` names no branch in the command text: the
#: branch arrives on stdin (`... | xargs git merge`) or git merges the
#: configured upstream. Either way it IS a merge, so it is gated under this name
#: rather than answered "not a merge" (Plan 00408 Task 3.7).
UNNAMED_MERGE_TARGET: Final[str] = "unnamed-branch"
#: A pull needs a repository AND a refspec before it names a branch to merge.
_PULL_POSITIONALS_NAMING_A_BRANCH: Final[int] = 2

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


def _shlex_tokens(text: str) -> list[str] | None:
    """Shell-tokenise ``text``, or ``None`` when its quoting is unbalanced.

    ``None`` is an ANSWER rather than a swallowed failure: unbalanced quoting is
    an expected input here (see ``_segment_tokens``), and the caller acts on it
    by trying the next strategy.
    """
    tokens: list[str] | None = None
    try:
        tokens = shlex.split(text)
    except ValueError as exc:
        logger.debug("Merge segment is not balanced shell quoting (%s): %r", exc, text)
        tokens = None
    return tokens


def _segment_tokens(segment: str) -> list[str]:
    """Tokenise a matched merge segment into words, quoting removed.

    Unbalanced quoting is ORDINARY here rather than malformed input: a merge
    inside ``bash -c "git merge x"`` is matched INSIDE the enclosing literal, so
    the slice carries that literal's closing quote and no opener. Balancing the
    SEGMENT and re-tokenising is what keeps the branch NAME right.

    Splitting on whitespace instead is what the first fix did, and it was wrong
    in a way that mattered: a multi-word ``-m`` message became several tokens,
    ``_first_positional`` skips exactly ONE token after a valued flag, and the
    branch came back as the message's SECOND WORD. So
    ``git merge -m 'merge plan 00407' worktree-plan-00407`` reported ``plan`` —
    and so did ``git merge -m 'another plan here' some/other-branch``. Two
    unrelated merges sharing one approval key means the one-shot approval a
    human granted for the first is consumed by the second (Plan 00407 N12
    review).
    """
    tokens = _shlex_tokens(segment)
    if tokens is not None:
        return tokens

    trimmed = segment.rstrip()
    if trimmed[-1:] in ('"', "'"):
        balanced = _shlex_tokens(trimmed[:-1])
        if balanced is not None:
            return balanced

    # Still untokenisable. Split on whitespace so the merge is at least still
    # DETECTED: naming the wrong branch denies THIS merge, whereas returning
    # nothing would make `merge_target` answer None and stand the gate down
    # altogether — the one outcome worse than a wrong name.
    return [token.strip("\"'") for token in segment.split()]


def _positionals(tokens: list[str], valued_flags: frozenset[str]) -> list[str]:
    """The non-option words, skipping the value of each flag that takes one."""
    positionals: list[str] = []
    skip_value = False
    for token in tokens:
        if skip_value:
            skip_value = False
            continue
        if token in valued_flags:
            skip_value = True
            continue
        if token.startswith("-"):
            continue
        positionals.append(token)
    return positionals


def _first_positional(tokens: list[str]) -> str | None:
    positionals = _positionals(tokens, _VALUED_FLAGS)
    return positionals[0] if positionals else None


def _pulled_branch(tokens: list[str]) -> str | None:
    """The branch a ``git pull <repository> <refspec>`` merges, else ``None``.

    The refspec's SOURCE side is the branch merged: ``+feature/x:feature/x``
    merges ``feature/x``.
    """
    positionals = _positionals(tokens, _PULL_VALUED_FLAGS)
    if len(positionals) < _PULL_POSITIONALS_NAMING_A_BRANCH:
        return None
    source = positionals[1].removeprefix("+").split(":", 1)[0]
    return source or None


def merge_target(command: str) -> str | None:
    """The branch (or PR) a merge command would merge, or ``None`` if it is not one.

    ``git merge --abort``/``--continue``/``--quit`` end or resume a merge
    rather than start one. A ``git merge`` naming no branch is still a merge --
    of stdin's branch under ``xargs``, or of the upstream -- and answers
    :data:`UNNAMED_MERGE_TARGET`; a ``git pull`` is a merge only when it names
    a refspec. Values of flags such as ``-m`` are skipped so a commit message
    can never be read as the branch.

    Matching is scoped to what the shell will EXECUTE by a single pass,
    ``strip_inert_spans``: it removes a ``-m`` message body, and a ``<<'EOF'``
    body that nothing on its line can EXECUTE. A merge named in either is
    prose.

    That qualifier is load-bearing and was missing here, which is how
    ``bash <<'EOF'`` reached this gate unjudged in v3.64.0: this docstring
    asserted a heredoc body is handed to the receiving command verbatim and
    therefore prose, which is true of ``git commit -F -`` and false of
    ``bash``. "Nothing can execute it" is three questions, not one — the
    receiver, every stage it is piped on to, and whether the whole thing sits
    in a command substitution (Plan 00409). Without it, the repository's own
    canonical commit
    idiom (``git commit -m "$(cat <<'EOF' ... EOF)"``) was read as a real merge
    and denied with a remediation about a command nobody ran. This is the Plan
    00377 N7 class that ``destructive_git._scan_target`` fixed for itself; the
    sibling needed it too (Plan 00407 N2).

    A second pass blanking every quoted literal was tried and REMOVED, which is
    a correction worth stating so it is not re-added (Plan 00407 N12). It was
    there so ``echo 'git merge x'`` would not read as a merge — but a quoted
    literal can itself BE a command, because the shell executes the argument of
    ``bash -c "git merge x"``. Blanking it therefore hid a real merge from an
    approval gate, and the gate could be walked past by quoting. Blanking
    literals answers "what is this command's TARGET?"; it cannot answer "is
    there a command here at all?".

    What that costs is stated in full rather than as ``echo 'git merge x'``
    alone, so the trade-off a future reader re-litigates is the one made: a
    ``grep``/``rg`` FOR a merge command matches, as do ``git commit -am 'x'``,
    ``-m"x"`` and ``-m'x'`` (spellings ``_MESSAGE_BODY_PATTERN`` does not
    recognise as message flags) and ``gh ... --body 'x'``. It is the safe
    direction for a gate, and it bites only where the key is switched on.
    Telling an inert ``echo`` apart from ``bash -c`` needs an allowlist of
    commands that do not execute their argument, and recognising those flag
    spellings is a separate widening — both are Plan 00408, and neither is
    re-adding literal blanking, which is what let ``bash -c`` through.

    Because one copy is both matched and re-sliced, offsets need no
    reconciliation — the earlier two-pass form had to re-slice from the
    heredoc-stripped copy rather than the blanked one, and that hazard is gone.
    """
    executable = strip_inert_spans(command)
    git = _GIT_MERGE_RE.search(executable)
    if git is not None:
        tokens = _segment_tokens(executable[git.start(1) : git.end(1)])
        if any(token in _NON_MERGE_FLAGS for token in tokens):
            return None
        return _first_positional(tokens) or UNNAMED_MERGE_TARGET
    gh = _GH_PR_MERGE_RE.search(executable)
    if gh is not None:
        segment = executable[gh.start(1) : gh.end(1)]
        return _first_positional(_segment_tokens(segment)) or _GH_CURRENT_PR
    pull = _GIT_PULL_RE.search(executable)
    if pull is not None:
        return _pulled_branch(_segment_tokens(executable[pull.start(1) : pull.end(1)]))
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
                "a `git merge`/`git pull <remote> <branch>`/`gh pr merge` in the main "
                "checkout on the default branch "
                f"while `{_CONFIG_KEY}` is on and no human has approved that branch"
            ),
            why=_RULE_WHY,
            fix=_RULE_FIX,
            verbose=_RULE_VERBOSE,
        )
        self._formatter = RuleFormatter()

    def is_dormant(self) -> bool:
        """Whether config leaves this handler unable to fire (Plan 00390 N2).

        Mirrors ``matches()``'s first line so the CLAUDE.md generator can omit
        a gate the project has switched off, rather than announcing its rule
        under headings that promise enforcement.
        """
        return not self._merge_to_main_requires_human_approval

    def matches(self, hook_input: dict[str, Any]) -> bool:
        if not self._merge_to_main_requires_human_approval:
            return False
        command = get_bash_command(hook_input)
        target = merge_target(command) if command else None
        if target is None:
            return False
        cwd = hook_input.get(HookInputField.CWD)
        if not cwd:
            return False
        return self._merges_into_main_checkout_default_branch(Path(str(cwd)), target)

    @staticmethod
    def _merges_into_main_checkout_default_branch(cwd: Path, target: str) -> bool:
        """Whether ``target`` would land on the main checkout's default branch.

        Merging the default branch into itself -- ``git pull origin main`` on
        ``main``, the ordinary update -- brings in nobody's work, so there is
        nothing for a human to approve.
        """
        repo = GitRepo.resolve_for(cwd)
        root = repo.root if repo is not None else cwd
        if is_linked_worktree(root):
            return False
        branch = current_branch(cwd)
        if branch is None:
            return False
        default = default_branch(cwd)
        return branch == default and target != default

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
            "gated. `git pull <remote> <branch>` merges that branch and is gated the\n"
            "same way; a pull naming no branch, or naming the default branch itself,\n"
            "is an ordinary update and is not. A `git merge` whose branch is not in\n"
            f"the command (`... | xargs git merge`) is gated as `{UNNAMED_MERGE_TARGET}`.\n"
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
