"""TddEnforcementHandler - enforces test-first development for production source files.

Uses Strategy Pattern: all language-specific logic is delegated to TddStrategy
implementations. The handler itself has ZERO language awareness.
"""

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_file_content, get_file_path
from claude_code_hooks_daemon.strategies.tdd import TddStrategyRegistry
from claude_code_hooks_daemon.strategies.tdd.protocol import TddStrategy

# Path mapping constants for _get_test_file_path
_TEST_DIR = "tests"
_TEST_UNIT_DIR = "unit"
_SRC_DIR = "src"
_DEFAULT_WORKSPACE = "/workspace"

# Test location style constants (Plan 00076: collocated test support)
_TEST_LOCATION_SEPARATE = "separate"
_TEST_LOCATION_COLLOCATED = "collocated"
_TEST_LOCATION_TEST_SUBDIR = "test_subdir"
_TEST_SUBDIR_NAME = "__tests__"
_DEFAULT_TEST_LOCATIONS = frozenset(
    {_TEST_LOCATION_SEPARATE, _TEST_LOCATION_COLLOCATED, _TEST_LOCATION_TEST_SUBDIR}
)


class TddEnforcementHandler(Handler):
    """Enforce TDD by blocking production file creation without corresponding test file.

    Uses Strategy Pattern: delegates ALL language-specific decisions to TddStrategy
    implementations registered in the TddStrategyRegistry. The handler orchestrates
    the workflow without any knowledge of specific languages.

    Supported languages are determined by registered strategies (currently 11:
    Python, Go, JavaScript/TypeScript, PHP, Rust, Java, C#, Kotlin, Ruby, Swift, Dart).
    Unknown file extensions are allowed through without blocking.

    Configuration options (set via config YAML):
        languages: list[str] | None - Restrict TDD enforcement to specific languages.
            If not set or empty, ALL registered languages are enforced (default).
            Example: ["python", "go", "javascript/typescript"]
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.TDD_ENFORCEMENT,
            priority=Priority.TDD_ENFORCEMENT,
            tags=[
                HandlerTag.TDD,
                HandlerTag.MULTI_LANGUAGE,
                HandlerTag.QA_ENFORCEMENT,
                HandlerTag.BLOCKING,
                HandlerTag.TERMINAL,
            ],
        )
        self._registry = TddStrategyRegistry.create_default()
        # Config option: restrict to specific languages (None = ALL languages)
        # Set by registry via setattr after __init__
        self._languages: list[str] | None = None
        self._languages_applied: bool = False
        # Config option: test location styles to check (None = ALL styles)
        # Set via setattr after __init__ from handler options
        self._test_locations: list[str] | None = None

    def _apply_language_filter(self) -> None:
        """Apply language filter to registry on first use (lazy).

        Config options are set via setattr AFTER __init__, so we must defer
        filtering until first matches()/handle() call. This is idempotent -
        only applies once via the _languages_applied guard.

        Priority: handler-level _languages > project-level _project_languages > ALL
        """
        if self._languages_applied:
            return
        self._languages_applied = True
        # Handler-level override takes priority over project-level default
        effective_languages = self._languages or getattr(self, "_project_languages", None)
        if effective_languages:
            self._registry.filter_by_languages(effective_languages)

    @property
    def _effective_test_locations(self) -> frozenset[str]:
        """Return the active test location styles.

        Returns all 3 styles when _test_locations is None or empty,
        otherwise returns a frozenset of the configured values.
        """
        if not self._test_locations:
            return _DEFAULT_TEST_LOCATIONS
        return frozenset(self._test_locations)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is a Write operation to a production source file.

        Delegates all language-specific checks to the matched strategy:
        - should_skip: vendor, build, node_modules dirs
        - is_test_file: test naming conventions per language
        - is_production_source: source directory conventions per language
        """
        self._apply_language_filter()

        # Only match Write tool
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.WRITE:
            return False

        file_path = get_file_path(hook_input)
        if not file_path:
            return False

        # Find strategy for this file's language
        strategy = self._registry.get_strategy(file_path)
        if strategy is None:
            return False  # Unknown language — allow through

        # Delegate all decisions to strategy (zero language logic here)
        content = get_file_content(hook_input) or ""
        if strategy.should_skip(file_path, content):
            return False

        if strategy.is_test_file(file_path):
            return False

        return strategy.is_production_source(file_path)

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Check if test file exists in ANY valid location, deny if not."""
        source_path = get_file_path(hook_input)
        if not source_path:
            return HookResult(decision=Decision.ALLOW)

        strategy = self._registry.get_strategy(source_path)
        if strategy is None:
            return HookResult(decision=Decision.ALLOW)

        # Get multiple candidate test paths (checks mirror, current, fallback)
        candidate_paths = self._get_test_file_paths(source_path, strategy)

        # Check if ANY candidate exists
        existing_test = next((path for path in candidate_paths if path.exists()), None)
        if existing_test:
            return HookResult(decision=Decision.ALLOW)

        # None exist - block with helpful message showing all searched locations
        source_filename = Path(source_path).name
        test_filename = candidate_paths[0].name  # Show primary candidate

        return HookResult(
            decision=Decision.DENY,
            reason=(
                f"TDD REQUIRED: Cannot create {strategy.language_name} source file "
                f"without test file\n\n"
                f"Source file: {source_filename}\n"
                f"Missing test: {test_filename}\n\n"
                f"Searched locations:\n"
                + "\n".join(f"  - {path}" for path in candidate_paths)
                + "\n\n"
                f"PHILOSOPHY: Test-Driven Development\n"
                f"In TDD, we write the test first, then implement the code.\n"
                f"This ensures:\n"
                f"  - Clear requirements before coding\n"
                f"  - 100% test coverage from the start\n"
                f"  - Design-focused implementation\n"
                f"  - Prevents untested code in production\n\n"
                f"REQUIRED ACTION:\n"
                f"1. Create the test file first at one of these locations:\n"
                f"   {candidate_paths[0]}\n\n"
                f"2. Write comprehensive tests for the module\n"
                f"   - Test public API with various inputs\n"
                f"   - Test edge cases and error conditions\n\n"
                f"3. Run tests (they should fail - red)\n\n"
                f"4. THEN create the source file:\n"
                f"   {source_path}\n\n"
                f"5. Run tests again (they should pass - green)\n\n"
                f"REFERENCE:\n"
                f"  See existing test files in tests/ for examples"
            ),
        )

    def _get_test_file_path(self, source_path: str, strategy: TddStrategy) -> Path:
        """Get the expected test file path for a source file.

        DEPRECATED: Use _get_test_file_paths() (plural) for multi-path detection.

        Uses strategy to compute language-correct test filename.
        Path mapping: src/{package}/{subdir}/.../file -> tests/unit/{subdir}/.../test_file

        The package directory (first dir after src/) is stripped since test directories
        typically don't replicate the package name.
        """
        source_filename = Path(source_path).name
        test_filename = strategy.compute_test_filename(source_filename)

        path_parts = Path(source_path).parts

        # Generic src/-based path mapping
        if _SRC_DIR in path_parts:
            test_path = self._map_src_to_test_path(path_parts, test_filename)
            if test_path is not None:
                return test_path

        # Fallback for non-src/ paths (e.g., controller-based structure)
        return self._map_fallback_test_path(source_path, path_parts, test_filename)

    def _get_test_file_paths(self, source_path: str, strategy: TddStrategy) -> list[Path]:
        """Get ordered list of candidate test file paths for a source file.

        Tries multiple conventions before declaring test missing:
        1. Mirror mapping (tests/ mirrors src/ structure exactly) [separate]
        2. Current mapping (strips package, uses tests/unit/) [separate]
        3. Fallback mapping (controller-relative or parent-relative) [separate]
        4. Collocated (test file next to source file) [collocated]
        5. Test subdirectory (__tests__/ next to source file) [test_subdir]

        Returns paths in priority order (most specific to least specific).
        Controlled by _effective_test_locations config.
        """
        candidates: list[Path] = []
        source_filename = Path(source_path).name
        test_filename = strategy.compute_test_filename(source_filename)
        path_parts = Path(source_path).parts
        effective_locations = self._effective_test_locations

        # Separate test directory strategies (mirror, unit, fallback)
        if _TEST_LOCATION_SEPARATE in effective_locations:
            # Strategy 1: Mirror mapping (PHP PSR-4, Java, etc.)
            if _SRC_DIR in path_parts:
                mirror_path = self._map_src_to_tests_mirror(path_parts, test_filename)
                if mirror_path is not None:
                    candidates.append(mirror_path)

            # Strategy 2: Current mapping (Python convention - strip package)
            if _SRC_DIR in path_parts:
                current_path = self._map_src_to_test_path(path_parts, test_filename)
                if current_path is not None:
                    candidates.append(current_path)

            # Strategy 3: Fallback mapping
            fallback_path = self._map_fallback_test_path(source_path, path_parts, test_filename)
            candidates.append(fallback_path)

        # Collocated: test file next to source file
        if _TEST_LOCATION_COLLOCATED in effective_locations:
            candidates.append(self._map_collocated_test_path(source_path, test_filename))

        # Test subdirectory: __tests__/ next to source file
        if _TEST_LOCATION_TEST_SUBDIR in effective_locations:
            candidates.append(self._map_test_subdir_path(source_path, test_filename))

        return candidates

    @staticmethod
    def _map_src_to_tests_mirror(path_parts: tuple[str, ...], test_filename: str) -> Path | None:
        """Map src/{package}/{subdir}/.../file to tests/{package}/{subdir}/.../test_file.

        Mirrors the FULL src/ structure under tests/ (no package stripping).
        Handles PHP PSR-4, Java standard layout, and other full-mirror conventions.

        Example:
            src/SupFeeds/Logging/DTO/File.php
            -> tests/SupFeeds/Logging/DTO/FileTest.php
        """
        src_idx = path_parts.index(_SRC_DIR)

        # Workspace root is everything before src/
        workspace_parts = path_parts[:src_idx]
        workspace_root = Path(*workspace_parts) if workspace_parts else Path(_DEFAULT_WORKSPACE)

        # Parts after src/: {package}/{subdir}/.../file.ext
        # Keep ALL subdirs (don't strip package)
        after_src = path_parts[src_idx + 1 :]

        if len(after_src) >= 1:
            # after_src[:-1] = ALL subdirectories to mirror (including package)
            # after_src[-1] = filename (replaced with test_filename)
            sub_dirs = after_src[:-1]
            test_file_path = workspace_root / _TEST_DIR
            for sub_dir in sub_dirs:
                test_file_path = test_file_path / sub_dir
            return test_file_path / test_filename
        return None

    @staticmethod
    def _map_src_to_test_path(path_parts: tuple[str, ...], test_filename: str) -> Path | None:
        """Map src/{package}/{subdir}/.../file to tests/unit/{subdir}/.../test_file."""
        src_idx = path_parts.index(_SRC_DIR)

        # Workspace root is everything before src/
        workspace_parts = path_parts[:src_idx]
        workspace_root = Path(*workspace_parts) if workspace_parts else Path(_DEFAULT_WORKSPACE)

        # Parts after src/: {package}/{subdir}/.../file.ext
        after_src = path_parts[src_idx + 1 :]

        if len(after_src) > 2:
            # after_src[0] = package name (skip)
            # after_src[1:-1] = subdirectories to mirror
            # after_src[-1] = filename (replaced with test_filename)
            sub_dirs = after_src[1:-1]
            test_file_path = workspace_root / _TEST_DIR / _TEST_UNIT_DIR
            for sub_dir in sub_dirs:
                test_file_path = test_file_path / sub_dir
            return test_file_path / test_filename
        elif len(after_src) == 2:
            # src/{package}/file.ext -> tests/unit/test_file.ext
            return workspace_root / _TEST_DIR / _TEST_UNIT_DIR / test_filename
        return None

    @staticmethod
    def _map_fallback_test_path(
        source_path: str, path_parts: tuple[str, ...], test_filename: str
    ) -> Path:
        """Fallback path mapping for non-src/ structures."""
        try:
            controller_idx = path_parts.index("controller")
            controller_dir = Path(*path_parts[: controller_idx + 1])
        except ValueError:
            controller_dir = Path(source_path).parent.parent.parent

        return controller_dir / _TEST_DIR / test_filename

    @staticmethod
    def _map_collocated_test_path(source_path: str, test_filename: str) -> Path:
        """Map source file to collocated test path (same directory).

        Example: src/pkg/utils/helpers.ts -> src/pkg/utils/helpers.test.ts
        """
        return Path(source_path).parent / test_filename

    @staticmethod
    def _map_test_subdir_path(source_path: str, test_filename: str) -> Path:
        """Map source file to __tests__/ subdirectory test path.

        Example: src/pkg/utils/helpers.ts -> src/pkg/utils/__tests__/helpers.test.ts
        """
        return Path(source_path).parent / _TEST_SUBDIR_NAME / test_filename

    def get_claude_md(self) -> str | None:
        return (
            "## tdd_enforcement — test file must exist before source file\n\n"
            "Creating a production source file is blocked until a corresponding test file exists.\n\n"
            "**TDD workflow (required)**:\n"
            "1. Create the **test file first** (e.g. `tests/unit/handlers/test_my_handler.py`)\n"
            "2. Write failing tests — RED phase\n"
            "3. Create the source file and implement until tests pass — GREEN phase\n"
            "4. Refactor — REFACTOR phase\n\n"
            "**Supported languages**: Python, Go, JavaScript/TypeScript, PHP, Rust, Java, "
            "C#, Kotlin, Ruby, Swift, Dart\n\n"
            "**Test file locations checked** (any satisfies the block):\n"
            "- Separate mirror: `tests/unit/{subdir}/test_{module}.py`\n"
            "- Collocated: `{source_dir}/{module}.test.ts` (JS/TS projects)\n"
            "- Test subdirectory: `{source_dir}/__tests__/{module}.test.ts`\n\n"
            "**Allowed through without blocking**: vendor dirs, node_modules, build outputs, "
            "generated files, and file extensions not in the supported language list."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests aggregated from all registered strategies."""
        tests: list[Any] = []
        # Collect from all registered strategies
        seen_languages: set[str] = set()
        for strategy in self._registry._strategies.values():
            if strategy.language_name in seen_languages:
                continue
            seen_languages.add(strategy.language_name)
            if hasattr(strategy, "get_acceptance_tests"):
                tests.extend(strategy.get_acceptance_tests())
        return tests
