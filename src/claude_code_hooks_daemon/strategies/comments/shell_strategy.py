"""Shell (bash) comment strategy implementation.

This is the field report's own language (Plan 00208): the version-marker
trailing comment that reached 5,645 characters was a bash line.
"""

from typing import Any

from claude_code_hooks_daemon.strategies.comments.common import (
    DEFAULT_SKIP_DIRECTORIES,
)
from claude_code_hooks_daemon.strategies.comments.syntax import (
    HASH_SYNTAX,
    CommentSyntax,
)
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

_LANGUAGE_NAME = "Shell"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-comment-changelog-shell"
_EXTENSIONS: tuple[str, ...] = (".sh", ".bash")


class ShellCommentStrategy:
    """Comment syntax strategy for Shell/Bash (``#`` line comments only)."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    @property
    def syntax(self) -> CommentSyntax:
        return HASH_SYNTAX

    @property
    def skip_directories(self) -> tuple[str, ...]:
        return DEFAULT_SKIP_DIRECTORIES

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Shell comment-changelog detection."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        fixture_root = scratch_path(_FIXTURE_DIR)

        return [
            AcceptanceTest(
                title="Shell: version-marker trailing comment changelog is blocked",
                command=(
                    "Use the Write tool to create "
                    f"{scratch_path(_FIXTURE_DIR, 'example.sh')} whose "
                    "content has a version variable line with a trailing '#' comment "
                    "reading changelog-style history: 'Patch: 3.27.0 was assigned. "
                    "Prior 3.26.2: whitelisted the supervisor. Prior 3.26.1: fixed "
                    "a different bug.' (the exact real-world shape reported)"
                ),
                description=(
                    "Blocks the field-report shape: a bash version-marker trailing "
                    "comment carrying release-numbered history"
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
