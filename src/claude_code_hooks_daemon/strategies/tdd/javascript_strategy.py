"""JavaScript/TypeScript TDD strategy implementation."""

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.strategies.tdd.common import (
    is_in_common_test_directory,
    matches_directory,
)
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

# Language-specific constants
_LANGUAGE_NAME = "JavaScript/TypeScript"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-tdd-javascript"
_EXTENSIONS: tuple[str, ...] = (".js", ".jsx", ".ts", ".tsx")
_SOURCE_DIRECTORIES: tuple[str, ...] = ("/src/", "/lib/", "/app/")
_SKIP_DIRECTORIES: tuple[str, ...] = (
    "node_modules/",
    "dist/",
    "build/",
    ".next/",
    "coverage/",
)
_TEST_PATTERNS: tuple[str, ...] = (".test", ".spec")


class JavaScriptTddStrategy:
    """TDD enforcement strategy for JavaScript/TypeScript projects.

    Test convention: helpers.ts -> helpers.test.ts (preserves extension)
    Source directories: /src/, /lib/, /app/
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

        # JS/TS test files match *.test.{ext} or *.spec.{ext}
        for ext in _EXTENSIONS:
            for pattern in _TEST_PATTERNS:
                # Pattern is ".test" or ".spec", ext is ".js" etc.
                # So we check for ".test.js", ".spec.ts", etc.
                if file_path.endswith(f"{pattern}{ext}"):
                    return True
        return False

    def is_production_source(self, file_path: str) -> bool:
        return matches_directory(file_path, _SOURCE_DIRECTORIES)

    def should_skip(self, file_path: str, content: str = "") -> bool:
        return matches_directory(file_path, _SKIP_DIRECTORIES)

    def compute_test_filename(self, source_filename: str) -> str:
        # Preserve the source file's extension
        basename = Path(source_filename).stem
        ext = Path(source_filename).suffix
        return f"{basename}.test{ext}"

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for JavaScript/TypeScript TDD strategy."""

        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        fixture_root = scratch_path(_FIXTURE_DIR)

        return [
            AcceptanceTest(
                title="TDD enforcement for JavaScript/TypeScript source file",
                command=(
                    "Use the Write tool to create file "
                    f"{scratch_path(_FIXTURE_DIR, 'src', 'utils', 'helper.ts')} "
                    "with content 'export function helper() {}'"
                ),
                description="Blocks JavaScript/TypeScript source file creation without corresponding test file",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"BLOCKED \[R-TDD-TEST-FIRST\]",
                    r"JavaScript/TypeScript",
                    r"test file",
                ],
                safety_notes=(
                    "Inside the gitignored scratch directory - safe. Handler blocks "
                    "Write before the file is created."
                ),
                test_type=TestType.BLOCKING,
                setup_commands=[f"mkdir -p {fixture_root}/src/utils"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
