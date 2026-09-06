"""Ruby TDD strategy implementation."""

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.strategies.tdd.common import (
    is_in_common_test_directory,
    matches_directory,
)
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

# Language-specific constants
_LANGUAGE_NAME = "Ruby"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-tdd-ruby"
_EXTENSIONS: tuple[str, ...] = (".rb",)
_SOURCE_DIRECTORIES: tuple[str, ...] = ("/lib/", "/app/")
_SKIP_DIRECTORIES: tuple[str, ...] = ("vendor/", ".bundle/")


class RubyTddStrategy:
    """TDD enforcement strategy for Ruby projects.

    Test convention: user.rb -> user_spec.rb
    Source directories: /lib/, /app/
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

        # Ruby test files end with "_spec.rb" or "_test.rb"
        path = Path(file_path)
        stem = path.stem
        return (stem.endswith("_spec") or stem.endswith("_test")) and path.suffix == ".rb"

    def is_production_source(self, file_path: str) -> bool:
        return matches_directory(file_path, _SOURCE_DIRECTORIES)

    def should_skip(self, file_path: str, content: str = "") -> bool:
        return matches_directory(file_path, _SKIP_DIRECTORIES)

    def compute_test_filename(self, source_filename: str) -> str:
        basename = source_filename.removesuffix(".rb")
        return f"{basename}_spec.rb"

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Ruby TDD strategy."""

        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        fixture_root = scratch_path(_FIXTURE_DIR)

        return [
            AcceptanceTest(
                title="TDD enforcement for Ruby source file",
                command=(
                    "Use the Write tool to create file "
                    f"{scratch_path(_FIXTURE_DIR, 'lib', 'services', 'user_service.rb')} "
                    "with content 'class UserService\\nend'"
                ),
                description="Blocks Ruby source file creation without corresponding test file",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED \[R-TDD-TEST-FIRST\]", r"Ruby", r"test file"],
                safety_notes=(
                    "Inside the gitignored scratch directory - safe. Handler blocks "
                    "Write before file is created."
                ),
                test_type=TestType.BLOCKING,
                setup_commands=[f"mkdir -p {fixture_root}/lib/services"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
