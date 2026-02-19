"""PHP TDD strategy implementation."""

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.strategies.tdd.common import (
    is_in_common_test_directory,
    matches_directory,
)

# Language-specific constants
_LANGUAGE_NAME = "PHP"
_EXTENSIONS: tuple[str, ...] = (".php",)
_SOURCE_DIRECTORIES: tuple[str, ...] = ("/src/", "/app/")
_SKIP_DIRECTORIES: tuple[str, ...] = ("tests/fixtures/", "vendor/")
_TEST_SUFFIX = "Test"


class PhpTddStrategy:
    """TDD enforcement strategy for PHP projects.

    Test convention: UserController.php -> UserControllerTest.php
    Source directories: /src/, /app/
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

        # PHP test files have stem ending with "Test"
        basename = Path(file_path).stem
        return basename.endswith(_TEST_SUFFIX)

    def is_production_source(self, file_path: str) -> bool:
        return matches_directory(file_path, _SOURCE_DIRECTORIES)

    def should_skip(self, file_path: str) -> bool:
        return matches_directory(file_path, _SKIP_DIRECTORIES)

    def compute_test_filename(self, source_filename: str) -> str:
        basename = Path(source_filename).stem
        return f"{basename}Test.php"

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for PHP TDD strategy."""

        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="TDD enforcement for PHP source file",
                command=(
                    "Use the Write tool to create file "
                    "/tmp/acceptance-test-tdd-php/src/Services/UserService.php "
                    "with content '<?php\\n\\nclass UserService {}'"
                ),
                description="Blocks PHP source file creation without corresponding test file",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"TDD REQUIRED", r"PHP", r"test file"],
                safety_notes="Uses /tmp path - safe. Handler blocks Write before file is created.",
                test_type=TestType.BLOCKING,
                setup_commands=["mkdir -p /tmp/acceptance-test-tdd-php/src/Services"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-tdd-php"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
