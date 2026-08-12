"""Dart comment strategy implementation."""

from typing import Any

from claude_code_hooks_daemon.strategies.comments.common import (
    DEFAULT_SKIP_DIRECTORIES,
)
from claude_code_hooks_daemon.strategies.comments.syntax import (
    SLASH_SYNTAX,
    CommentSyntax,
)

_LANGUAGE_NAME = "Dart"
_EXTENSIONS: tuple[str, ...] = (".dart",)


class DartCommentStrategy:
    """Comment syntax strategy for Dart (``//`` line, ``/* */`` block).

    Dart doc comments conventionally use ``///`` triple-slash syntax, not a
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
        """Return acceptance tests for Dart comment-changelog detection."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Dart: changelog narrative in a comment is blocked",
                command=(
                    "Use the Write tool to create "
                    "/tmp/acceptance-test-comment-changelog-dart/example.dart whose "
                    "content has a trailing '//' comment reading changelog-style "
                    "history: 'Prior 3.2.2: fixed a race. Prior 3.2.1: original "
                    "broken behaviour.'"
                ),
                description=(
                    "Blocks a Dart trailing comment carrying multiple "
                    "'Prior <version>:' dated/versioned entries"
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=["changelog", "comment", "BLOCKED"],
                safety_notes="Uses /tmp path - safe. Handler blocks Write before file is created.",
                test_type=TestType.BLOCKING,
                setup_commands=["mkdir -p /tmp/acceptance-test-comment-changelog-dart"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-comment-changelog-dart"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
