"""Handler to validate instruction file content (CLAUDE.md, README.md).

Blocks implementation logs, status indicators, and other ephemeral content
that should not be committed to permanent instruction files.
"""

import re
from typing import Any, ClassVar, Final

from claude_code_hooks_daemon.constants import HookInputField
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import GatingResult, get_data_layer
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest, RecommendedModel, TestType
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter

# SINGLE SOURCE OF TRUTH: (category name -- matches the keys _find_blocked_pattern
# returns, rule_id, blocked, why, fix, verbose). One Rule per content category
# (Plan 00116, Decision B) -- these are genuinely different concepts, not a
# language/strategy fan-out sharing one rule.
_RULE_DEFINITIONS: Final[tuple[tuple[str, str, str, str, str, str], ...]] = (
    (
        "implementation logs",
        RuleID.INSTRUCTION_IMPLEMENTATION_LOG,
        "implementation logs (e.g. 'created the file X', 'added the class Y')",
        "Instruction files hold permanent instructions, not a log of past edits",
        "Remove the log sentence; put implementation history in git or a plan JOURNAL/",
        "Implementation logs describe WHAT WAS DONE, not what the instructions ARE. "
        "That belongs in a commit message, a plan's JOURNAL/ day-file, or a changelog "
        "-- never in CLAUDE.md/README.md, which are read fresh every session and must "
        "stay a stable description of the project, not a diary of edits.",
    ),
    (
        "status indicators",
        RuleID.INSTRUCTION_STATUS_INDICATOR,
        "status indicators (e.g. checkmark + 'Complete', 'Done', 'Success', 'Fixed')",
        "A completion emoji records a moment in time, not a permanent fact",
        "Remove the status marker; instruction files describe the project, not its history",
        "A checkmark or status emoji followed by a completion word records that SOMETHING "
        "finished at some point -- useful in a progress report, meaningless (and quickly "
        "stale) in a file every session reads as ground truth.",
    ),
    (
        "timestamps",
        RuleID.INSTRUCTION_TIMESTAMP,
        "timestamps (ISO dates such as 2024-03-15)",
        "A dated entry is a log line, and instruction files are not a log",
        "Remove the date; if it is genuinely load-bearing, put it in git history",
        "An ISO-format date embedded in prose almost always means 'this happened on this "
        "day' -- changelog narrative, not a stable instruction. Git already timestamps "
        "every change; duplicating that inside CLAUDE.md/README.md just goes stale.",
    ),
    (
        "llm summaries",
        RuleID.INSTRUCTION_LLM_SUMMARY,
        "LLM summaries (section headings such as '## Summary', '## Key Points', '## Overview')",
        "A summary heading is the shape an LLM's own turn-report takes, not project documentation",
        "Remove the heading and fold any durable content into the surrounding instructions",
        "'## Summary'/'## Key Points'/'## Overview' at the top of a block is the exact "
        "shape an assistant's own end-of-turn report takes. Pasting that report into "
        "CLAUDE.md/README.md turns a one-off summary into permanent (and quickly "
        "irrelevant) content.",
    ),
    (
        "test output",
        RuleID.INSTRUCTION_TEST_OUTPUT,
        "test output counts (e.g. '42 tests passed', '1 test failed')",
        "A test run's result is a point-in-time fact, not a stable instruction",
        "Remove the count; CI already reports this on every run",
        "Recording how many tests passed or failed is a snapshot of one run -- the next "
        "commit invalidates it. CI output is where that fact belongs; an instruction "
        "file that quotes it just goes stale the moment the count changes.",
    ),
    (
        "file listings",
        RuleID.INSTRUCTION_FILE_LISTING,
        "changelog-style file listings (e.g. 'created src/Service/Foo.php')",
        "A file path preceded by a past-tense action verb is changelog narrative",
        "Remove the log line; a bare path reference used as documentation stays allowed",
        "'created'/'modified'/'updated' followed by a source path is the shape of a "
        "changelog entry, not documentation -- that belongs in git history or a plan's "
        "JOURNAL/. A bare path reference in prose (e.g. 'see docs/foo.md for details') "
        "is NOT blocked; only the action-verb + path combination is.",
    ),
    (
        "change summaries",
        RuleID.INSTRUCTION_CHANGE_SUMMARY,
        "change summaries (e.g. 'Added 15 lines', 'Removed 8 lines')",
        "A line-count delta describes one diff, not a stable instruction",
        "Remove the summary; the diff itself is preserved in git",
        "'Added/Removed/Changed N lines' is exactly the shape of a commit-message "
        "one-liner. It is meaningful as history (git already has it) and meaningless "
        "as a standing instruction, since it describes an edit rather than the project.",
    ),
    (
        "completion indicators",
        RuleID.INSTRUCTION_COMPLETION_INDICATOR,
        "completion indicators (e.g. 'ALL DONE!', 'Task complete!', 'Finished task')",
        "A completion phrase announces a session's end, not a fact about the project",
        "Remove the phrase; instruction files should never celebrate finishing a task",
        "'ALL DONE!'/'Task complete!'/'Finished task' is turn-end narration, not project "
        "documentation. It is only ever true for the moment it was written, and every "
        "later session reading the file has no idea what task it refers to.",
    ),
)


