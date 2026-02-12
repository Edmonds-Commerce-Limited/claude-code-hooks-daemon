"""Dart lint strategy implementation."""

from typing import Any

from claude_code_hooks_daemon.strategies.lint.common import COMMON_SKIP_PATHS

# Language-specific constants
_LANGUAGE_NAME = "Dart"
_EXTENSIONS: tuple[str, ...] = (".dart",)
_DEFAULT_LINT_COMMAND = "dart analyze {file}"
_EXTENDED_LINT_COMMAND = None  # Dart's analyzer is comprehensive enough


class DartLintStrategy:
    """Lint enforcement strategy for Dart files.

    Default: dart analyze (comprehensive analysis)
    Extended: None (dart analyze is sufficient)
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
        """Return acceptance tests for Dart lint strategy."""
        from claude_code_hooks_daemon.core import AcceptanceTest, Decision, TestType

        return [
            AcceptanceTest(
                title="Lint validation on Dart file write",
                command=(
                    "Use the Write tool to create file "
                    "/tmp/acceptance-test-lint-dart/main.dart "
                    'with content "void main() { print(\'hello\'); }"'
                ),
                description="Triggers lint validation after writing Dart file",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"Dart", r"lint"],
                safety_notes="Uses /tmp path - safe. Creates temporary Dart file.",
                test_type=TestType.ADVISORY,
                setup_commands=["mkdir -p /tmp/acceptance-test-lint-dart"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-lint-dart"],
            ),
        ]
