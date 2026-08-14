"""AncestryPreservingMergeHandler - blocks ancestry-severing merge integrations.

A squash merge collapses N commits into one new commit on the target, and a
GitHub "rebase and merge" replays them as new commits with new shas. In both
cases the branch's original commits never become ancestors of the target, so
`git branch -d` -- the safe, battle-tested delete -- refuses the branch
permanently, even though its content is fully upstream (Plan 00207).

Only a `--no-ff` merge commit preserves ancestry. This handler blocks the
three ancestry-severing spellings that can fire from a Bash tool call:
`git merge --squash`, `gh pr merge --squash` and `gh pr merge --rebase`. It
cannot see a squash/rebase merge performed through the GitHub web UI -- the
daemon only sees tool calls, not browser clicks.
"""

from __future__ import annotations

import re
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.command_evasion import (
    GIT_INVOCATION,
    SUBCOMMAND_SEPARATOR_CHARS,
)

# Mode values (mirrors git_stash's mode option, Plan 00207 Task 1.2).
_MODE_BLOCK = "block"
_MODE_WARN = "warn"

# Escape hatch: MUST_SQUASH_BECAUSE="non-empty reason" before the command.
# Covers BOTH ancestry-severing spellings this handler blocks (squash and
# rebase-merge) -- Plan 00207 Task 1.2 names this one hatch for both.
_ESCAPE_HATCH_PATTERN = re.compile(
    r"""MUST_SQUASH_BECAUSE=["']([^"']+)["']""",
    re.IGNORECASE,
)

# A command segment does not cross a shell sub-command separator, matching the
# scoping already used by destructive_git's force-push pattern and
# gh_pr_comments' segment extraction -- so `git merge --squash x; git commit
# -m "not a squash flag"` cannot leak a match across commands.
_SEGMENT = rf"[^{SUBCOMMAND_SEPARATOR_CHARS}]*?"

# git merge --squash, either flag position: `git merge --squash x` or
# `git merge x --squash`. GIT_INVOCATION absorbs global options (`git -C
# <path> merge --squash`) and get_bash_command() already normalises line
# continuations, so both Plan 00202 evasion spellings are covered for free.
_GIT_MERGE_SQUASH_PATTERN = re.compile(
    rf"{GIT_INVOCATION}merge\b{_SEGMENT}--squash\b",
    re.IGNORECASE,
)

# gh pr merge --squash / --rebase. `gh` is not hardened against global options
# here (Plan 00207 scope; matches the existing gh_issue_comments/gh_pr_comments
# precedent) -- \b already matches "gh" inside a path-qualified binary like
# /usr/bin/gh, which is the evasion vector those siblings actually cover.
_GH_PR_MERGE_SQUASH_PATTERN = re.compile(
    rf"\bgh\s+pr\s+merge\b{_SEGMENT}--squash\b",
    re.IGNORECASE,
)
_GH_PR_MERGE_REBASE_PATTERN = re.compile(
    rf"\bgh\s+pr\s+merge\b{_SEGMENT}--rebase\b",
    re.IGNORECASE,
)

# SINGLE SOURCE OF TRUTH: ordered (pattern, command-label) pairs consumed by
# BOTH matches() and handle(), exactly mirroring destructive_git's
# _DESTRUCTIVE_PATTERN_REASONS. handle() reports the label of the FIRST
# matching pattern so the two methods can never drift apart.
_ANCESTRY_SEVERING_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (_GIT_MERGE_SQUASH_PATTERN, "git merge --squash"),
    (_GH_PR_MERGE_SQUASH_PATTERN, "gh pr merge --squash"),
    (_GH_PR_MERGE_REBASE_PATTERN, "gh pr merge --rebase"),
)

_WARN_GUIDANCE_HEADER = "WARNING: ancestry-severing merge detected"


