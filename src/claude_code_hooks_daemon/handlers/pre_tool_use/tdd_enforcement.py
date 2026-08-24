"""TddEnforcementHandler - enforces test-first development for production source files.

Uses Strategy Pattern: all language-specific logic is delegated to TddStrategy
implementations. The handler itself has ZERO language awareness.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.utils import get_file_content, get_file_path
from claude_code_hooks_daemon.strategies.tdd import TddStrategyRegistry
from claude_code_hooks_daemon.strategies.tdd.protocol import TddStrategy
from claude_code_hooks_daemon.utils.path_exclusion import (
    handler_excludes_path,
    path_matches_globs,
    resolve_project_root,
)

logger = logging.getLogger(__name__)

# Path mapping constants for the src->tests path-mapping helpers
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

# `test_path_map` option keys (Plan 00251 Phase 3)
_KEY_SOURCE_GLOB = "source_glob"
_KEY_TEST_DIR = "test_dir"


@dataclass(frozen=True)
class DeclaredTestDir:
    """One ``test_path_map`` entry: sources matching a glob are tested in a directory.

    A project uses this to DECLARE a test root the built-in resolvers cannot
    infer — a layout with no ``src/`` segment, where both mirror resolvers bail
    and the fallback yields a lowercase ``tests/`` that the project's own test
    runner does not scan.

    Declaring is strictly better than excluding: an exclusion turns enforcement
    off for the path, while a declaration keeps the gate ON and only tells it
    where to look.

    Attributes:
        source_glob: Gitignore-style glob selecting the source files this applies
            to, matched with the same dialect as ``exclude_paths`` so a project
            learns one glob syntax rather than two.
        test_dir: Directory holding those files' tests. Project-root-relative, or
            absolute. NOT mirrored — the test filename is placed directly in this
            directory, because that is what a flat PSR-4 test namespace looks
            like. Mirroring is already available for ``src/`` layouts via the
            built-in ``separate`` resolvers.
    """

    source_glob: str
    test_dir: str

    def __post_init__(self) -> None:
        """FAIL FAST on a meaningless mapping.

        This is the TRUSTED construction path; untrusted YAML goes through
        :func:`_parse_test_path_map`, which degrades gracefully and RELIES on this
        check rather than duplicating it (the same split as ``command_hints``).
        """
        if not self.source_glob:
            raise ValueError("DeclaredTestDir requires a non-empty source_glob")
        if not self.test_dir:
            raise ValueError("DeclaredTestDir requires a non-empty test_dir")


def _parse_test_path_map(raw: Any) -> list[DeclaredTestDir]:
    """Parse the raw ``options.test_path_map`` config value.

    External config is validated defensively and degrades gracefully: a malformed
    entry is logged and skipped, never raised, so one bad line in a project's
    YAML cannot disable TDD enforcement wholesale. That matters more here than in
    an advisory handler — this one DENIES — but the failure stays visible where
    the author is already looking, because the deny message lists every location
    that WAS searched, and a mapping that did not take is conspicuous by its
    absence from that list.
    """
    if not raw:
        return []
    if not isinstance(raw, list):
        logger.warning("tdd_enforcement: 'test_path_map' option must be a list; ignoring")
        return []

    parsed: list[DeclaredTestDir] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            logger.warning("tdd_enforcement: test_path_map[%d] is not a mapping; skipped", index)
            continue
        source_glob = str(entry.get(_KEY_SOURCE_GLOB, "") or "").strip()
        test_dir = str(entry.get(_KEY_TEST_DIR, "") or "").strip()
        if not source_glob or not test_dir:
            logger.warning(
                "tdd_enforcement: test_path_map[%d] missing required %s/%s; skipped",
                index,
                _KEY_SOURCE_GLOB,
                _KEY_TEST_DIR,
            )
            continue
        parsed.append(DeclaredTestDir(source_glob=source_glob, test_dir=test_dir))
    return parsed


class TddEnforcementHandler(PreToolUseHandlerBase):
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
        # Config option: glob patterns exempted from TDD enforcement entirely.
        # Set via setattr after __init__ from handler options; unions with the
        # project-wide daemon.exclude_paths the registry injects (Plan 00251).
        self._exclude_paths: list[str] | None = None
        # Config option: declared source-glob -> test-dir mappings for layouts no
        # resolver can infer (Plan 00251). Typed `Any` deliberately: this is raw
        # YAML the daemon does not control, and `_parse_test_path_map` handles a
        # value that is not even a list — a narrower annotation here would be the
        # same kind of lie Phase 1 removed from `core/handler.py`.
        self._test_path_map: Any = None
        self._resolved_test_path_map: list[DeclaredTestDir] | None = None

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
        effective_languages = self._languages or self._project_languages
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

        # A project may exempt a path from TDD enforcement entirely (Plan 00251,
        # the follow-up Plan 00150's Non-Goals deferred). Checked BEFORE the
        # strategy lookup: an exclusion is the project stating this path is out of
        # scope, which is a stronger statement than any per-language judgement and
        # must not depend on a strategy existing for the extension.
        if handler_excludes_path(
            file_path,
            handler_patterns=self._exclude_paths,
            project_patterns=self._project_exclude_paths,
        ):
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

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Check if test file exists in ANY valid location, deny if not."""
        source_path = get_file_path(hook_input)
        if not source_path:
            return GatingResult(decision=Decision.ALLOW)

        strategy = self._registry.get_strategy(source_path)
        if strategy is None:
            return GatingResult(decision=Decision.ALLOW)

        # Get multiple candidate test paths (checks mirror, current, fallback)
        candidate_paths = self._get_test_file_paths(source_path, strategy)

        # Check if ANY candidate exists
        existing_test = next((path for path in candidate_paths if path.exists()), None)
        if existing_test:
            return GatingResult(decision=Decision.ALLOW)

        # None exist - block with helpful message showing all searched locations
        source_filename = Path(source_path).name
        test_filename = candidate_paths[0].name  # Show primary candidate

        return GatingResult(
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

        # Declared mappings first: a project stating where its tests live is a
        # FACT, and it outranks every inferred candidate. Deliberately NOT gated
        # on _effective_test_locations — that option selects among the three
        # INFERENCE styles below, so gating a declaration behind it would mean a
        # project setting `test_locations: ["collocated"]` silently lost its own
        # declared test root (Plan 00251).
        candidates.extend(self._map_declared_test_paths(source_path, test_filename))

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

    def _declared_test_dirs(self) -> list[DeclaredTestDir]:
        """Parse ``test_path_map`` once, lazily.

        Config options are injected via setattr AFTER ``__init__``, so parsing
        cannot happen in the constructor; and the value is re-read on every
        ``handle()``, so it must not be re-parsed each time.
        """
        if self._resolved_test_path_map is None:
            self._resolved_test_path_map = _parse_test_path_map(self._test_path_map)
        return self._resolved_test_path_map

    def _map_declared_test_paths(self, source_path: str, test_filename: str) -> list[Path]:
        """Candidate test paths from the project's declared ``test_path_map``.

        Each matching mapping contributes exactly one candidate — the test
        filename placed FLAT in the declared directory, not mirrored under it.
        Returns them in config order, so a project controls which of several
        matching declarations the deny message suggests first.
        """
        mappings = self._declared_test_dirs()
        if not mappings:
            return []

        project_root = resolve_project_root()
        candidates: list[Path] = []
        for mapping in mappings:
            if not path_matches_globs(
                source_path, [mapping.source_glob], project_root=project_root
            ):
                continue
            test_dir = Path(mapping.test_dir)
            if not test_dir.is_absolute():
                if project_root is None:
                    # Nothing to anchor a relative dir against. Degrade to the
                    # inferred candidates rather than guessing a root — a guessed
                    # root would produce a path that silently never exists, which
                    # reads as "your test is missing" rather than "your mapping
                    # could not be resolved".
                    logger.warning(
                        "tdd_enforcement: test_path_map test_dir %r is relative but the "
                        "project root is unresolvable; skipped",
                        mapping.test_dir,
                    )
                    continue
                test_dir = Path(project_root) / test_dir
            candidates.append(test_dir / test_filename)
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
            "Creating a production source file with `Write` is blocked until a "
            "corresponding test file exists.\n\n"
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
            "**The deny message lists every location it searched.** If your project's real "
            "test directory is not in that list, no amount of retrying will satisfy the gate "
            "— the project needs to DECLARE the directory (below), not move the test.\n\n"
            "**A layout the resolvers cannot infer is declarable** via "
            "`handlers.pre_tool_use.tdd_enforcement.options.test_path_map` — a list of "
            "`{source_glob, test_dir}` entries. `test_dir` is project-root-relative (or "
            "absolute) and FLAT: the test filename is placed directly in it, not mirrored "
            "under it. This keeps enforcement ON and is the preferred fix, because a test "
            "that exists is worth more than an exemption:\n\n"
            "```yaml\n"
            "test_path_map:\n"
            '  - source_glob: "**/qaConfig/PHPStan/Rules/**"\n'
            '    test_dir: "apps/app/qaConfig/Tests"\n'
            "```\n\n"
            "**A path can also be exempted entirely** via that handler's `exclude_paths` "
            "option or the project-wide `daemon.exclude_paths` — additive gitignore-style "
            "globs. Prefer `test_path_map`: excluding turns the gate OFF for those files.\n\n"
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
