"""Swift lint strategy implementation."""

from typing import Any

from claude_code_hooks_daemon.strategies.lint.common import COMMON_SKIP_PATHS

# Language-specific constants
_LANGUAGE_NAME = "Swift"
_EXTENSIONS: tuple[str, ...] = (".swift",)
_DEFAULT_LINT_COMMAND = "swiftc -typecheck {file}"
_EXTENDED_LINT_COMMAND = "swiftlint lint {file}"


class SwiftLintStrategy:
    """Lint enforcement strategy for Swift files.

    Default: swiftc -typecheck (type checking)
    Extended: swiftlint (style and error detection)
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
        """Return acceptance tests for Swift lint strategy."""
        from claude_code_hooks_daemon.core import AcceptanceTest, Decision, TestType

        return [
            AcceptanceTest(
                title="Swift lint - valid code passes",
                command=(
                    "Use the Write tool to create file "
                    "/tmp/acceptance-test-lint-swift/valid.swift "
                    'with content "print(\\"hello\\")"'
                ),
                description="Valid Swift code should pass lint validation",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Uses /tmp path - safe. Creates temporary Swift file.",
                test_type=TestType.ADVISORY,
                setup_commands=["mkdir -p /tmp/acceptance-test-lint-swift"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-lint-swift"],
            ),
            AcceptanceTest(
                title="Swift lint - invalid code blocked",
                command=(
                    "Use the Write tool to create file "
                    "/tmp/acceptance-test-lint-swift/invalid.swift "
                    'with content "print(\\"hello"'
                ),
                description="Invalid Swift code (unclosed string) should be blocked",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"Swift lint FAILED", r"invalid.swift"],
                safety_notes="Uses /tmp path - safe. Creates temporary Swift file with syntax error.",
                test_type=TestType.BLOCKING,
                setup_commands=["mkdir -p /tmp/acceptance-test-lint-swift"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-lint-swift"],
            ),
        ]
