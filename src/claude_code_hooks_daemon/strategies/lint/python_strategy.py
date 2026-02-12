"""Python lint strategy implementation."""

from typing import Any

from claude_code_hooks_daemon.strategies.lint.common import COMMON_SKIP_PATHS

# Language-specific constants
_LANGUAGE_NAME = "Python"
_EXTENSIONS: tuple[str, ...] = (".py",)
_DEFAULT_LINT_COMMAND = "python -m py_compile {file}"
_EXTENDED_LINT_COMMAND = "ruff check {file}"


class PythonLintStrategy:
    """Lint enforcement strategy for Python files.

    Default: python -m py_compile (syntax check)
    Extended: ruff check (style and error detection)
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
        """Return acceptance tests for Python lint strategy."""
        from claude_code_hooks_daemon.core import AcceptanceTest, Decision, TestType

        return [
            AcceptanceTest(
                title="Lint validation on Python file write",
                command=(
                    "Use the Write tool to create file "
                    "/tmp/acceptance-test-lint-python/test.py "
                    'with content "def hello():\\n    print(\'hello\')"'
                ),
                description="Triggers lint validation after writing Python file",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"Python", r"lint"],
                safety_notes="Uses /tmp path - safe. Creates temporary Python file.",
                test_type=TestType.ADVISORY,
                setup_commands=["mkdir -p /tmp/acceptance-test-lint-python"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-lint-python"],
            ),
        ]
