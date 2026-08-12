"""Python comment strategy implementation."""

from typing import Any

from claude_code_hooks_daemon.strategies.comments.common import (
    DEFAULT_SKIP_DIRECTORIES,
)
from claude_code_hooks_daemon.strategies.comments.syntax import (
    PYTHON_SYNTAX,
    CommentSyntax,
)

_LANGUAGE_NAME = "Python"
_EXTENSIONS: tuple[str, ...] = (".py",)


class PythonCommentStrategy:
    """Comment syntax strategy for Python (``#`` line comments, docstrings)."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    @property
    def syntax(self) -> CommentSyntax:
        return PYTHON_SYNTAX

    @property
    def skip_directories(self) -> tuple[str, ...]:
        return DEFAULT_SKIP_DIRECTORIES

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Python comment-changelog detection."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Python: changelog narrative in a comment is blocked",
                command=(
                    "Use the Write tool to create "
                    "/tmp/acceptance-test-comment-changelog-python/example.py whose "
                    "content has a trailing '#' comment on a version-constant line "
                    "reading changelog-style history: 'Prior 3.26.2: fixed timing "
                    "bug. Prior 3.26.1: attempted a different fix.'"
                ),
                description=(
                    "Blocks a Python trailing comment carrying multiple "
                    "'Prior <version>:' dated/versioned entries"
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=["changelog", "comment", "BLOCKED"],
                safety_notes="Uses /tmp path - safe. Handler blocks Write before file is created.",
                test_type=TestType.BLOCKING,
                setup_commands=["mkdir -p /tmp/acceptance-test-comment-changelog-python"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-comment-changelog-python"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
