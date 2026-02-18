"""Acceptance test definitions for handlers.

This module provides dataclasses for defining programmatic acceptance tests
that handlers must implement.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from claude_code_hooks_daemon.core.hook_result import Decision


class TestType(StrEnum):
    """Type of acceptance test.

    Test types determine how handlers are verified during acceptance testing:

    BLOCKING (EXECUTABLE):
        - PreToolUse handlers that deny dangerous commands
        - Must be tested by running commands and verifying they're blocked
        - Examples: destructive_git, sed_blocker, force_push
        - Testing method: Run command with echo, verify hook blocks it

    ADVISORY (EXECUTABLE):
        - PreToolUse/PostToolUse handlers that provide context without blocking
        - Must be tested by running commands and checking system-reminders
        - Examples: git_status, plan_number, tdd_enforcement
        - Testing method: Run command, verify advisory context appears

    CONTEXT (OBSERVABLE or VERIFIED_BY_LOAD):
        - Lifecycle handlers that fire on events (SessionStart, PostToolUse, etc.)
        - Two sub-categories:

        OBSERVABLE (verify in session):
            - SessionStart: Visible in system-reminders at session start
            - UserPromptSubmit: Visible in system-reminders on user messages
            - PostToolUse: Visible in system-reminders after tool calls
            - Testing method: Check system-reminders for expected messages

        VERIFIED_BY_LOAD (trust daemon + unit tests):
            - SessionEnd: Fires when session ends (untestable in-session)
            - PreCompact: Fires during context compaction (untriggerable)
            - Stop, SubagentStop, Status, Notification, PermissionRequest
            - Testing method: Daemon loads successfully + unit tests pass

    Acceptance testing focuses on EXECUTABLE tests (~89 tests, 20-30 min).
    OBSERVABLE tests are quick context checks (30 sec).
    VERIFIED_BY_LOAD handlers are trusted without manual testing.
    """

    BLOCKING = "blocking"
    ADVISORY = "advisory"
    CONTEXT = "context"


@dataclass
class AcceptanceTest:
    """Defines a single acceptance test for a handler.

    Acceptance tests are programmatic definitions of real-world scenarios
    that handlers should handle correctly. They're used to generate manual
    test playbooks and will eventually enable automated testing.

    Attributes:
        title: Short descriptive title for the test
        command: The command/action to test (use echo for destructive commands)
        description: Detailed description of what's being tested
        expected_decision: Expected Decision (ALLOW, DENY, etc.)
        expected_message_patterns: Regex patterns to match in handler messages
        safety_notes: Explanation of why test is safe to execute (optional)
        setup_commands: Commands to run before test (e.g., create test files)
        cleanup_commands: Commands to run after test (e.g., remove test files)
        requires_event: Event type required for test (if not normally triggerable)
        test_type: Type of test (BLOCKING, ADVISORY, CONTEXT)
        required_tools: Optional list of executables that must be in PATH for this
            test to run. If any are missing the test is skipped. Use for language
            linters that may not be installed (e.g. ["go"], ["rustc"], ["swiftc"]).
    """

    title: str
    command: str
    description: str
    expected_decision: Decision
    expected_message_patterns: list[str]
    safety_notes: str | None = None
    setup_commands: list[str] | None = None
    cleanup_commands: list[str] | None = None
    requires_event: str | None = None
    test_type: TestType = TestType.BLOCKING
    required_tools: list[str] | None = None

    def __post_init__(self) -> None:
        """Validate fields after initialization."""
        if not self.title or not self.title.strip():
            raise ValueError("title must be a non-empty string")
        if not self.command or not self.command.strip():
            raise ValueError("command must be a non-empty string")
        if not self.description or not self.description.strip():
            raise ValueError("description must be a non-empty string")
