"""AbsolutePathHandler - requires absolute paths in file operations."""

from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter

_RULE = Rule(
    rule_id=RuleID.ABSOLUTE_PATH_REQUIRED,
    blocked="`Read`/`Write`/`Edit` file_path requires absolute path",
    why="Ambiguous about the current working directory and can target the wrong file",
    fix="Use an absolute path starting with /",
    verbose=(
        "Why absolute paths are required:\n"
        "  - Eliminates ambiguity about current working directory\n"
        "  - Prevents accidental operations on wrong files\n"
        "  - Makes file operations explicit and traceable\n\n"
        "REQUIRED ACTION:\n"
        "  Use absolute path starting with /\n\n"
        "Note: Claude Code's Read tool documentation states:\n"
        "'The file_path parameter must be an absolute path, not a relative path'"
    ),
)


def _absolute_example(file_path: str) -> str:
    """Worked example for the RUNTIME block reason, on THIS machine.

    Absolute on purpose (Plan 00192): a block reason is ephemeral and read by
    an agent on this machine, so the example must be usable exactly as printed.
    This is the opposite of what ``get_claude_md`` needs — that string is
    written into a tracked file read by every clone (Plan 00244).

    The example used to be hard-coded to ``/workspace``, this repository's own
    self-install root, so every client install was told to prepend a directory
    that does not exist there.

    Returns an empty string when :class:`ProjectContext` is not initialised: a
    block reason must never raise, and an omitted example is better than a
    wrong one.
    """
    try:
        return f"  Example: {ProjectContext.project_root() / file_path}\n"
    except RuntimeError:
        return ""


class AbsolutePathHandler(PreToolUseHandlerBase):
    """Require absolute paths for Read/Write/Edit tool file_path parameters.

    This handler enforces that all file operations use absolute paths to avoid
    ambiguity and ensure operations target the correct files.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.ABSOLUTE_PATH,
            priority=Priority.ABSOLUTE_PATH,
            tags=[HandlerTag.SAFETY, HandlerTag.FILE_OPS, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if tool uses relative path in file_path parameter."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)

        # Only check Read, Write, and Edit tools
        if tool_name not in [ToolName.READ, ToolName.WRITE, ToolName.EDIT]:
            return False

        tool_input = hook_input.get(HookInputField.TOOL_INPUT, {})
        file_path = tool_input.get("file_path", "")

        if not file_path:
            return False

        # Check if path is relative (doesn't start with /)
        return not file_path.startswith("/")

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's blocking behaviour."""
        return [_RULE]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Block relative paths with a verbose-first/terse-after explanation.

        Verbosity is decided per (transcript_path, rule_id) via the shared
        DisclosureTracker (Plan 00116, Decision G). The invocation-specific
        tool name, relative path and worked example are appended to the first
        (verbose) fire only — an agent that has already seen the teaching
        content still gets those details, since they change per call, but
        the surrounding prose is not repeated.
        """
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        tool_input = hook_input.get(HookInputField.TOOL_INPUT, {})
        file_path = tool_input.get("file_path", "")

        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure
        formatter = RuleFormatter()

        if transcript_path and tracker.was_disclosed(
            transcript_path, RuleID.ABSOLUTE_PATH_REQUIRED
        ):
            message = formatter.terse(_RULE) + f"\nRelative path provided: {file_path}"
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, RuleID.ABSOLUTE_PATH_REQUIRED)
            message = (
                formatter.verbose(_RULE) + f"\n\nTool: {tool_name}\n"
                f"Relative path provided: {file_path}\n"
                f"{_absolute_example(file_path)}"
            )

        return GatingResult(decision=Decision.DENY, reason=message)

    def get_claude_md(self) -> str | None:
        return (
            "## absolute_path — always use absolute paths\n\n"
            "The `Read`, `Write`, and `Edit` tools require absolute paths. "
            "Relative paths are blocked.\n\n"
            "- **Blocked**: `src/main.py`, `./config.yaml`, `../other/file.txt`\n"
            "- **Correct**: each of those prefixed with the project's absolute root\n\n"
            "Prepend the absolute path of the project root — the working directory "
            "Claude Code reports for this session — to any relative path before "
            "calling these tools. The block message names the exact path to use, so "
            "there is nothing to guess."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for absolute path handler.

        Both tests are marked ``harness_cannot_produce`` (Plan 00196). Claude
        Code resolves ``file_path`` to an absolute path BEFORE dispatching
        PreToolUse, so the daemon never receives the relative form and no
        tester can trigger these blocks through a real tool call. Verified
        during the v3.51.0 acceptance gate: a Write of the relative path
        ``untracked/relpath_probe.py`` reached a later handler reporting
        ``File: /workspace/untracked/relpath_probe.py``, and ``~/...`` is
        expanded the same way rather than blocked.

        The handler is NOT redundant and must not be removed — a direct socket
        probe with a relative ``file_path`` still returns ``deny``, which is
        the behaviour any non-Claude-Code client relies on. That deny path is
        covered by ``tests/unit/handlers/test_absolute_path.py`` and end to end
        by ``tests/acceptance/test_absolute_path_socket_deny.py``.
        """
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        harness_normalises_paths = (
            "Claude Code resolves file_path to an absolute path before PreToolUse "
            "dispatch, so the relative form never reaches the daemon. Deny path is "
            "covered by tests/unit/handlers/test_absolute_path.py and "
            "tests/acceptance/test_absolute_path_socket_deny.py."
        )

        return [
            AcceptanceTest(
                title="Read with relative path",
                command="Use the Read tool to read file_path 'relative/path/file.txt' (relative path, no leading slash)",
                description="Blocks Read tool with relative path (requires absolute path)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"requires absolute path",
                    r"Relative path provided",
                ],
                safety_notes="Handler blocks before any file I/O occurs.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
                harness_cannot_produce=harness_normalises_paths,
            ),
            AcceptanceTest(
                title="Write with relative path",
                command="Use the Write tool with file_path 'some/relative/path.txt' and content 'test' (relative path, no leading slash)",
                description="Blocks Write tool with relative path",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"absolute path",
                ],
                safety_notes="Handler blocks before any file I/O occurs.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
                harness_cannot_produce=harness_normalises_paths,
            ),
        ]
