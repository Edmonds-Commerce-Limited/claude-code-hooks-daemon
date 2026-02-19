"""Swift TDD strategy implementation."""

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.strategies.tdd.common import (
    is_in_common_test_directory,
    matches_directory,
)

# Language-specific constants
_LANGUAGE_NAME = "Swift"
_EXTENSIONS: tuple[str, ...] = (".swift",)
_SOURCE_DIRECTORIES: tuple[str, ...] = ("/Sources/", "/src/")
_SKIP_DIRECTORIES: tuple[str, ...] = (".build/", "Pods/", "Carthage/")


class SwiftTddStrategy:
    """TDD enforcement strategy for Swift projects.

    Test convention: UserService.swift -> UserServiceTests.swift
    Source directories: /Sources/, /src/
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

        # Swift test files end with "Tests.swift"
        path = Path(file_path)
        return path.stem.endswith("Tests") and path.suffix == ".swift"

    def is_production_source(self, file_path: str) -> bool:
        return matches_directory(file_path, _SOURCE_DIRECTORIES)

    def should_skip(self, file_path: str) -> bool:
        return matches_directory(file_path, _SKIP_DIRECTORIES)

    def compute_test_filename(self, source_filename: str) -> str:
        basename = source_filename.removesuffix(".swift")
        return f"{basename}Tests.swift"

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Swift TDD strategy."""

        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="TDD enforcement for Swift source file",
                command=(
                    "Use the Write tool to create file "
                    "/tmp/acceptance-test-tdd-swift/Sources/MyApp/Parser.swift "
                    "with content 'class Parser {}'"
                ),
                description="Blocks Swift source file creation without corresponding test file",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"TDD REQUIRED", r"Swift", r"test file"],
                safety_notes="Uses /tmp path - safe. Handler blocks Write before file is created.",
                test_type=TestType.BLOCKING,
                setup_commands=["mkdir -p /tmp/acceptance-test-tdd-swift/Sources/MyApp"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-tdd-swift"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
