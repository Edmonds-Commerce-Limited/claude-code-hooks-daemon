"""Java TDD strategy implementation."""

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.strategies.tdd.common import (
    is_in_common_test_directory,
    matches_directory,
)
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

# Language-specific constants
_LANGUAGE_NAME = "Java"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-tdd-java"
_EXTENSIONS: tuple[str, ...] = (".java",)
_SOURCE_DIRECTORIES: tuple[str, ...] = ("/src/main/",)
_SKIP_DIRECTORIES: tuple[str, ...] = ("target/", "build/", ".gradle/", "vendor/")
_TEST_SUFFIX = "Test"


class JavaTddStrategy:
    """TDD enforcement strategy for Java projects.

    Test convention: Service.java -> ServiceTest.java
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

        # Java test files have stem ending with "Test"
        basename = Path(file_path).stem
        return basename.endswith(_TEST_SUFFIX)

    def is_production_source(self, file_path: str) -> bool:
        return matches_directory(file_path, _SOURCE_DIRECTORIES)

    def should_skip(self, file_path: str, content: str = "") -> bool:
        return matches_directory(file_path, _SKIP_DIRECTORIES)

    def compute_test_filename(self, source_filename: str) -> str:
        basename = Path(source_filename).stem
        return f"{basename}Test.java"

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Java TDD strategy."""

        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        fixture_root = scratch_path(_FIXTURE_DIR)

        return [
            AcceptanceTest(
                title="TDD enforcement for Java source file",
                command=(
                    "Use the Write tool to create file "
                    f"{scratch_path(_FIXTURE_DIR, 'src', 'main', 'java', 'com', 'example', 'UserService.java')} "
                    "with content 'package com.example;\\n\\npublic class UserService {}'"
                ),
                description="Blocks Java source file creation without corresponding test file",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED \[R-TDD-TEST-FIRST\]", r"Java", r"test file"],
                safety_notes=(
                    "Inside the gitignored scratch directory - safe. Handler blocks "
                    "Write before file is created."
                ),
                test_type=TestType.BLOCKING,
                setup_commands=[f"mkdir -p {fixture_root}/src/main/java/com/example"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
