"""GitStashHandler - blocks or warns about git stash based on configuration."""

import re
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.command_evasion import GIT_INVOCATION, remove_word_quoting
from claude_code_hooks_daemon.utils.command_position import command_position_segments

# Shared teaching content for the (only) deny path — preserves the deny-mode
# block message verbatim (Plan 00116, Task 3.2).
_RULE_VERBOSE = (
    "Stashes get forgotten, lost, and block git pull. "
    "Use git commit instead — WIP commits are fine.\n\n"
    "DO THIS INSTEAD:\n"
    "  git commit -m 'WIP: description'\n"
    "  git pull --rebase\n\n"
    "ESCAPE HATCH (if you truly must stash):\n"
    '  MUST_STASH_BECAUSE="explain why commit won\'t work"; '
    "git stash"
)

# Git accepts GLOBAL OPTIONS before the subcommand, so `git -C /path stash`
# bypassed this handler entirely until every pattern below was widened.
#
# The ALLOW-list is widened for the opposite reason: it must keep pace with the
# block pattern or it stops protecting the safe operations. If only the block
# pattern tolerated global options, `git -C /path stash pop` would match "is a
# stash command" while failing to match "is a recovery operation" — turning a
# bypass into a false positive on the one form that RECOVERS work.

# Escape hatch: MUST_STASH_BECAUSE="non-empty reason" before git stash
# Requires a non-empty quoted reason to pass through.
_ESCAPE_HATCH_PATTERN = re.compile(
    r"""MUST_STASH_BECAUSE=["']([^"']+)["']""",
    re.IGNORECASE,
)

# Recovery/query operations are allowed unconditionally: pop, apply, list, show
# retrieve stashed work. drop/clear are blocked by DestructiveGitHandler.
_RECOVERY_PATTERN = re.compile(GIT_INVOCATION + r"stash\s+(?:pop|apply|list|show)", re.IGNORECASE)
_CREATION_PATTERN = re.compile(
    GIT_INVOCATION + r"stash(?:\s+(?:push|save))?(?=\W|$)", re.IGNORECASE
)


def _creates_a_stash(segment: str) -> bool:
    """Whether ONE command segment is a `git stash` that creates a stash."""
    words = remove_word_quoting(segment)
    if _RECOVERY_PATTERN.search(words):
        return False
    return _CREATION_PATTERN.search(words) is not None


