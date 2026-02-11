"""Rust QA suppression strategy implementation."""

from typing import Any

# ── Language-specific constants ──────────────────────────────────
_LANGUAGE_NAME = "Rust"
_EXTENSIONS: tuple[str, ...] = (".rs",)
_FORBIDDEN_PATTERNS: tuple[str, ...] = (
    r"#\[" + r"allow\(",
    r"#!\[" + r"allow\(",
)
_SKIP_DIRECTORIES: tuple[str, ...] = (
    "target/",
    "vendor/",
)
_TOOL_NAMES: tuple[str, ...] = ("Clippy", "rustfmt")
_TOOL_DOCS_URLS: tuple[str, ...] = (
    "https://doc.rust-lang.org/clippy/",
    "https://rust-lang.github.io/rustfmt/",
)


class RustQaSuppressionStrategy:
    """QA suppression strategy for Rust."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    @property
    def forbidden_patterns(self) -> tuple[str, ...]:
        return _FORBIDDEN_PATTERNS

    @property
    def skip_directories(self) -> tuple[str, ...]:
        return _SKIP_DIRECTORIES

    @property
    def tool_names(self) -> tuple[str, ...]:
        return _TOOL_NAMES

    @property
    def tool_docs_urls(self) -> tuple[str, ...]:
        return _TOOL_DOCS_URLS

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Rust QA suppression strategy."""
        from claude_code_hooks_daemon.core import AcceptanceTest, Decision, TestType

        return [
            AcceptanceTest(
                title="Rust QA suppression blocked",
                command=(
                    'Write file_path="/tmp/acceptance-test-qa-rust/example.rs"'
                    ' content="#[' + "allow(" + 'unused_variables)]\\nfn main() {}"'
                ),
                description="Should block Rust QA suppression attribute",
                expected_decision=Decision.DENY,
                expected_message_patterns=["suppression", "BLOCKED", "Rust"],
                test_type=TestType.BLOCKING,
                safety_notes="Uses /tmp path - safe",
                setup_commands=["mkdir -p /tmp/acceptance-test-qa-rust"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-qa-rust"],
            ),
        ]
