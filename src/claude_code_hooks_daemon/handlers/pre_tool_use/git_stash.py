"""GitStashHandler - blocks or warns about git stash based on configuration."""

import re
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_bash_command

# Escape hatch: MUST_STASH_BECAUSE="non-empty reason" before git stash
# Requires a non-empty quoted reason to pass through.
_ESCAPE_HATCH_PATTERN = re.compile(
    r"""MUST_STASH_BECAUSE=["']([^"']+)["']""",
    re.IGNORECASE,
)


class GitStashHandler(Handler):
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
            tags=[HandlerTag.SAFETY, HandlerTag.GIT, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )
        self._mode = "deny"

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is a git stash creation command without escape hatch."""
        command = get_bash_command(hook_input)
        if not command:
            return False

        # Allow recovery/query operations unconditionally
        # pop, apply, list, show — these retrieve stashed work
        # Note: drop/clear are blocked by DestructiveGitHandler
        if re.search(r"git\s+stash\s+(?:pop|apply|list|show)", command, re.IGNORECASE):
            return False

        # Check if this is a stash creation command
        is_stash = bool(
            re.search(r"git\s+stash(?:\s+(?:push|save))?(?=\W|$)", command, re.IGNORECASE)
        )
        if not is_stash:
            return False

        # Escape hatch: MUST_STASH_BECAUSE="non-empty reason" bypasses block
        if _ESCAPE_HATCH_PATTERN.search(command):
            return False

        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block or warn about git stash based on mode configuration."""
        mode = getattr(self, "_mode", "deny")

        if mode == "deny":
            return HookResult(
                decision=Decision.DENY,
                reason=(
                    "BLOCKED: git stash\n\n"
                    "Stashes get forgotten, lost, and block git pull. "
                    "Use git commit instead — WIP commits are fine.\n\n"
                    "DO THIS INSTEAD:\n"
                    "  git commit -m 'WIP: description'\n"
                    "  git pull --rebase\n\n"
                    "ESCAPE HATCH (if you truly must stash):\n"
                    '  MUST_STASH_BECAUSE="explain why commit won\'t work"; '
                    "git stash"
                ),
            )
        else:
            return HookResult(
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
                    command='echo "git stash"',
                    description="Blocks git stash — use git commit instead",
                    expected_decision=Decision.DENY,
                    expected_message_patterns=[
                        r"BLOCKED",
                        r"git commit",
                    ],
                    safety_notes="Uses echo - safe to test",
                    test_type=TestType.BLOCKING,
                    recommended_model=RecommendedModel.HAIKU,
                    requires_main_thread=False,
                ),
                AcceptanceTest(
                    title="git stash push blocked",
                    command="echo \"git stash push -m 'temp changes'\"",
                    description="Blocks git stash push — use git commit instead",
                    expected_decision=Decision.DENY,
                    expected_message_patterns=[
                        r"BLOCKED",
                        r"MUST_STASH_BECAUSE",
                    ],
                    safety_notes="Uses echo - safe to test",
                    test_type=TestType.BLOCKING,
                    recommended_model=RecommendedModel.HAIKU,
                    requires_main_thread=False,
                ),
            ]
        else:
            return [
                AcceptanceTest(
                    title="git stash (warn mode)",
                    command='echo "git stash"',
                    description="Allows git stash with advisory warning",
                    expected_decision=Decision.ALLOW,
                    expected_message_patterns=[
                        r"WARNING",
                        r"git commit",
                    ],
                    safety_notes="Uses echo - safe to test",
                    test_type=TestType.ADVISORY,
                    recommended_model=RecommendedModel.SONNET,
                    requires_main_thread=False,
                ),
                AcceptanceTest(
                    title="git stash push (warn mode)",
                    command="echo \"git stash push -m 'temp changes'\"",
                    description="Allows git stash push with advisory warning",
                    expected_decision=Decision.ALLOW,
                    expected_message_patterns=[
                        r"WARNING",
                        r"git commit",
                    ],
                    safety_notes="Uses echo - safe to test",
                    test_type=TestType.ADVISORY,
                    recommended_model=RecommendedModel.SONNET,
                    requires_main_thread=False,
                ),
            ]