class GitStashHandler(PreToolUseHandlerBase):
    """Block or warn about git stash based on mode configuration.

    Modes:
        - "deny": Hard block unless escape hatch used (default)
        - "warn": Allow with advisory warnings

    Escape hatch (deny mode only):
        MUST_STASH_BECAUSE="reason"; git stash
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.GIT_STASH,
            priority=Priority.GIT_STASH,
            # NOT terminal: `mode: warn` returns ALLOW, and the chain breaks
            # on ANY terminal match whatever it decided, so a terminal ALLOW
            # here would end dispatch at priority 19 and silently disable
            # every higher-numbered handler for that command. A non-terminal
            # deny still denies -- core/chain.py keeps the most restrictive
            # decision seen (the Plan 00144 regression).
            terminal=False,
            tags=[HandlerTag.SAFETY, HandlerTag.GIT, HandlerTag.BLOCKING],
        )
        self._mode = "deny"
        self._rule = Rule(
            rule_id=RuleID.GIT_STASH_PUSH,
            blocked="`git stash` / `git stash push` / `git stash save`",
            why="Stashes get forgotten, lost, and block git pull",
            fix="Use git commit instead — WIP commits are fine",
            verbose=_RULE_VERBOSE,
        )
        self._formatter = RuleFormatter()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is a git stash creation command without escape hatch."""
        command = get_bash_command(hook_input)
        if not command:
            return False

        # Only text in COMMAND position is judged (ledger N241): a commit
        # message, a `grep` pattern or an `echo` argument that names `git
        # stash` is prose, while a literal `bash -c 'git stash'` body is a
        # command. This supersedes Plan 00228 Decision 2, which kept quoted
        # text matched so the acceptance suite could embed a command in an
        # `echo`; the owner's threat-model ruling (CLAUDE/ARCHITECTURE.md)
        # makes a false positive on ordinary work a defect.
        #
        # Each command segment is judged on its own (ledger N200): a recovery
        # form in one segment must not exempt a stash in another. In-word
        # quoting is removed per segment because bash removes it: `git
        # "stash"` stashes, and `git stash 'pop'` recovers (Plan 00408 Task
        # 3.0's sibling sweep). The escape hatch reads the raw command, since
        # its quotes are what delimit the reason.
        if not any(_creates_a_stash(segment) for segment in command_position_segments(command)):
            return False

        # Escape hatch: MUST_STASH_BECAUSE="non-empty reason" bypasses block
        if _ESCAPE_HATCH_PATTERN.search(command):
            return False

        return True

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's deny path."""
        return [self._rule]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Block or warn about git stash based on mode configuration."""
        mode = getattr(self, "_mode", "deny")

        if mode == "deny":
            transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
            tracker = get_data_layer().disclosure

            if transcript_path and tracker.was_disclosed(transcript_path, self._rule.rule_id):
                message = self._formatter.terse(self._rule)
            else:
                if transcript_path:
                    tracker.mark_disclosed(transcript_path, self._rule.rule_id)
                message = self._formatter.verbose(self._rule)

            return GatingResult(decision=Decision.DENY, reason=message)
        else:
            return GatingResult(
                decision=Decision.ALLOW,
                context=[
                    "WARNING: git stash detected",
                    "Stashes can be lost, forgotten, or accidentally dropped",
                    "Consider safer alternatives like git commit or git worktree",
                ],
                guidance=(
                    "WARNING: git stash is risky\n\n"
                    "Stashes get forgotten, lost, and block git pull. "
                    "Use git commit instead — WIP commits are fine.\n\n"
                    "DO THIS INSTEAD:\n"
                    "  git commit -m 'WIP: description'\n"
                    "  git pull --rebase"
                ),
            )

    def get_claude_md(self) -> str | None:
        return (
            "## git_stash — git stash is blocked by default\n\n"
            "`git stash`, `git stash push`, and `git stash save` are blocked. "
            "`git stash pop`, `git stash apply`, `git stash list`, and `git stash show` "
            "are always allowed.\n\n"
            "**Why**: stashes get forgotten, lost, and block `git pull`. "
            "Use `git commit -m 'WIP: ...'` instead — WIP commits are acceptable.\n\n"
            "**Escape hatch** (when commit truly won't work):\n"
            "```\n"
            'MUST_STASH_BECAUSE="explain why"; git stash\n'
            "```\n\n"
            "Configure via `handlers.pre_tool_use.git_stash.options.mode: warn` "
            "for advisory-only mode."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for git stash handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        mode = getattr(self, "_mode", "deny")

        if mode == "deny":
            return [
                AcceptanceTest(
                    title="git stash blocked",
                    command="bash -n -c 'git stash'",
                    dispatch_as_bash=True,
                    description="Blocks git stash — use git commit instead",
                    expected_decision=Decision.DENY,
                    expected_message_patterns=[
                        r"BLOCKED",
                        r"git commit",
                    ],
                    safety_notes="Runs under bash -n -c, which only parses the command and never executes it",
                    test_type=TestType.BLOCKING,
                    recommended_model=RecommendedModel.HAIKU,
                    requires_main_thread=False,
                ),
                AcceptanceTest(
                    title="git stash push blocked",
                    command='bash -n -c "git stash push -m temp-changes"',
                    dispatch_as_bash=True,
                    description="Blocks git stash push — use git commit instead",
                    expected_decision=Decision.DENY,
                    expected_message_patterns=[
                        r"BLOCKED",
                        r"MUST_STASH_BECAUSE",
                    ],
                    safety_notes="Runs under bash -n -c, which only parses the command and never executes it",
                    test_type=TestType.BLOCKING,
                    recommended_model=RecommendedModel.HAIKU,
                    requires_main_thread=False,
                ),
            ]
        else:
            return [
                AcceptanceTest(
                    title="git stash (warn mode)",
                    command="bash -n -c 'git stash'",
                    description="Allows git stash with advisory warning",
                    expected_decision=Decision.ALLOW,
                    expected_message_patterns=[
                        r"WARNING",
                        r"git commit",
                    ],
                    safety_notes="Runs under bash -n -c, which only parses the command and never executes it",
                    test_type=TestType.ADVISORY,
                    recommended_model=RecommendedModel.SONNET,
                    requires_main_thread=False,
                ),
                AcceptanceTest(
                    title="git stash push (warn mode)",
                    command='bash -n -c "git stash push -m temp-changes"',
                    description="Allows git stash push with advisory warning",
                    expected_decision=Decision.ALLOW,
                    expected_message_patterns=[
                        r"WARNING",
                        r"git commit",
                    ],
                    safety_notes="Runs under bash -n -c, which only parses the command and never executes it",
                    test_type=TestType.ADVISORY,
                    recommended_model=RecommendedModel.SONNET,
                    requires_main_thread=False,
                ),
            ]
