"""Shell/Bash lint strategy implementation."""

from typing import Any

from claude_code_hooks_daemon.strategies.lint.common import COMMON_SKIP_PATHS

# Language-specific constants
_LANGUAGE_NAME = "Shell"
_EXTENSIONS: tuple[str, ...] = (".sh", ".bash")
_DEFAULT_LINT_COMMAND = "bash -n {file}"
_EXTENDED_LINT_COMMAND = "shellcheck {file}"


class ShellLintStrategy:
    """Lint enforcement strategy for Shell/Bash scripts.

    Default: bash -n (syntax check)
    Extended: shellcheck (style and error detection)
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
        """Return acceptance tests for Shell lint strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Shell lint - valid code passes",
                command=(
                    "Use the Write tool to create file "
                    "/tmp/acceptance-test-lint-shell/valid.sh "
                    'with content "#!/bin/bash\\necho hello"'
                ),
                description="Valid Shell script should pass lint validation",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Uses /tmp path - safe. Creates temporary shell script.",
                test_type=TestType.ADVISORY,
                setup_commands=["mkdir -p /tmp/acceptance-test-lint-shell"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-lint-shell"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Shell lint - invalid code blocked",
                command=(
                    "Use the Write tool to create file "
                    "/tmp/acceptance-test-lint-shell/invalid.sh "
                    'with content "#!/bin/bash\\nif [ -f file ]; then\\necho missing fi"'
                ),
                description="Invalid Shell script (missing fi) should be blocked",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"Shell lint FAILED", r"invalid.sh", r"syntax error"],
                safety_notes="Uses /tmp path - safe. Creates temporary shell script with syntax error.",
                test_type=TestType.BLOCKING,
                setup_commands=["mkdir -p /tmp/acceptance-test-lint-shell"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-lint-shell"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
