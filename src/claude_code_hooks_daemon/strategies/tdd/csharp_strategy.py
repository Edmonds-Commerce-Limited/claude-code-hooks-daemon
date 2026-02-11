"""C# TDD strategy implementation."""

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.strategies.tdd.common import (
    is_in_common_test_directory,
    matches_directory,
)

# Language-specific constants
_LANGUAGE_NAME = "C#"
_EXTENSIONS: tuple[str, ...] = (".cs",)
_SOURCE_DIRECTORIES: tuple[str, ...] = ("/src/",)
_SKIP_DIRECTORIES: tuple[str, ...] = ("bin/", "obj/", "packages/", ".nuget/")


class CSharpTddStrategy:
    """TDD enforcement strategy for C# projects.

    Test convention: UserService.cs -> UserServiceTests.cs
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

        # C# test files end with "Tests.cs" or "Test.cs"
        path = Path(file_path)
        stem = path.stem
        return (stem.endswith("Tests") or stem.endswith("Test")) and path.suffix == ".cs"

    def is_production_source(self, file_path: str) -> bool:
        return matches_directory(file_path, _SOURCE_DIRECTORIES)

    def should_skip(self, file_path: str) -> bool:
        return matches_directory(file_path, _SKIP_DIRECTORIES)

    def compute_test_filename(self, source_filename: str) -> str:
        basename = source_filename.removesuffix(".cs")
        return f"{basename}Tests.cs"

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for C# TDD strategy."""

        from claude_code_hooks_daemon.core import AcceptanceTest, Decision, TestType

        return [
            AcceptanceTest(
                title="TDD enforcement for C# source file",
                command=(
                    "Use the Write tool to create file "
                    "/tmp/acceptance-test-tdd-csharp/src/Services/UserService.cs "
                    "with content 'namespace MyApp.Services;\\n\\npublic class UserService {}'"
                ),
                description="Blocks C# source file creation without corresponding test file",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"TDD REQUIRED", r"C#", r"test file"],
                safety_notes="Uses /tmp path - safe. Handler blocks Write before file is created.",
                test_type=TestType.BLOCKING,
                setup_commands=["mkdir -p /tmp/acceptance-test-tdd-csharp/src/Services"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-tdd-csharp"],
            ),
        ]
