"""Acceptance test definitions for handlers.

This module provides dataclasses for defining programmatic acceptance tests
that handlers must implement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from claude_code_hooks_daemon.core.hook_result import Decision


@dataclass(frozen=True)
class ToolPayload:
    """The exact tool call a harness must synthesise to trigger a test.

    ``AcceptanceTest.command`` is overloaded: sometimes a literal shell
    command, sometimes an English sentence describing a tool call ("Use the
    Write tool to create file X with content Y"). Nothing marks which, so a
    harness that wants to DRIVE the test has to guess -- and the Plan 00243
    prototype's guessing produced 49 false failures from five different
    grammars expressing one payload.

    Declaring the payload removes the guess. ``tool_name``/``tool_input`` are
    the hook event's own field names, so a harness builds its probe by copying
    them rather than by reconstructing them.

    A shell string is not an alternative for these tests. A ``Write``-tool
    guard is not reachable from bash at all -- a file written through Bash
    bypasses the content guards that run BEFORE a ``Write`` -- so rewriting
    such a test as ``echo ... > f`` would assert the opposite of what it means
    to assert.

    Frozen because handlers build these at import time and the generator hands
    the same object to every renderer; a mutable payload would let one of them
    edit what the next reads.
    """

    tool_name: str
    tool_input: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Reject a payload no harness could dispatch."""
        if not self.tool_name or not self.tool_name.strip():
            raise ValueError("tool_name must be a non-empty string")

    def as_instruction(self) -> str:
        """Render the sentence a human tester follows, FROM this payload.

        The audit behind Plan 00243 counted FIVE grammars expressing one Write
        payload. They existed because every site hand-wrote its own sentence
        beside its own values, so the two could disagree with nothing to
        notice. Deriving the sentence removes the second copy: a site states
        the payload once and both readers -- the harness and the human -- get
        the same fact by construction rather than by review.

        Arguments are sorted, so the same payload written by two authors in
        two key orders still renders identically; dict order would otherwise
        reintroduce the very variation this collapses. Values are rendered
        with ``repr`` so a newline inside file content stays inside the
        sentence instead of splitting the playbook's ``**Command**`` block
        across two lines and reading as two instructions.
        """
        if not self.tool_input:
            return f"Use the {self.tool_name} tool"
        rendered = ", ".join(f"{key}={value!r}" for key, value in sorted(self.tool_input.items()))
        return f"Use the {self.tool_name} tool with {rendered}"


class RecommendedModel(StrEnum):
    """Recommended model for running an acceptance test.

    Used by test runners to route tests to the most efficient model:

    HAIKU: Simple pattern-matching tests that verify a command is blocked
        or allowed. Fast and cheap. Can run in parallel sub-agents.
        Use for: BLOCKING tests with echo/bash commands or Write tool.

    SONNET: Tests requiring advisory context verification or moderate
        reasoning. Use for: ADVISORY tests and most CONTEXT tests.

    OPUS: Tests requiring high-quality judgment or complex verification.
        Use for: nuanced advisory tests or architectural validation.
    """

    HAIKU = "haiku"
    SONNET = "sonnet"
    OPUS = "opus"


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
        recommended_model: Suggested model for running this test. HAIKU for simple
            blocking tests, SONNET for advisory/context tests, OPUS for complex
            judgment tests. None means no preference.
        requires_main_thread: If True, test must run in the main Claude Code session
            (not a sub-agent). Required for SessionStart/UserPromptSubmit CONTEXT
            tests and VERIFIED_BY_LOAD tests. BLOCKING and ADVISORY tests can run
            in sub-agents (requires_main_thread=False).
        harness_cannot_produce: Explanation of why Claude Code cannot produce the
            input this test needs. When set, the playbook renders the test as SKIP
            with this reason instead of asking a tester to run it.

            This is the VERIFIED_BY_LOAD idea (trust the daemon + unit tests)
            applied to a handler whose event type cannot reach that bucket:
            OBSERVABLE vs VERIFIED_BY_LOAD is derived from the EVENT TYPE, so a
            PreToolUse handler has no way to declare itself untriggerable.

            Use ONLY when the harness rewrites or intercepts the input before the
            daemon sees it, making the assertion unreachable by construction —
            never to excuse a test that is merely awkward or slow. State WHAT
            rewrites the input, so the claim can be re-checked when Claude Code
            changes. The handler keeps its real test_type and expected_decision:
            the behaviour is real, only the route to triggering it is gone, so
            the deny path must stay covered by unit and/or socket-level tests.
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
    recommended_model: RecommendedModel | None = None
    requires_main_thread: bool = False
    harness_cannot_produce: str | None = None
    tool_payload: ToolPayload | None = None

    def __post_init__(self) -> None:
        """Validate fields after initialization."""
        if not self.title or not self.title.strip():
            raise ValueError("title must be a non-empty string")
        if not self.command or not self.command.strip():
            raise ValueError("command must be a non-empty string")
        if not self.description or not self.description.strip():
            raise ValueError("description must be a non-empty string")
        if self.harness_cannot_produce and self.tool_payload is not None:
            # The two say opposite things about the same test: one that the
            # input cannot be produced at all, the other exactly how to
            # produce it. Whichever is true, the other is a claim the harness
            # would act on.
            raise ValueError(
                "harness_cannot_produce and tool_payload are mutually exclusive: "
                "a test whose input cannot be produced has no payload to declare"
            )
