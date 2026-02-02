"""EslintDisableHandler - blocks ESLint disable comments in code."""

import re
from typing import Any, ClassVar

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_file_content, get_file_path


class EslintDisableHandler(Handler):
    """Block ESLint disable comments in code."""

    FORBIDDEN_PATTERNS: ClassVar[list[str]] = [
        r"eslint-disable",
        r"@ts-ignore",
        r"@ts-nocheck",
        r"@ts-expect-error",
    ]

    CHECK_EXTENSIONS: ClassVar[list[str]] = [".ts", ".tsx", ".js", ".jsx"]

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.ESLINT_DISABLE,
            priority=Priority.ESLINT_DISABLE,
            tags=[
                HandlerTag.QA_SUPPRESSION_PREVENTION,
                HandlerTag.TYPESCRIPT,
                HandlerTag.JAVASCRIPT,
                HandlerTag.BLOCKING,
                HandlerTag.TERMINAL,
            ],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if writing ESLint disable comments."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name not in [ToolName.WRITE, ToolName.EDIT]:
            return False

        file_path = get_file_path(hook_input)

        # If file_path is provided, check extension
        if file_path:
            # Case-insensitive extension check
            file_path_lower = file_path.lower()
            if not any(file_path_lower.endswith(ext) for ext in self.CHECK_EXTENSIONS):
                return False

            # Skip node_modules, dist, build artifacts
            if any(skip in file_path for skip in ["node_modules", "dist", ".build", "coverage"]):
                return False

        content = get_file_content(hook_input)
        if tool_name == ToolName.EDIT:
            content = hook_input.get(HookInputField.TOOL_INPUT, {}).get("new_string", "")

        if not content:
            return False

        # If no file_path, check content for JavaScript/TypeScript markers
        if not file_path:
            # Only match if content looks like JS/TS (has //, /* */, or typical JS syntax)
            js_markers = [r"//", r"/\*", r"const\s+", r"let\s+", r"var\s+", r"function\s+", r"=>"]
            has_js_marker = any(re.search(marker, content) for marker in js_markers)
            if not has_js_marker:
                return False

        # Check for forbidden patterns
        for pattern in self.FORBIDDEN_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                return True

        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block ESLint suppressions."""
        file_path = get_file_path(hook_input)
        content = get_file_content(hook_input)
        if hook_input.get(HookInputField.TOOL_NAME) == "Edit":
            content = hook_input.get(HookInputField.TOOL_INPUT, {}).get("new_string", "")

        if not content:
            return HookResult(decision=Decision.ALLOW)

        # Find which pattern matched
        issues = []
        for pattern in self.FORBIDDEN_PATTERNS:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                issues.append(match.group(0))

        return HookResult(
            decision=Decision.DENY,
            reason=(
                "🚫 BLOCKED: ESLint suppression comments are not allowed\n\n"
                f"File: {file_path}\n\n"
                f"Found {len(issues)} suppression comment(s):\n"
                + "\n".join(f"  - {issue}" for issue in issues[:5])
                + "\n\n"
                "WHY: Suppression comments hide real problems and create technical debt.\n\n"
                "✅ CORRECT APPROACH:\n"
                "  1. Fix the underlying issue (don't suppress)\n"
                "  2. Refactor code to meet ESLint rules\n"
                "  3. If rule is genuinely wrong, update .eslintrc.json project-wide\n\n"
                "ESLint rules exist for good reason. Fix the code, don't silence the tool."
            ),
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Eslint Disable."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="eslint-disable-next-line in JS",
                command="Write JS file with '// eslint-disable-next-line' comment",
                description="Blocks eslint-disable comments (fix linting issues instead)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"eslint-disable", r"Fix.*linting", r"BLOCKED"],
                safety_notes="Tests Write tool validation without actual file operations",
                test_type=TestType.BLOCKING,
                requires_event="PreToolUse with Write tool to .js file",
            ),
        ]
