"""PHP lint strategy implementation."""

from typing import Any

from claude_code_hooks_daemon.strategies.lint.common import COMMON_SKIP_PATHS

# Language-specific constants
_LANGUAGE_NAME = "PHP"
_EXTENSIONS: tuple[str, ...] = (".php",)
_DEFAULT_LINT_COMMAND = "php -l {file}"
_EXTENDED_LINT_COMMAND = "phpstan analyse {file}"


class PhpLintStrategy:
    """Lint enforcement strategy for PHP files.

    Default: php -l (syntax check)
    Extended: phpstan analyse (static analysis)
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
        """Return acceptance tests for PHP lint strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="PHP lint - valid code passes",
                command=(
                    "Use the Write tool to create file "
                    "/tmp/acceptance-test-lint-php/valid.php "
                    "with content \"<?php echo 'hello'; ?>\""
                ),
                description="Valid PHP code should pass lint validation",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Uses /tmp path - safe. Creates temporary PHP file.",
                test_type=TestType.ADVISORY,
                setup_commands=["mkdir -p /tmp/acceptance-test-lint-php"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-lint-php"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="PHP lint - invalid code blocked",
                command=(
                    "Use the Write tool to create file "
                    "/tmp/acceptance-test-lint-php/invalid.php "
                    "with content \"<?php\\necho 'hello'\\necho 'world';\""
                ),
                description=(
                    "Invalid PHP code (missing semicolon between echo statements) "
                    "should be blocked. Note: '<?php echo x ?>' is VALID PHP — "
                    "closing ?> makes the semicolon optional. Use multiple statements "
                    "instead so semicolon is required."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"PHP lint FAILED", r"invalid.php"],
                safety_notes="Uses /tmp path - safe. Creates temporary PHP file with syntax error.",
                test_type=TestType.BLOCKING,
                required_tools=["php"],
                setup_commands=["mkdir -p /tmp/acceptance-test-lint-php"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-lint-php"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
