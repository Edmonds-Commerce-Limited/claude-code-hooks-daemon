"""Ruby lint strategy implementation."""

from typing import Any

from claude_code_hooks_daemon.strategies.lint.common import COMMON_SKIP_PATHS

# Language-specific constants
_LANGUAGE_NAME = "Ruby"
_EXTENSIONS: tuple[str, ...] = (".rb",)
_DEFAULT_LINT_COMMAND = "ruby -c {file}"
_EXTENDED_LINT_COMMAND = "rubocop {file}"


class RubyLintStrategy:
    """Lint enforcement strategy for Ruby files.

    Default: ruby -c (syntax check)
    Extended: rubocop (style and error detection)
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
        """Return acceptance tests for Ruby lint strategy."""
        from claude_code_hooks_daemon.core import AcceptanceTest, Decision, TestType

        return [
            AcceptanceTest(
                title="Ruby lint - valid code passes",
                command=(
                    "Use the Write tool to create file "
                    "/tmp/acceptance-test-lint-ruby/valid.rb "
                    "with content \"puts 'hello'\""
                ),
                description="Valid Ruby code should pass lint validation",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Uses /tmp path - safe. Creates temporary Ruby file.",
                test_type=TestType.ADVISORY,
                setup_commands=["mkdir -p /tmp/acceptance-test-lint-ruby"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-lint-ruby"],
            ),
            AcceptanceTest(
                title="Ruby lint - invalid code blocked",
                command=(
                    "Use the Write tool to create file "
                    "/tmp/acceptance-test-lint-ruby/invalid.rb "
                    "with content \"def hello\\n  puts 'missing end'\""
                ),
                description="Invalid Ruby code (missing end) should be blocked",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"Ruby lint FAILED", r"invalid.rb"],
                safety_notes="Uses /tmp path - safe. Creates temporary Ruby file with syntax error.",
                test_type=TestType.BLOCKING,
                setup_commands=["mkdir -p /tmp/acceptance-test-lint-ruby"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-lint-ruby"],
            ),
        ]
