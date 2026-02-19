"""Rust TDD strategy implementation."""

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.strategies.tdd.common import (
    is_in_common_test_directory,
    matches_directory,
)

# Language-specific constants
_LANGUAGE_NAME = "Rust"
_EXTENSIONS: tuple[str, ...] = (".rs",)
_SOURCE_DIRECTORIES: tuple[str, ...] = ("/src/",)
_SKIP_DIRECTORIES: tuple[str, ...] = ("target/", "vendor/")
_TEST_SUFFIX = "_test"


class RustTddStrategy:
    """TDD enforcement strategy for Rust projects.

    Test convention: parser.rs -> parser_test.rs
    Source directories: /src/
    """

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    def is_test_file(self, file_path: str) -> bool:
        if is_in_common_test_directory(file_path):
            return True

        # Rust test files have stem ending with "_test"
        basename = Path(file_path).stem
        return basename.endswith(_TEST_SUFFIX)

    def is_production_source(self, file_path: str) -> bool:
        return matches_directory(file_path, _SOURCE_DIRECTORIES)

    def should_skip(self, file_path: str) -> bool:
        return matches_directory(file_path, _SKIP_DIRECTORIES)

    def compute_test_filename(self, source_filename: str) -> str:
        basename = Path(source_filename).stem
        return f"{basename}_test.rs"

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Rust TDD strategy."""

        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="TDD enforcement for Rust source file",
                command=(
                    "Use the Write tool to create file "
                    "/tmp/acceptance-test-tdd-rust/src/parser.rs "
                    "with content 'pub fn parse() {}'"
                ),
                description="Blocks Rust source file creation without corresponding test file",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"TDD REQUIRED", r"Rust", r"test file"],
                safety_notes="Uses /tmp path - safe. Handler blocks Write before file is created.",
                test_type=TestType.BLOCKING,
                setup_commands=["mkdir -p /tmp/acceptance-test-tdd-rust/src"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-tdd-rust"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
