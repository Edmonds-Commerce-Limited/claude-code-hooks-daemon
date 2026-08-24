"""Branch naming advisor handler.

Example project handler that checks the current git branch name against
allowed patterns at session start and reports a non-conforming branch as
context.

It ADVISES rather than blocks, and that is a property of the event, not a
softening of the rule: `SessionStart` has no way to express a refusal on the
wire, so a handler that denied here would have its refusal silently dropped and
the session would start anyway. Reporting it as context is the strongest thing
this event can actually do — and it reaches Claude, which is what changes
behaviour. To BLOCK work on a badly-named branch, put the check on `PreToolUse`
instead, where a refusal is deliverable.

Copy this to .claude/project-handlers/session_start/ and adapt the patterns.
"""

import re
import subprocess
from typing import Any

from claude_code_hooks_daemon.core import AcceptanceTest, AdvisoryResult, TestType
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.hook_result import Decision

# Adapt these patterns to your project's branch naming conventions
_ALLOWED_BRANCH_PATTERN = re.compile(r"^(feature|fix|chore|docs|plan)/.*$")

_ALLOWED_SPECIAL_BRANCHES = frozenset({"main", "master", "develop", "staging"})


class BranchNamingEnforcerHandler(SessionStartHandlerBase):
    """Report a branch that breaks the project's naming convention.

    Checks that the current git branch follows the pattern:
    feature/*, fix/*, chore/*, docs/*, plan/*
    or is a special branch (main, master, develop, staging).

    Subclassing ``SessionStartHandlerBase`` narrows ``handle()`` to
    ``AdvisoryResult``, so this handler CANNOT be edited into returning a
    refusal that the event would silently discard.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id="branch-naming-enforcer",
            priority=30,
            # SessionStart cannot refuse, so terminal only decides whether
            # LATER session-start handlers still run — never whether the
            # session proceeds. Leave it False so peers keep their say.
            terminal=False,
            tags=["project", "git", "workflow"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always match on session start."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Check branch name against allowed patterns."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            return AdvisoryResult.allow(
                context=["Branch naming check skipped: git command timed out."],
            )

        if result.returncode != 0:
            return AdvisoryResult.allow(
                context=["Branch naming check skipped: could not determine current branch."],
            )

        branch = result.stdout.strip()

        if branch in _ALLOWED_SPECIAL_BRANCHES:
            return AdvisoryResult.allow()

        if _ALLOWED_BRANCH_PATTERN.match(branch):
            return AdvisoryResult.allow()

        return AdvisoryResult.allow(
            context=[
                f"BRANCH NAMING: '{branch}' does not follow this project's convention.",
                "Expected: feature/*, fix/*, chore/*, docs/*, plan/* "
                "or a special branch (main, master, develop, staging).",
                f"Rename it before opening a PR: git branch -m feature/{branch}",
            ],
        )

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Acceptance tests for the branch naming advisory.

        Both branches of the check are covered. The conforming case alone was
        never enough: it passes just as happily against a handler whose
        non-conforming path does nothing at all, which is exactly the state
        this example shipped in.
        """
        return [
            AcceptanceTest(
                title="Conforming branch says nothing",
                command="git rev-parse --abbrev-ref HEAD",
                description=(
                    "On a conforming branch the session starts with no branch-naming "
                    "context injected"
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Read-only git query - safe to execute",
                requires_event="SessionStart",
                test_type=TestType.CONTEXT,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="Non-conforming branch is reported as context",
                command="git rev-parse --abbrev-ref HEAD",
                description=(
                    "On a branch that breaks the convention, SessionStart context names "
                    "the branch and the expected patterns. It ALLOWS: SessionStart cannot "
                    "carry a refusal, so a deny here would be dropped and the session "
                    "would start regardless."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[
                    r"BRANCH NAMING",
                    r"does not follow this project's convention",
                ],
                setup_commands=["git checkout -b nonconforming-example-branch"],
                cleanup_commands=["git checkout - && git branch -d nonconforming-example-branch"],
                safety_notes=(
                    "Creates and deletes a throwaway branch; uses the safe -d delete, "
                    "which refuses if the branch holds unmerged work"
                ),
                requires_event="SessionStart",
                test_type=TestType.CONTEXT,
                requires_main_thread=True,
            ),
        ]
