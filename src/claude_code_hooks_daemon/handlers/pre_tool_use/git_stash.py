"""GitStashHandler - completely blocks git stash with no exceptions."""

import re
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_bash_command


class GitStashHandler(Handler):
    """Completely block git stash - no exceptions."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.GIT_STASH,
            priority=Priority.GIT_STASH,
            tags=[HandlerTag.SAFETY, HandlerTag.GIT, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is a git stash creation command."""
        command = get_bash_command(hook_input)
        if not command:
            return False

        # Match stash creation commands but NOT recovery/query operations
        # Block: git stash, git stash push, git stash save
        # Allow: git stash pop, git stash apply, git stash list, git stash show
        # Note: drop/clear are blocked by DestructiveGitHandler
        if re.search(r"git\s+stash\s+(?:pop|apply|list|show)", command, re.IGNORECASE):
            return False  # Allow recovery/query operations

        # Match creation commands
        return bool(re.search(r"git\s+stash(?:\s+(?:push|save))?(?:\s|$)", command, re.IGNORECASE))

    def handle(self, _hook_input: dict[str, Any]) -> HookResult:
        """Warn about git stash but allow with guidance."""
        return HookResult(
            decision=Decision.ALLOW,
            context=[
                "WARNING: git stash detected",
                "Stashes can be lost, forgotten, or accidentally dropped",
                "Consider safer alternatives like git commit or git worktree",
            ],
            guidance=(
                "⚠️  WARNING: git stash is risky\n\n"
                "WHY:\n"
                "Stashes can be lost, forgotten, or accidentally dropped.\n"
                "Stashes are especially problematic in worktree-based workflows.\n"
                "There are ALWAYS better alternatives.\n\n"
                "✅ SAFE ALTERNATIVES:\n"
                "  1. git commit -m 'WIP: description'  (proper version control)\n"
                "  2. git checkout -b experiment/name   (new branch for experiments)\n"
                "  3. git worktree add ../worktree-name (parallel work)\n"
                "  4. git add -p                        (stage specific changes)\n\n"
                "🆘 IF YOU THINK YOU NEED STASH:\n"
                "Stop and ask the human for help. There's always a better solution.\n"
                "The human will guide you to the correct approach for your situation."
            ),
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for git stash handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="git stash",
                command='echo "git stash"',
                description="Allows git stash with advisory warning (risky but sometimes needed)",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[
                    r"WARNING.*git stash",
                    r"risky",
                    r"git commit.*WIP",
                ],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.ADVISORY,
            ),
            AcceptanceTest(
                title="git stash push",
                command="echo \"git stash push -m 'temp changes'\"",
                description="Allows git stash push with advisory warning",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[
                    r"WARNING",
                    r"better alternatives",
                ],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.ADVISORY,
            ),
        ]
