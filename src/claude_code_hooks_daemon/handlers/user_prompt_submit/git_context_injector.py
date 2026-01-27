"""GitContextInjectorHandler - injects git status context into user prompts."""

import subprocess
from typing import Any

from claude_code_hooks_daemon.core import Decision, Handler, HookResult


class GitContextInjectorHandler(Handler):
    """Inject current git status as context when user submits a prompt.

    Provides awareness of repository state (branch, uncommitted changes) to help
    the agent make better decisions. Non-terminal to allow prompt processing.
    """

    def __init__(self) -> None:
        """Initialise handler as non-terminal context provider."""
        super().__init__(
            name="git-context-injector",
            priority=20,
            terminal=False,
            tags=["workflow", "git", "context-injection", "non-terminal"],
        )

    def matches(self, _hook_input: dict[str, Any]) -> bool:
        """Match all user prompt submissions.

        Args:
            _hook_input: Hook input dictionary from Claude Code (unused)

        Returns:
            Always True (provide context for all prompts)
        """
        return True

    def handle(self, _hook_input: dict[str, Any]) -> HookResult:
        """Inject git status as context.

        Args:
            _hook_input: Hook input dictionary from Claude Code (unused)

        Returns:
            HookResult with git status context or silent allow if git unavailable
        """
        try:
            # Run git status with short timeout
            result = subprocess.run(
                ["git", "status"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )

            # If git command failed (not a repo, git not installed, etc.), silent allow
            if result.returncode != 0:
                return HookResult(decision=Decision.ALLOW)

            # Build context message
            context = "Current git repository status:\n\n"
            context += result.stdout
            context += "\n---\n"
            context += "Consider this context when making changes to the repository."

            return HookResult(decision=Decision.ALLOW, context=[context])

        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            # Git not installed, timeout, or other errors - silent allow
            return HookResult(decision=Decision.ALLOW)
