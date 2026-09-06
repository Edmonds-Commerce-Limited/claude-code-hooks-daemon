"""PHP comment strategy implementation."""

from typing import Any

from claude_code_hooks_daemon.strategies.comments.common import (
    DEFAULT_SKIP_DIRECTORIES,
)
from claude_code_hooks_daemon.strategies.comments.syntax import (
    PHP_SYNTAX,
    CommentSyntax,
)
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

_LANGUAGE_NAME = "PHP"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-comment-changelog-php"
_EXTENSIONS: tuple[str, ...] = (".php",)


class PhpCommentStrategy:
    """Comment syntax strategy for PHP (``#``/``//`` line, ``/* */`` block, PHPDoc)."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    @property
    def syntax(self) -> CommentSyntax:
        return PHP_SYNTAX

    @property
    def skip_directories(self) -> tuple[str, ...]:
        return DEFAULT_SKIP_DIRECTORIES

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for PHP comment-changelog detection."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        fixture_root = scratch_path(_FIXTURE_DIR)

        return [
            AcceptanceTest(
                title="PHP: changelog narrative in a comment is blocked",
                command=(
                    "Use the Write tool to create "
                    f"{scratch_path(_FIXTURE_DIR, 'example.php')} whose "
                    "content has a trailing '//' comment reading changelog-style "
                    "history: 'Prior 7.4.2: fixed a race. Prior 7.4.1: original "
                    "broken behaviour.'"
                ),
                description=(
                    "Blocks a PHP trailing comment carrying multiple "
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
