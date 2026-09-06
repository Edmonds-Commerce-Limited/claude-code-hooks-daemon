"""Kotlin lint strategy implementation."""

from typing import Any

from claude_code_hooks_daemon.strategies.lint.common import COMMON_SKIP_PATHS
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

# Language-specific constants
_LANGUAGE_NAME = "Kotlin"
_EXTENSIONS: tuple[str, ...] = (".kt",)
_DEFAULT_LINT_COMMAND = "kotlinc -script {file} 2>&1"
_EXTENDED_LINT_COMMAND = "ktlint {file}"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-lint-kotlin"


class KotlinLintStrategy:
    """Lint enforcement strategy for Kotlin files.

    Default: kotlinc -script (compilation check)
    Extended: ktlint (style and error detection)
    """

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    @property
    def default_lint_command(self) -> str:
        return _DEFAULT_LINT_COMMAND

    @property
    def extended_lint_command(self) -> str | None:
        return _EXTENDED_LINT_COMMAND

    @property
    def skip_paths(self) -> tuple[str, ...]:
        return COMMON_SKIP_PATHS

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Kotlin lint strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        fixture_root = scratch_path(_FIXTURE_DIR)

        return [
            AcceptanceTest(
                title="Kotlin lint - valid code passes",
                command=(
                    "Use the Write tool to create file "
                    f"{scratch_path(_FIXTURE_DIR, 'valid.kt')} "
                    'with content "fun main() { println(\\"hello\\") }"'
                ),
                description="Valid Kotlin code should pass lint validation",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Inside the gitignored scratch directory - safe. "
                    "Creates temporary Kotlin file."
                ),
                test_type=TestType.ADVISORY,
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Kotlin lint - invalid code blocked",
                command=(
                    "Use the Write tool to create file "
                    f"{scratch_path(_FIXTURE_DIR, 'invalid.kt')} "
                    'with content "fun main( { println(\\"hello\\") }"'
                ),
                description="Invalid Kotlin code (missing closing paren) should be blocked",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"Kotlin lint FAILED", r"invalid.kt"],
                safety_notes=(
                    "Inside the gitignored scratch directory - safe. "
                    "Creates temporary Kotlin file with syntax error."
                ),
                test_type=TestType.BLOCKING,
                required_tools=["kotlinc"],
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
