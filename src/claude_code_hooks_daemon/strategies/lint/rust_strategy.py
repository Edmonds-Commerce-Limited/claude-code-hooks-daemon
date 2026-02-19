"""Rust lint strategy implementation."""

from typing import Any

from claude_code_hooks_daemon.strategies.lint.common import COMMON_SKIP_PATHS

# Language-specific constants
_LANGUAGE_NAME = "Rust"
_EXTENSIONS: tuple[str, ...] = (".rs",)
_DEFAULT_LINT_COMMAND = "rustc --edition 2021 --crate-type lib -Z parse-only {file}"
_EXTENDED_LINT_COMMAND = "clippy-driver {file}"
_EXTRA_SKIP_PATHS: tuple[str, ...] = ("target/",)


class RustLintStrategy:
    """Lint enforcement strategy for Rust files.

    Default: rustc parse-only (syntax check)
    Extended: clippy-driver (comprehensive linting)
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
        return COMMON_SKIP_PATHS + _EXTRA_SKIP_PATHS

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Rust lint strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Rust lint - valid code passes",
                command=(
                    "Use the Write tool to create file "
                    "/tmp/acceptance-test-lint-rust/valid.rs "
                    'with content "pub fn hello() {}"'
                ),
                description="Valid Rust code should pass lint validation",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Uses /tmp path - safe. Creates temporary Rust file.",
                test_type=TestType.ADVISORY,
                setup_commands=["mkdir -p /tmp/acceptance-test-lint-rust"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-lint-rust"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Rust lint - invalid code blocked",
                command=(
                    "Use the Write tool to create file "
                    "/tmp/acceptance-test-lint-rust/invalid.rs "
                    'with content "pub fn hello( {}"'
                ),
                description="Invalid Rust code (missing closing paren) should be blocked",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"Rust lint FAILED", r"invalid.rs"],
                safety_notes="Uses /tmp path - safe. Creates temporary Rust file with syntax error.",
                test_type=TestType.BLOCKING,
                required_tools=["rustc"],
                setup_commands=["mkdir -p /tmp/acceptance-test-lint-rust"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-lint-rust"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
