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
        from claude_code_hooks_daemon.core import AcceptanceTest, Decision, TestType

        return [
            AcceptanceTest(
                title="Lint validation on Rust file write",
                command=(
                    "Use the Write tool to create file "
                    "/tmp/acceptance-test-lint-rust/lib.rs "
                    'with content "pub fn hello() {}"'
                ),
                description="Triggers lint validation after writing Rust file",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"Rust", r"lint"],
                safety_notes="Uses /tmp path - safe. Creates temporary Rust file.",
                test_type=TestType.ADVISORY,
                setup_commands=["mkdir -p /tmp/acceptance-test-lint-rust"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-lint-rust"],
            ),
        ]
