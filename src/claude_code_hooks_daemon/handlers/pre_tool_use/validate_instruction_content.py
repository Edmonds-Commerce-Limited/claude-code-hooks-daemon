"""Handler to validate instruction file content (CLAUDE.md, README.md).

Blocks implementation logs, status indicators, and other ephemeral content
that should not be committed to permanent instruction files.
"""

import re
from typing import Any, ClassVar

from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Handler
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest, RecommendedModel, TestType
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult


class ValidateInstructionContentHandler(Handler):
    """Validates content being written to CLAUDE.md and README.md files.

    Blocks ephemeral content like implementation logs, status indicators,
    timestamps, and test output from being committed to instruction files.

    Content inside markdown code blocks (```) is exempted from validation.
    """

    # Pattern categories - each represents a type of blocked content
    IMPLEMENTATION_LOGS: ClassVar[list[str]] = [
        r"\b(?:created|added|modified|updated|implemented|built|generated)\s+(?:the\s+)?(?:file|directory|class|function|method|interface|trait|enum|feature)\s+\S",
    ]

    STATUS_INDICATORS: ClassVar[list[str]] = [
        r"[✅🟢✓]\s*(?:complete|done|working|success|pass(?:ed|ing)?|fixed?)",
    ]

    TIMESTAMPS: ClassVar[list[str]] = [
        r"\b20\d{2}-\d{2}-\d{2}\b",  # ISO date format
    ]

    LLM_SUMMARIES: ClassVar[list[str]] = [
        r"^##\s+(?:summary|key\s+points|overview)",
    ]

    TEST_OUTPUT: ClassVar[list[str]] = [
        r"\d+\s+tests?\s+(?:pass(?:ed|ing)?|fail(?:ed|ing)?|run|executed)",
    ]

    FILE_LISTINGS: ClassVar[list[str]] = [
        # Only match file paths preceded by action verbs (change log style)
        # e.g. "created src/Service/Foo.php" or "- modified tests/bar.js"
        # Does NOT match documentation references like "See docs/foo.md for details"
        r"(?:created|modified|updated|added|deleted|removed|changed)\s+(?:src|tests?|vendor|config|public|assets|docs)/[a-zA-Z0-9_/\-]+\.(?:php|js|ts|tsx|jsx|md|yml|yaml|json|xml)",
    ]

    CHANGE_SUMMARIES: ClassVar[list[str]] = [
        r"(?:added|removed|changed|modified|updated)\s+\d+\s+lines?",
    ]

    COMPLETION_INDICATORS: ClassVar[list[str]] = [
        r"(?:all\s+done|task\s+complete|finished\s+task)!?",
    ]

    def __init__(self) -> None:
        """Initialize handler."""
        super().__init__(
            handler_id=HandlerID.VALIDATE_INSTRUCTION_CONTENT,
            priority=Priority.VALIDATE_INSTRUCTION_CONTENT,
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this handler applies to the tool call.

        Applies to Write and Edit tools operating on CLAUDE.md or README.md files.
        """
        tool_name = hook_input.get("tool_name", "")
        if tool_name not in (ToolName.WRITE, ToolName.EDIT):
            return False

        tool_input = hook_input.get("tool_input", {})
        file_path: str = tool_input.get("file_path", "")

        # Check if file is CLAUDE.md or README.md (case-insensitive, any directory)
        return bool(file_path.upper().endswith(("CLAUDE.MD", "README.MD")))

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Validate content being written to instruction files.

        Returns DENY if blocked patterns are found outside code blocks.
        Returns ALLOW if content is clean or patterns are only in code blocks.
        """
        tool_input = hook_input.get("tool_input", {})
        tool_name = hook_input.get("tool_name", "")

        # Get content to check based on tool type
        if tool_name == ToolName.WRITE:
            content = tool_input.get("content", "")
        elif tool_name == ToolName.EDIT:
            content = tool_input.get("new_string", "")
        else:
            return HookResult(
                decision=Decision.ALLOW,
                reason="Tool type not handled by validator",
            )

        # Check for blocked patterns outside code blocks
        blocked_category = self._find_blocked_pattern(content)
        if blocked_category:
            file_path = tool_input.get("file_path", "unknown")
            return HookResult(
                decision=Decision.DENY,
                reason=f"🚫 BLOCKED: Detected {blocked_category} in {file_path}",
                guidance=(
                    f"Instruction files (CLAUDE.md, README.md) should contain permanent instructions, "
                    f"not ephemeral content like {blocked_category}.\n\n"
                    f"Blocked content categories:\n"
                    f"- Implementation logs (created file, added class, etc.)\n"
                    f"- Status indicators (✓ Complete, ✅ Done, etc.)\n"
                    f"- Timestamps (2024-03-15)\n"
                    f"- LLM summaries (## Summary, ## Key Points, etc.)\n"
                    f"- Test output (42 tests passed)\n"
                    f"- File listings (src/Service/ProductService.php)\n"
                    f"- Change summaries (Added 15 lines)\n"
                    f"- Completion indicators (ALL DONE!, Task complete!)\n\n"
                    f"Content inside markdown code blocks (```) is allowed."
                ),
            )

        return HookResult(
            decision=Decision.ALLOW,
            context=["Content validated - no ephemeral patterns detected"],
        )

    def _find_blocked_pattern(self, content: str) -> str | None:
        """Find blocked patterns in content, excluding code blocks.

        Returns the category name of the first blocked pattern found,
        or None if content is clean.
        """
        # Remove code blocks before checking patterns
        content_without_code_blocks = self._remove_code_blocks(content)

        # Check each pattern category
        pattern_categories = {
            "implementation logs": self.IMPLEMENTATION_LOGS,
            "status indicators": self.STATUS_INDICATORS,
            "timestamps": self.TIMESTAMPS,
            "llm summaries": self.LLM_SUMMARIES,
            "test output": self.TEST_OUTPUT,
            "file listings": self.FILE_LISTINGS,
            "change summaries": self.CHANGE_SUMMARIES,
            "completion indicators": self.COMPLETION_INDICATORS,
        }

        for category, patterns in pattern_categories.items():
            for pattern in patterns:
                if re.search(pattern, content_without_code_blocks, re.IGNORECASE | re.MULTILINE):
                    return category

        return None

    def _remove_code_blocks(self, content: str) -> str:
        """Remove markdown code blocks from content.

        Code blocks are delimited by triple backticks (```).
        Content inside code blocks should be exempted from validation.
        """
        # Track whether we're inside a code block
        lines = content.split("\n")
        result_lines: list[str] = []
        in_code_block = False

        for line in lines:
            # Check if line starts a code block
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                # Replace code block markers with empty lines to preserve line structure
                result_lines.append("")
                continue

            # If we're in a code block, skip this line (replace with empty)
            if in_code_block:
                result_lines.append("")
            else:
                result_lines.append(line)

        return "\n".join(result_lines)

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Return acceptance tests for this handler."""
        return [
            AcceptanceTest(
                title="Block implementation log in CLAUDE.md",
                command=(
                    "Use the Write tool to write to /tmp/acceptance-test-validate/CLAUDE.md"
                    " with content 'Created the file ProductService.php and added the class'"
                ),
                description="Prevents implementation logs from being written to instruction files",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"implementation logs", r"BLOCKED"],
                safety_notes="Uses /tmp path - safe. Handler blocks Write before file is created.",
                test_type=TestType.BLOCKING,
                setup_commands=["mkdir -p /tmp/acceptance-test-validate"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-validate"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Allow clean instructions in CLAUDE.md",
                command=(
                    "Use the Write tool to write to /tmp/acceptance-test-validate/CLAUDE.md"
                    " with content '# Project Instructions\\n\\nUse strict typing for all modules.'"
                ),
                description="Allows clean instructional content without ephemeral patterns",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"validated"],
                safety_notes="Uses /tmp path - safe. Clean content should be allowed.",
                test_type=TestType.ADVISORY,
                setup_commands=["mkdir -p /tmp/acceptance-test-validate"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-validate"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
