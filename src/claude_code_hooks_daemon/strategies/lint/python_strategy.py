"""Python lint strategy implementation."""

import sys
from typing import Any

from claude_code_hooks_daemon.strategies.lint.common import COMMON_SKIP_PATHS
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

# Language-specific constants
_LANGUAGE_NAME = "Python"
_EXTENSIONS: tuple[str, ...] = (".py",)
# Use the same Python interpreter running the daemon (works in any environment)
_DEFAULT_LINT_COMMAND = f"{sys.executable} -m py_compile {{file}}"
_EXTENDED_LINT_COMMAND = "ruff check {file}"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-lint-python"


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
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        fixture_root = scratch_path(_FIXTURE_DIR)

        return [
            AcceptanceTest(
                title="Python lint - valid code passes",
                command=(
                    "Use the Write tool to create file "
                    f"{scratch_path(_FIXTURE_DIR, 'valid.py')} "
                    "with content \"def hello():\\n    print('hello')\\n\""
                ),
                description="Valid Python code should pass lint validation",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Inside the gitignored scratch directory - safe. "
                    "Creates temporary Python file."
                ),
                test_type=TestType.ADVISORY,
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Python lint - invalid code blocked",
                command=(
                    "Use the Write tool to create file "
                    f"{scratch_path(_FIXTURE_DIR, 'invalid.py')} "
                    "with content \"def hello(\\n    print('hello')\""
                ),
                description="Invalid Python code (missing closing paren) should be blocked",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"Python lint FAILED", r"invalid.py", r"SyntaxError"],
                safety_notes=(
                    "Inside the gitignored scratch directory - safe. "
                    "Creates temporary Python file with syntax error."
                ),
                test_type=TestType.BLOCKING,
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
