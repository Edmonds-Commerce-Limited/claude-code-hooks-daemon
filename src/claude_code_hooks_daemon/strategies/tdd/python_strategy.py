"""Python TDD strategy implementation."""

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.strategies.tdd.common import (
    is_in_common_test_directory,
    matches_directory,
)
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

# Language-specific constants
_LANGUAGE_NAME = "Python"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-tdd-python"
_EXTENSIONS: tuple[str, ...] = (".py",)
_SOURCE_DIRECTORIES: tuple[str, ...] = ("/src/",)
_SKIP_DIRECTORIES: tuple[str, ...] = (
    "tests/fixtures/",
    "migrations/",
    "vendor/",
    ".venv/",
    "venv/",
)
_INIT_FILENAME = "__init__.py"


class PythonTddStrategy:
    """TDD enforcement strategy for Python projects.

    Test convention: module.py -> test_module.py
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

        # Python test files start with "test_"
        filename = Path(file_path).name
        return filename.startswith("test_") and filename.endswith(".py")

    def is_production_source(self, file_path: str) -> bool:
        # Exclude __init__.py files
        if file_path.endswith(_INIT_FILENAME):
            return False

        return matches_directory(file_path, _SOURCE_DIRECTORIES)

    def should_skip(self, file_path: str, content: str = "") -> bool:
        return matches_directory(file_path, _SKIP_DIRECTORIES)

    def compute_test_filename(self, source_filename: str) -> str:
        return f"test_{source_filename}"

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Python TDD strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        fixture_root = scratch_path(_FIXTURE_DIR)

        return [
            AcceptanceTest(
                title="TDD enforcement for Python source file",
                command=(
                    "Use the Write tool to create file "
                    f"{scratch_path(_FIXTURE_DIR, 'src', 'mypkg', 'utils', 'helper.py')} "
                    "with content 'def helper():\\n    pass'"
                ),
                description="Blocks Python source file creation without corresponding test file",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"BLOCKED \[R-TDD-TEST-FIRST\]",
                    r"Python",
                    r"test file",
                ],
                safety_notes=(
                    "Inside the gitignored scratch directory - safe. Handler blocks "
                    "Write before file is created."
                ),
                test_type=TestType.BLOCKING,
                setup_commands=[f"mkdir -p {fixture_root}/src/mypkg/utils"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
