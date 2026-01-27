"""BashErrorDetectorHandler - detects errors and warnings in Bash command output."""

from typing import Any

from claude_code_hooks_daemon.core import Decision, Handler, HookResult


class BashErrorDetectorHandler(Handler):
    """Detect errors and warnings in Bash command output.

    Provides feedback context when Bash commands exit with errors or when
    output contains error/warning keywords. Non-terminal to allow execution
    to proceed while providing awareness.
    """

    def __init__(self) -> None:
        """Initialise handler as non-terminal for feedback."""
        super().__init__(
            name="bash-error-detector",
            priority=50,
            terminal=False,
            tags=["validation", "bash", "advisory", "non-terminal"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is a Bash tool invocation.

        Args:
            hook_input: Hook input dictionary from Claude Code

        Returns:
            True if Bash tool
        """
        return hook_input.get("tool_name") == "Bash"

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Analyze Bash output for errors/warnings.

        Args:
            hook_input: Hook input dictionary from Claude Code

        Returns:
            HookResult with context if issues detected, otherwise silent allow
        """
        tool_output = hook_input.get("tool_output", {})
        if not tool_output:
            return HookResult(decision=Decision.ALLOW)

        # Handle case where tool_output is a string (shouldn't happen in production)
        if not isinstance(tool_output, dict):
            return HookResult(decision=Decision.ALLOW)

        exit_code = tool_output.get("exit_code", 0)
        stdout = tool_output.get("stdout", "") or ""
        stderr = tool_output.get("stderr", "") or ""

        # Combine output for keyword search
        combined_output = (stdout + "\n" + stderr).lower()

        # Detect issues
        issues = []

        if exit_code != 0:
            issues.append(f"Command exited with code {exit_code}")

        # Case-insensitive keyword detection
        error_keywords = ["error", "failed", "failure", "fatal"]
        warning_keywords = ["warning", "warn", "deprecated"]

        for keyword in error_keywords:
            if keyword in combined_output:
                issues.append(f"Output contains '{keyword}' keyword")
                break  # Only report once per category

        for keyword in warning_keywords:
            if keyword in combined_output:
                issues.append(f"Output contains '{keyword}' keyword")
                break

        # If no issues, silent allow
        if not issues:
            return HookResult(decision=Decision.ALLOW)

        # Build context message
        tool_input = hook_input.get("tool_input", {})
        command = tool_input.get("command", "unknown")

        context = "Bash command detected issues:\n"
        context += f"Command: {command}\n\n"
        context += "Issues detected:\n"
        for issue in issues:
            context += f"  - {issue}\n"

        context += "\nReview the output carefully to ensure the command succeeded as expected."

        return HookResult(decision=Decision.ALLOW, context=[context])
