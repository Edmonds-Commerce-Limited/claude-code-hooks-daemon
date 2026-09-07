"""Swift comment strategy implementation."""

from typing import Any

from claude_code_hooks_daemon.strategies.comments.common import (
    DEFAULT_SKIP_DIRECTORIES,
)
from claude_code_hooks_daemon.strategies.comments.syntax import (
    SLASH_SYNTAX,
    CommentSyntax,
)
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

_LANGUAGE_NAME = "Swift"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-comment-changelog-swift"
_EXTENSIONS: tuple[str, ...] = (".swift",)


class SwiftCommentStrategy:
    """Comment syntax strategy for Swift (``//`` line, ``/* */`` block).

    Swift doc comments conventionally use ``///`` triple-slash syntax, not a
    block delimiter -- caught here as an ordinary ``//`` line comment (no
    doc-exemption for triple-slash; see PLAN 00208 Non-Goals).
    """

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    @property
    def syntax(self) -> CommentSyntax:
        return SLASH_SYNTAX

    @property
    def skip_directories(self) -> tuple[str, ...]:
        return DEFAULT_SKIP_DIRECTORIES

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Swift comment-changelog detection."""
        from claude_code_hooks_daemon.constants import ToolName
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        fixture_root = scratch_path(_FIXTURE_DIR)
        probe = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": str(scratch_path(_FIXTURE_DIR, "Example.swift")),
                "content": (
                    'let version = "5.9.3" // Prior 5.9.2: fixed a race. Prior '
                    "5.9.1: original broken behaviour.\n"
                ),
            },
        )

        return [
            AcceptanceTest(
                title="Swift: changelog narrative in a comment is blocked",
                command=probe.as_instruction(),
                tool_payload=probe,
                description=(
                    "Blocks a Swift trailing comment carrying multiple "
                    "'Prior <version>:' dated/versioned entries"
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=["changelog", "comment", "BLOCKED"],
                safety_notes=(
                    "Inside the gitignored scratch directory - safe. Handler "
                    "blocks Write before file is created."
                ),
                test_type=TestType.BLOCKING,
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
