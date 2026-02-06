"""PhpQaSuppressionBlocker - blocks QA suppression comments in PHP code."""

import re
from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.language_config import PHP_CONFIG
from claude_code_hooks_daemon.core.utils import get_file_content, get_file_path


class PhpQaSuppressionBlocker(Handler):
    """Block QA suppression comments in PHP code."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.PHP_QA_SUPPRESSION,
            priority=Priority.PHP_QA_SUPPRESSION,
            tags=[
                HandlerTag.PHP,
                HandlerTag.QA_SUPPRESSION_PREVENTION,
                HandlerTag.BLOCKING,
                HandlerTag.TERMINAL,
            ],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if writing PHP QA suppression comments."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name not in [ToolName.WRITE, ToolName.EDIT]:
            return False

        file_path = get_file_path(hook_input)
        if not file_path:
            return False

        # Case-insensitive extension check
        file_path_lower = file_path.lower()
        if not any(file_path_lower.endswith(ext) for ext in PHP_CONFIG.extensions):
            return False

        # Skip configured directories
        if any(skip in file_path for skip in PHP_CONFIG.skip_directories):
            return False

        content = get_file_content(hook_input)
        if tool_name == ToolName.EDIT:
            content = hook_input.get(HookInputField.TOOL_INPUT, {}).get("new_string", "")

        if not content:
            return False

        # Check for forbidden patterns
        for pattern in PHP_CONFIG.qa_forbidden_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return True

        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block PHP QA suppressions."""
        file_path = get_file_path(hook_input)
        content = get_file_content(hook_input)
        if hook_input.get(HookInputField.TOOL_NAME) == "Edit":
            content = hook_input.get(HookInputField.TOOL_INPUT, {}).get("new_string", "")

        if not content:
            return HookResult(decision=Decision.ALLOW)

        # Find which pattern matched
        issues = []
        for pattern in PHP_CONFIG.qa_forbidden_patterns:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                issues.append(match.group(0))

        # Build resources section from config
        resources_text = "\n".join(
            f"  - {tool}: {url}"
            for tool, url in zip(PHP_CONFIG.qa_tool_names, PHP_CONFIG.qa_tool_docs_urls)
        )

        return HookResult(
            decision=Decision.DENY,
            reason=(
                f"🚫 BLOCKED: {PHP_CONFIG.name} QA suppression comments are not allowed\n\n"
                f"File: {file_path}\n\n"
                f"Found {len(issues)} suppression comment(s):\n"
                + "\n".join(f"  - {issue}" for issue in issues[:5])
                + "\n\n"
                "WHY: Suppression comments hide real problems and create technical debt.\n"
                "Static analysis errors, type issues, and coding standard violations exist for good reason.\n\n"
                "✅ CORRECT APPROACH:\n"
                "  1. Fix the underlying issue (don't suppress)\n"
                "  2. Add proper type declarations instead of suppressing static analysis\n"
                "  3. Refactor code to meet coding standards (PSR-12, etc.)\n"
                "  4. If rule is genuinely wrong for your project, update phpstan.neon or phpcs.xml\n"
                "  5. For test-specific code, ensure file is in tests/ directory\n"
                "  6. For legacy code requiring suppression:\n"
                "     - Add detailed comment explaining WHY suppression is needed\n"
                "     - Create ticket to fix properly\n"
                "     - Link ticket in comment\n\n"
                "Quality tools exist to prevent bugs. Fix the code, don't silence the tool.\n\n"
                f"Resources:\n{resources_text}"
            ),
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Php Qa Suppression Blocker."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="phpcs:ignore comment",
                command="Write PHP file with '// phpcs:ignore' comment",
                description="Blocks phpcs:ignore comments (fix code style instead)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"phpcs:ignore", r"Fix.*issue", r"BLOCKED"],
                safety_notes="Tests Write tool validation without actual file operations",
                test_type=TestType.BLOCKING,
                requires_event="PreToolUse with Write tool to .php file",
            ),
        ]
