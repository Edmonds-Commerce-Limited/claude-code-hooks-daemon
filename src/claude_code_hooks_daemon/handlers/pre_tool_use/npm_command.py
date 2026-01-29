"""NpmCommandHandler - enforces llm: prefixed npm commands and blocks direct npx usage."""

import re
from typing import Any, ClassVar

from claude_code_hooks_daemon.constants import HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_bash_command


class NpmCommandHandler(Handler):
    """Enforce llm: prefixed npm commands and block direct npx tool usage."""

    ALLOWED_COMMANDS: ClassVar[list[str]] = ["clean", "dev:permissive"]
    SUGGESTIONS: ClassVar[dict[str, str]] = {
        "build": "llm:build",
        "build:permissive": "llm:build:permissive",
        "lint": "llm:lint",
        "lint:fix": "llm:lint:fix",
        "type-check": "llm:type-check",
        "format": "llm:format",
        "format:check": "llm:format:check",
        "test": "llm:test",
        "test:smoke": "llm:browser-test (Playwright) or llm:test:smoke (fast TypeScript)",
        "qa": "llm:qa",
    }

    # Map npx tools to their npm run llm: equivalents
    NPX_TOOL_SUGGESTIONS: ClassVar[dict[str, str]] = {
        "tsc": "llm:type-check",
        "eslint": "llm:lint",
        "prettier": "llm:format:check",
        "cspell": "llm:spell-check",
        "playwright": "llm:test",
        "tsx": "npm run llm:* (if script has wrapper) or ask user which command",
    }

    def __init__(self) -> None:
        super().__init__(
            name="enforce-npm-commands",
            priority=Priority.NPM_COMMAND,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.NPM,
                HandlerTag.NODEJS,
                HandlerTag.JAVASCRIPT,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
            ],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is an npm run or npx command that needs validation."""
        command = get_bash_command(hook_input)
        if not command:
            return False

        # Check if npm/npx command is being piped (grep, awk, sed, tee, etc.)
        # llm: commands write to cache files, so piping is pointless
        pipe_match = re.search(r"\b(npm\s+run|npx)\s+[a-z:]+.*?\s*\|", command)
        if pipe_match:
            return True  # Block ALL piped npm/npx commands (including llm:)

        # Check for npm run commands
        npm_match = re.search(r"\bnpm\s+run\s+([a-z:]+(?:-[a-z]+)*)", command)
        if npm_match:
            npm_cmd = npm_match.group(1)
            # Only match if NOT already llm: command and NOT in whitelist
            return not npm_cmd.startswith("llm:") and npm_cmd not in self.ALLOWED_COMMANDS

        # Check for npx commands (tsc, eslint, prettier, etc.)
        npx_match = re.search(r"\bnpx\s+([a-z]+)", command)
        if npx_match:
            tool_name = npx_match.group(1)
            # Block all npx tools that have llm: equivalents
            return tool_name in self.NPX_TOOL_SUGGESTIONS

        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block non-llm npm commands, npx tools, and piped commands with suggestion."""
        command = get_bash_command(hook_input)
        if not command:
            return HookResult(decision=Decision.ALLOW, reason="No command found in hook input")

        # Check if command is being piped
        pipe_match = re.search(r"\b(npm\s+run|npx)\s+([a-z:]+).*?\s*\|", command)
        if pipe_match:
            pipe_match.group(1)
            cmd_name = pipe_match.group(2)
            return HookResult(
                decision=Decision.DENY,
                reason=(
                    f"🚫 BLOCKED: Piping npm/npx commands is pointless\n\n"
                    f"PHILOSOPHY: llm: commands write to cache files in ./var/qa/\n"
                    f"Piping output to grep/awk/sed is ineffective because:\n"
                    f"  • Minimal stdout (summary only, not full data)\n"
                    f"  • Full data in JSON cache files\n"
                    f"  • Use jq to query cache files directly\n\n"
                    f"BLOCKED COMMAND:\n"
                    f"  {command}\n\n"
                    f"INSTEAD:\n"
                    f"  1. Run: npm run llm:{cmd_name.replace('llm:', '')}\n"
                    f"  2. Query cache with jq: jq '.results[] | select(.success == false)' ./var/qa/{{type}}-cache.json\n"
                    f"  3. Use jq for filtering, counting, extracting data\n\n"
                    f"Cache files contain full machine-readable JSON - use jq!"
                ),
            )

        # Check if it's npm run command
        npm_match = re.search(r"npm\s+run\s+([a-z:]+(?:-[a-z]+)*)", command)
        if npm_match:
            npm_cmd = npm_match.group(1)
            suggested = self.SUGGESTIONS.get(npm_cmd, "llm:qa")
            blocked_cmd = f"npm run {npm_cmd}"
        else:
            # Must be npx command
            npx_match = re.search(r"npx\s+([a-z]+)", command)
            if npx_match:
                tool_name = npx_match.group(1)
                suggested = self.NPX_TOOL_SUGGESTIONS.get(tool_name, "llm:qa")
                blocked_cmd = f"npx {tool_name}"
            else:
                # Fallback if pattern doesn't match
                return HookResult(decision=Decision.ALLOW, reason="Could not parse npm/npx command")

        return HookResult(
            decision=Decision.DENY,
            reason=(
                f"🚫 BLOCKED: Must use llm: prefixed command instead of '{blocked_cmd}'\n\n"
                f"PHILOSOPHY: Claude should use llm: prefixed commands which provide:\n"
                f"  • Minimal stdout (summary only)\n"
                f"  • Verbose JSON logging to ./var/qa/ files\n"
                f"  • Machine-readable output\n"
                f"  • Caching system for performance\n\n"
                f"BLOCKED COMMAND:\n"
                f"  {blocked_cmd}\n\n"
                f"USE THIS INSTEAD:\n"
                f"  npm run {suggested}\n\n"
                f"The llm: commands create cache files you can read directly.\n"
                f"No need for grep/awk/sed post-processing!"
            ),
        )