class AncestryPreservingMergeHandler(Handler):
    """Block (or, in warn mode, advise against) ancestry-severing merges.

    Modes:
        - "block" (default): hard-block unless the escape hatch is used
        - "warn": allow with an advisory warning

    Escape hatch (block mode only):
        MUST_SQUASH_BECAUSE="reason"; git merge --squash <branch>
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.ANCESTRY_PRESERVING_MERGE,
            priority=Priority.ANCESTRY_PRESERVING_MERGE,
            # NOT terminal: `mode: warn` returns ALLOW, and the chain breaks
            # on ANY terminal match whatever it decided, so a terminal ALLOW
            # here would end dispatch at priority 19 and silently disable
            # every higher-numbered handler for that command. A non-terminal
            # deny still denies -- core/chain.py keeps the most restrictive
            # decision seen (the Plan 00144 regression).
            terminal=False,
            tags=[
                HandlerTag.SAFETY,
                HandlerTag.GIT,
                HandlerTag.GITHUB,
                HandlerTag.BLOCKING,
            ],
        )
        self._mode = _MODE_BLOCK

    def _match_label(self, command: str) -> str | None:
        """Return the label of the first matching ancestry-severing pattern."""
        for pattern, label in _ANCESTRY_SEVERING_PATTERNS:
            if pattern.search(command):
                return label
        return None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is an ancestry-severing merge command without the escape hatch."""
        command = get_bash_command(hook_input)
        if not command:
            return False

        if self._match_label(command) is None:
            return False

        # Escape hatch: MUST_SQUASH_BECAUSE="non-empty reason" bypasses the block.
        if _ESCAPE_HATCH_PATTERN.search(command):
            return False

        return True

    def _block_reason(self, label: str) -> str:
        return (
            f"BLOCKED: {label} severs ancestry\n\n"
            "WHY THIS MATTERS:\n"
            "A squash merge collapses every commit into one new commit on the "
            "target, and a rebase merge replays them as new commits with new "
            "shas. Either way, this branch's commits never become ancestors of "
            "the target -- so git branch -d (the safe, battle-tested delete) "
            "will refuse this branch FOREVER, even though its content is fully "
            "upstream. Only a --no-ff merge commit preserves ancestry.\n\n"
            "USE INSTEAD:\n"
            "  git merge --no-ff <branch>      (merge commit, preserves ancestry)\n"
            "  gh pr merge --merge <number>    (GitHub equivalent of --no-ff)\n\n"
            "A LOCAL git rebase (e.g. `git rebase main` on your feature branch "
            "before merging) is fine and stays allowed -- it is the REBASE MERGE "
            "integration button that severs ancestry, not local rebasing.\n\n"
            "ESCAPE HATCH (if your platform mandates squash-only or rebase-only "
            "merging):\n"
            '  MUST_SQUASH_BECAUSE="explain why"; git merge --squash <branch>'
        )

    def _warn_guidance(self, label: str) -> str:
        return (
            f"{_WARN_GUIDANCE_HEADER}\n\n"
            f"{label} means this branch's commits never become ancestors of the "
            "target, so git branch -d will refuse this branch forever even "
            "though its content is fully upstream.\n\n"
            "DO THIS INSTEAD:\n"
            "  git merge --no-ff <branch>\n"
            "  gh pr merge --merge <number>"
        )

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block or warn about the ancestry-severing merge, based on mode."""
        command = get_bash_command(hook_input)
        if not command:
            return HookResult(decision=Decision.ALLOW)

        label = self._match_label(command) or "ancestry-severing merge"
        mode = getattr(self, "_mode", _MODE_BLOCK)

        if mode == _MODE_WARN:
            return HookResult(
                decision=Decision.ALLOW,
                context=[
                    _WARN_GUIDANCE_HEADER,
                    f"{label} severs ancestry -- git branch -d will refuse this " "branch forever",
                    "Consider git merge --no-ff / gh pr merge --merge instead",
                ],
                guidance=self._warn_guidance(label),
            )

        return HookResult(decision=Decision.DENY, reason=self._block_reason(label))

    def get_claude_md(self) -> str | None:
        return (
            "## ancestry_preserving_merge — ancestry-severing merges are blocked "
            "by default\n\n"
            "`git merge --squash`, `gh pr merge --squash` and `gh pr merge "
            "--rebase` are blocked. A squash merge collapses every commit into "
            "one new commit on the target; a rebase merge replays them with new "
            "shas. Either way this branch's commits never become **ancestors** "
            "of the target, so `git branch -d` (the safe, battle-tested delete) "
            "refuses the branch FOREVER, even though its content is fully "
            "upstream. This is about the ancestry consequence, not a style "
            "opinion on squashing or rebasing.\n\n"
            "**Always allowed**: `git merge`, `git merge --no-ff`, `gh pr merge "
            "--merge`, and a LOCAL `git rebase <branch>` on your own feature "
            "branch before merging -- that preserves ancestry once merged with "
            "`--no-ff`. It is the REBASE MERGE *integration button* that severs "
            "ancestry, not local rebasing.\n\n"
            "**Use instead**:\n"
            "```\n"
            "git merge --no-ff <branch>      # merge commit, preserves ancestry\n"
            "gh pr merge --merge <number>    # GitHub equivalent of --no-ff\n"
            "```\n\n"
            "**Escape hatch** (when your platform genuinely mandates squash-only "
            "or rebase-only merging):\n"
            "```\n"
            'MUST_SQUASH_BECAUSE="explain why"; git merge --squash <branch>\n'
            "```\n\n"
            "**Not covered**: a squash or rebase merge performed through the "
            "GitHub web UI. The daemon sees tool calls, not browser clicks, so "
            "this handler has no visibility into a merge button pressed in a "
            "browser.\n\n"
            "Configure via `handlers.pre_tool_use.ancestry_preserving_merge."
            "options.mode: warn` for advisory-only mode."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for the ancestry-preserving merge handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        mode = getattr(self, "_mode", _MODE_BLOCK)

        if mode == _MODE_WARN:
            return [
                AcceptanceTest(
                    title="git merge --squash (warn mode)",
                    command='echo "git merge --squash feature-branch"',
                    description="Allows git merge --squash with an advisory warning",
                    expected_decision=Decision.ALLOW,
                    expected_message_patterns=[r"WARNING", r"ancestor"],
                    safety_notes="Uses echo - safe to test",
                    test_type=TestType.ADVISORY,
                    recommended_model=RecommendedModel.SONNET,
                    requires_main_thread=False,
                ),
                AcceptanceTest(
                    title="gh pr merge --rebase (warn mode)",
                    command='echo "gh pr merge --rebase 123"',
                    description="Allows gh pr merge --rebase with an advisory warning",
                    expected_decision=Decision.ALLOW,
                    expected_message_patterns=[r"WARNING", r"ancestor"],
                    safety_notes="Uses echo - safe to test",
                    test_type=TestType.ADVISORY,
                    recommended_model=RecommendedModel.SONNET,
                    requires_main_thread=False,
                ),
            ]

        return [
            AcceptanceTest(
                title="git merge --squash",
                command='echo "git merge --squash feature-branch"',
                description="Blocks git merge --squash (severs ancestry)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED", r"ancestor"],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="gh pr merge --squash",
                command='echo "gh pr merge --squash 123"',
                description="Blocks gh pr merge --squash (severs ancestry)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED", r"ancestor"],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="gh pr merge --rebase",
                command='echo "gh pr merge --rebase 123"',
                description="Blocks gh pr merge --rebase (severs ancestry, widened this plan's scope)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED", r"ancestor"],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git merge --no-ff is not blocked",
                command='echo "git merge --no-ff feature-branch"',
                description=(
                    "git merge --no-ff preserves ancestry and must NOT be "
                    "blocked -- it is the whole point of this handler"
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="gh pr merge --merge is not blocked",
                command='echo "gh pr merge --merge 123"',
                description="gh pr merge --merge preserves ancestry and must NOT be blocked",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
