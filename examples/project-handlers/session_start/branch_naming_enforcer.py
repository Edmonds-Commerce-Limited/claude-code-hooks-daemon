"""Branch naming enforcer handler.

Example project handler that checks the current git branch name against
allowed patterns at session start. Blocks sessions on non-conforming branches.

Copy this to .claude/project-handlers/session_start/ and adapt the patterns.
"""

import re
import subprocess
from typing import Any

from claude_code_hooks_daemon.core import AcceptanceTest, Handler, HookResult, TestType
from claude_code_hooks_daemon.core.hook_result import Decision

# Adapt these patterns to your project's branch naming conventions
_ALLOWED_BRANCH_PATTERN = re.compile(
    r"^(feature|fix|chore|docs|plan)/.*$"
)

_ALLOWED_SPECIAL_BRANCHES = frozenset({"main", "master", "develop", "staging"})


class BranchNamingEnforcerHandler(Handler):
    """Enforce branch naming conventions at session start.

    Checks that the current git branch follows the pattern:
    feature/*, fix/*, chore/*, docs/*, plan/*
    or is a special branch (main, master, develop, staging).
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id="branch-naming-enforcer",
            priority=30,
            terminal=False,  # Change to True for strict enforcement
            tags=["project", "git", "workflow"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always match on session start."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Check branch name against allowed patterns."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            return HookResult.allow(
                context=["Branch naming check skipped: git command timed out."],
            )

        if result.returncode != 0:
            return HookResult.allow(
                context=["Branch naming check skipped: could not determine current branch."],
            )

        branch = result.stdout.strip()

        if branch in _ALLOWED_SPECIAL_BRANCHES:
            return HookResult.allow()

        if _ALLOWED_BRANCH_PATTERN.match(branch):
            return HookResult.allow()

        return HookResult.deny(
            reason=(
                f"Branch '{branch}' does not follow naming convention. "
                f"Use: feature/*, fix/*, chore/*, docs/*, plan/* "
                f"or a special branch (main, master, develop, staging)."
            ),
        )

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Acceptance tests for branch naming enforcer."""
        return [
            AcceptanceTest(
                title="Valid branch name allowed",
                command='echo "git rev-parse --abbrev-ref HEAD"',
                description="Session starts normally on correctly named branch",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Uses echo - safe to execute",
                test_type=TestType.BLOCKING,
            ),
        ]
