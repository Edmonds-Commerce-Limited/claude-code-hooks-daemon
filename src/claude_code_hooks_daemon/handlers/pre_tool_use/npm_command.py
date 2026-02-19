"""NpmCommandHandler - enforces llm: prefixed npm commands and blocks direct npx usage.

When llm: commands exist in package.json, enforces their usage (DENY raw commands).
When llm: commands do NOT exist, allows with advisory about creating them.
"""

import re
from typing import Any, ClassVar

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.guides import get_llm_command_guide_path
from claude_code_hooks_daemon.utils.npm import has_llm_commands_in_package_json


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
            handler_id=HandlerID.NPM_COMMAND,
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
        self.has_llm_commands: bool = has_llm_commands_in_package_json()

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

        # Advisory mode: no llm: commands in package.json
        if not self.has_llm_commands:
            guide_path = get_llm_command_guide_path()
            return HookResult(
                decision=Decision.ALLOW,
                reason=(
                    f"⚠️  ADVISORY: Consider creating llm: prefixed npm commands\n\n"
                    f"You're using: {blocked_cmd}\n\n"
                    f"RECOMMENDATION: Create llm: wrappers in package.json for better LLM integration\n"
                    f"  • Minimal stdout (summary only: exit code, counts, timing)\n"
                    f"  • Verbose JSON files in ./var/qa/ (optimized for jq queries)\n"
                    f"  • Machine-readable output (parse with jq, not grep/sed)\n\n"
                    f"Example package.json script:\n"
                    f'  "llm:{npm_cmd if npm_match else suggested}": '
                    f'"<tool> --format json --output-file ./var/qa/<tool>-cache.json"\n\n'
                    f"Full guide: {guide_path}\n\n"
                    f"This command will run for now, but consider adding llm: wrappers."
                ),
            )

        # Enforcement mode: llm: commands exist in package.json
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

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Npm Command."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="npm command enforcement (llm: commands exist)",
                command='echo "npm run build"',
                description=(
                    "Blocks raw npm commands when llm: wrappers exist in package.json. "
                    "If this project has llm: scripts, expect DENY. "
                    "If not, expect ALLOW with advisory."
                ),
                expected_decision=Decision.DENY if self.has_llm_commands else Decision.ALLOW,
                expected_message_patterns=[r"llm:", r"npm"],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