class ValidateInstructionContentHandler(PreToolUseHandlerBase):
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
        # One Rule per content category (Decision B: 8 rules), built once from
        # the single source-of-truth _RULE_DEFINITIONS mapping.
        self._rules: tuple[Rule, ...] = tuple(
            Rule(rule_id=rule_id, blocked=blocked, why=why, fix=fix, verbose=verbose)
            for _category, rule_id, blocked, why, fix, verbose in _RULE_DEFINITIONS
        )
        self._rule_by_category: dict[str, Rule] = {
            category: Rule(rule_id=rule_id, blocked=blocked, why=why, fix=fix, verbose=verbose)
            for category, rule_id, blocked, why, fix, verbose in _RULE_DEFINITIONS
        }
        self._formatter = RuleFormatter()

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

    def get_rules(self) -> list[Rule]:
        """Return the 8 Rule objects backing this handler's blocking behaviour."""
        return list(self._rules)

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Validate content being written to instruction files.

        Returns DENY if blocked patterns are found outside code blocks, with a
        verbose-first/terse-after explanation (Plan 00116, Decision G) keyed
        per (transcript_path, rule_id). Returns ALLOW if content is clean or
        patterns are only in code blocks.
        """
        tool_input = hook_input.get("tool_input", {})
        tool_name = hook_input.get("tool_name", "")

        # Get content to check based on tool type
        if tool_name == ToolName.WRITE:
            content = tool_input.get("content", "")
        elif tool_name == ToolName.EDIT:
            content = tool_input.get("new_string", "")
        else:
            return GatingResult(
                decision=Decision.ALLOW,
                reason="Tool type not handled by validator",
            )

        # Check for blocked patterns outside code blocks
        blocked_category = self._find_blocked_pattern(content)
        if blocked_category:
            file_path = tool_input.get("file_path", "unknown")
            rule = self._rule_by_category[blocked_category]

            transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
            tracker = get_data_layer().disclosure

            if transcript_path and tracker.was_disclosed(transcript_path, rule.rule_id):
                message = self._formatter.terse(rule)
            else:
                if transcript_path:
                    tracker.mark_disclosed(transcript_path, rule.rule_id)
                message = self._formatter.verbose(rule)

            message += f"\n\nFILE: {file_path}"

            return GatingResult(decision=Decision.DENY, reason=message)

        return GatingResult(
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

    def get_claude_md(self) -> str | None:
        return (
            "## validate_instruction_content — CLAUDE.md and README.md must have stable content\n\n"
            "A `Write`/`Edit` of ephemeral or session-specific content to `CLAUDE.md` "
            "or `README.md` is "
            "blocked. These files should contain only stable instructions, not implementation "
            "logs or session state.\n\n"
            "**Blocked content types**:\n"
            "- Timestamps and ISO dates\n"
            "- Status emoji followed by completion words (e.g. checkmark + 'Done')\n"
            "- Implementation log sentences ('created the file X', 'added the class Y')\n"
            "- Test output counts ('3 tests passed')\n"
            "- LLM summary section headings ('## Summary', '## Key Points')\n\n"
            "Content inside markdown code blocks is exempt from validation."
        )

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
