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
from claude_code_hooks_daemon.core.utils import get_file_path
from claude_code_hooks_daemon.strategies.tdd import TddStrategyRegistry
from claude_code_hooks_daemon.strategies.tdd.protocol import TddStrategy

# Path mapping constants for _get_test_file_path
_TEST_DIR = "tests"
_TEST_UNIT_DIR = "unit"
_SRC_DIR = "src"
_DEFAULT_WORKSPACE = "/workspace"


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
        if strategy.should_skip(file_path):
            return False

        if strategy.is_test_file(file_path):
            return False

        return strategy.is_production_source(file_path)

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Check if test file exists, deny if not."""
        source_path = get_file_path(hook_input)
        if not source_path:
            return HookResult(decision=Decision.ALLOW)

        strategy = self._registry.get_strategy(source_path)
        if strategy is None:
            return HookResult(decision=Decision.ALLOW)

        test_file_path = self._get_test_file_path(source_path, strategy)

        # Check if test file exists
        if test_file_path.exists():
            return HookResult(decision=Decision.ALLOW)

        # Test file doesn't exist — block with helpful message
        source_filename = Path(source_path).name
        test_filename = test_file_path.name

        return HookResult(
            decision=Decision.DENY,
            reason=(
                f"TDD REQUIRED: Cannot create {strategy.language_name} source file "
                f"without test file\n\n"
                f"Source file: {source_filename}\n"
                f"Missing test: {test_filename}\n\n"
                f"PHILOSOPHY: Test-Driven Development\n"
                f"In TDD, we write the test first, then implement the code.\n"
                f"This ensures:\n"
                f"  - Clear requirements before coding\n"
                f"  - 100% test coverage from the start\n"
                f"  - Design-focused implementation\n"
                f"  - Prevents untested code in production\n\n"
                f"REQUIRED ACTION:\n"
                f"1. Create the test file first:\n"
                f"   {test_file_path}\n\n"
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

    @staticmethod
    def _map_src_to_test_path(path_parts: tuple[str, ...], test_filename: str) -> Path | None:
        """Map src/{package}/{subdir}/.../file to tests/unit/{subdir}/.../test_file."""
        try:
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
        except (ValueError, IndexError):
            pass
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
