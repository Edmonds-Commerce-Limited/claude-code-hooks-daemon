"""Acceptance test definitions for handlers.

This module provides dataclasses for defining programmatic acceptance tests
that handlers must implement.
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from enum import StrEnum
from typing import Any

from claude_code_hooks_daemon.constants.tools import ToolName
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
        requires_llm_commands: The ``required_tools`` idea for a precondition that
            is not a PATH executable: some handlers (``validate_eslint_on_write``)
            only exercise real tool behaviour when the project's ``package.json``
            declares an ``llm:``-prefixed script, taking an advisory branch
            otherwise. Set True to have the playbook probe
            ``utils.npm.has_llm_commands_in_package_json`` and render the same
            SKIP treatment ``required_tools`` gives a missing binary.
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
        dispatch_as_bash: Declares that ``command`` is a literal shell string
            and that the Bash tool receives it verbatim, so the payload is
            DERIVED from it rather than written out a second time.

            The prose tests run this derivation the other way -- they state a
            payload and render the sentence from it -- because five English
            grammars had grown up around one Write payload. A shell test has
            the opposite problem: the bare command is already the best thing a
            human can be handed, and ``as_instruction()`` would render
            ``Use the Bash tool with command='echo "git reset --hard ..."'``,
            strictly harder to paste. Deriving the payload keeps ONE copy, so
            the command a human runs and the command the harness dispatches
            cannot drift apart.

            This is a per-site DECLARATION, not a classifier. Nothing here
            inspects the command's shape to decide whether it is shell -- that
            inference is what Plan 00243 removed, and it has since been
            measured wrong four times over on this playbook's own blocks
            (``Write(`` call syntax, a setup-command count, and two English
            sentences that begin ``WebFetch``/``With``). A block whose command
            merely LOOKS like shell but drives another tool must say so with
            an explicit ``tool_payload``, which is why declaring both raises.
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
    requires_llm_commands: bool = False
    recommended_model: RecommendedModel | None = None
    requires_main_thread: bool = False
    harness_cannot_produce: str | None = None
    tool_payload: ToolPayload | None = None
    #: An `InitVar`, not a field: it is consumed at construction to produce
    #: `tool_payload` and nothing reads it afterwards. A stored field would
    #: also have to be serialised -- `test_playbook_generator_json_field_
    #: coverage` requires every field to reach the JSON -- and emitting it
    #: would invite a harness to read the FLAG instead of the payload, which
    #: is the derived-versus-declared split this collapses.
    dispatch_as_bash: InitVar[bool] = False

    def __post_init__(self, dispatch_as_bash: bool) -> None:
        """Validate fields after initialization."""
        if not self.title or not self.title.strip():
            raise ValueError("title must be a non-empty string")
        if not self.command or not self.command.strip():
            raise ValueError("command must be a non-empty string")
        if not self.description or not self.description.strip():
            raise ValueError("description must be a non-empty string")
        if dispatch_as_bash:
            self._derive_bash_payload()
        if self.harness_cannot_produce and self.tool_payload is not None:
            # The two say opposite things about the same test: one that the
            # input cannot be produced at all, the other exactly how to
            # produce it. Whichever is true, the other is a claim the harness
            # would act on.
            raise ValueError(
                "harness_cannot_produce and tool_payload are mutually exclusive: "
                "a test whose input cannot be produced has no payload to declare"
            )

    def _derive_bash_payload(self) -> None:
        """Build the Bash payload from `command`, refusing any rival claim."""
        if self.tool_payload is not None:
            # Two payloads, and nothing says which one the harness runs. The
            # blocks that carry a shell-shaped command but match a DIFFERENT
            # tool are exactly why this cannot silently pick a winner.
            raise ValueError(
                "dispatch_as_bash and tool_payload are mutually exclusive: "
                "the command is either the Bash payload or another tool's, not both"
            )
        if self.harness_cannot_produce:
            raise ValueError(
                "dispatch_as_bash and harness_cannot_produce are mutually exclusive: "
                "a test whose input cannot be produced has no payload to derive"
            )
        self.tool_payload = ToolPayload(
            tool_name=ToolName.BASH, tool_input={"command": self.command}
        )
