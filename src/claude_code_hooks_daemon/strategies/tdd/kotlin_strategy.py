"""Kotlin TDD strategy implementation."""

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.strategies.tdd.common import (
    is_in_common_test_directory,
    matches_directory,
)

# Language-specific constants
_LANGUAGE_NAME = "Kotlin"
_EXTENSIONS: tuple[str, ...] = (".kt",)
_SOURCE_DIRECTORIES: tuple[str, ...] = ("/src/main/",)
_SKIP_DIRECTORIES: tuple[str, ...] = ("build/", ".gradle/", "vendor/")


class KotlinTddStrategy:
    """TDD enforcement strategy for Kotlin projects.

    Test convention: Service.kt -> ServiceTest.kt
    Source directories: /src/main/
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

        # Kotlin test files end with "Test.kt"
        path = Path(file_path)
        return path.stem.endswith("Test") and path.suffix == ".kt"

    def is_production_source(self, file_path: str) -> bool:
        return matches_directory(file_path, _SOURCE_DIRECTORIES)

    def should_skip(self, file_path: str) -> bool:
        return matches_directory(file_path, _SKIP_DIRECTORIES)

    def compute_test_filename(self, source_filename: str) -> str:
        basename = source_filename.removesuffix(".kt")
        return f"{basename}Test.kt"

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Kotlin TDD strategy."""

        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="TDD enforcement for Kotlin source file",
                command=(
                    "Use the Write tool to create file "
                    "/tmp/acceptance-test-tdd-kotlin/src/main/kotlin/com/example/UserService.kt "
                    "with content 'package com.example\\n\\nclass UserService'"
                ),
                description="Blocks Kotlin source file creation without corresponding test file",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"TDD REQUIRED", r"Kotlin", r"test file"],
                safety_notes="Uses /tmp path - safe. Handler blocks Write before file is created.",
                test_type=TestType.BLOCKING,
                setup_commands=[
                    "mkdir -p /tmp/acceptance-test-tdd-kotlin/src/main/kotlin/com/example"
                ],
                cleanup_commands=["rm -rf /tmp/acceptance-test-tdd-kotlin"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
