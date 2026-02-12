"""Go lint strategy implementation."""

from typing import Any

from claude_code_hooks_daemon.strategies.lint.common import COMMON_SKIP_PATHS

# Language-specific constants
_LANGUAGE_NAME = "Go"
_EXTENSIONS: tuple[str, ...] = (".go",)
_DEFAULT_LINT_COMMAND = "go vet {file}"
_EXTENDED_LINT_COMMAND = "golangci-lint run {file}"


class GoLintStrategy:
    """Lint enforcement strategy for Go files.

    Default: go vet (static analysis)
    Extended: golangci-lint (comprehensive linting)
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
        """Return acceptance tests for Go lint strategy."""
        from claude_code_hooks_daemon.core import AcceptanceTest, Decision, TestType

        return [
            AcceptanceTest(
                title="Lint validation on Go file write",
                command=(
                    "Use the Write tool to create file "
                    "/tmp/acceptance-test-lint-go/main.go "
                    'with content "package main\\nfunc main() {}"'
                ),
                description="Triggers lint validation after writing Go file",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"Go", r"lint"],
                safety_notes="Uses /tmp path - safe. Creates temporary Go file.",
                test_type=TestType.ADVISORY,
                setup_commands=["mkdir -p /tmp/acceptance-test-lint-go"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-lint-go"],
            ),
        ]
