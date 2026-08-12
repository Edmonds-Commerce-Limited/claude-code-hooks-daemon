"""JavaScript/TypeScript comment strategy implementation."""

from typing import Any

from claude_code_hooks_daemon.strategies.comments.common import (
    DEFAULT_SKIP_DIRECTORIES,
)
from claude_code_hooks_daemon.strategies.comments.syntax import (
    SLASH_DOC_SYNTAX,
    CommentSyntax,
)

_LANGUAGE_NAME = "JavaScript/TypeScript"
_EXTENSIONS: tuple[str, ...] = (".js", ".jsx", ".ts", ".tsx")


class JavaScriptCommentStrategy:
    """Comment syntax strategy for JS/TS (``//``, ``/* */``, JSDoc ``/** */``)."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    @property
    def syntax(self) -> CommentSyntax:
        return SLASH_DOC_SYNTAX

    @property
    def skip_directories(self) -> tuple[str, ...]:
        return DEFAULT_SKIP_DIRECTORIES

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for JS/TS comment-changelog detection."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="JavaScript/TypeScript: changelog narrative in a comment is blocked",
                command=(
                    "Use the Write tool to create "
                    "/tmp/acceptance-test-comment-changelog-js/example.ts whose "
                    "content has a trailing '//' comment reading changelog-style "
                    "history: 'Prior 1.4.2: fixed a race. Prior 1.4.1: original "
                    "broken behaviour.'"
                ),
                description=(
                    "Blocks a JS/TS trailing comment carrying multiple "
                    "'Prior <version>:' dated/versioned entries"
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=["changelog", "comment", "BLOCKED"],
                safety_notes="Uses /tmp path - safe. Handler blocks Write before file is created.",
                test_type=TestType.BLOCKING,
                setup_commands=["mkdir -p /tmp/acceptance-test-comment-changelog-js"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-comment-changelog-js"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
