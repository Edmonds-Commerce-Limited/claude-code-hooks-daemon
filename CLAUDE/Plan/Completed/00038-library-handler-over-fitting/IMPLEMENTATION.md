# Implementation Guide: Making Handlers Project-Agnostic

This document provides detailed implementation guidance for refactoring handlers to be configuration-driven and multi-language.

## Phase 1: Infrastructure

### 1.1 Configuration Schema Extension

**File**: `src/claude_code_hooks_daemon/config/schema.py` (or new file)

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ProjectPathsConfig:
    """Project-level path configuration for handlers.

    Provides centralized path mapping to avoid hardcoding paths in handlers.
    """
    plan_directory: str = "CLAUDE/Plan"
    test_directory: str = "tests"
    source_directory: str = "src"
    docs_directory: str = "docs"

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectPathsConfig":
        """Create from config dictionary."""
        return cls(
            plan_directory=data.get("plan_directory", cls.plan_directory),
            test_directory=data.get("test_directory", cls.test_directory),
            source_directory=data.get("source_directory", cls.source_directory),
            docs_directory=data.get("docs_directory", cls.docs_directory),
        )
```

**YAML Schema Update**:
```yaml
# .claude/hooks-daemon.yaml
version: 1.0

# NEW: Project-level path mappings
project_paths:
  plan_directory: "CLAUDE/Plan"
  test_directory: "tests"
  source_directory: "src"
  docs_directory: "docs"

# Existing handler configuration...
handlers:
  pre_tool_use:
    tdd_enforcement:
      enabled: true
```

### 1.2 ProjectPaths Utility

**File**: `src/claude_code_hooks_daemon/core/project_paths.py` (new)

```python
"""ProjectPaths - centralized path resolution for handlers."""

from pathlib import Path
from typing import Optional

from claude_code_hooks_daemon.core.project_context import ProjectContext


class ProjectPaths:
    """Centralized project path resolution.

    Provides single source of truth for project directory structure,
    making handlers project-agnostic.
    """

    _config: Optional["ProjectPathsConfig"] = None

    @classmethod
    def initialize(cls, config: "ProjectPathsConfig") -> None:
        """Initialize with configuration.

        Args:
            config: ProjectPathsConfig from YAML
        """
        cls._config = config

    @classmethod
    def get_plan_directory(cls) -> Path:
        """Get plan directory path.

        Returns:
            Absolute path to plan directory
        """
        if cls._config:
            return ProjectContext.project_root() / cls._config.plan_directory
        return ProjectContext.project_root() / "CLAUDE/Plan"  # Default

    @classmethod
    def get_test_directory(cls, language_default: Optional[str] = None) -> Path:
        """Get test directory path.

        Args:
            language_default: Language-specific default (e.g., "." for Go)

        Returns:
            Absolute path to test directory
        """
        if cls._config:
            test_dir = cls._config.test_directory
        elif language_default:
            test_dir = language_default
        else:
            test_dir = "tests"

        return ProjectContext.project_root() / test_dir

    @classmethod
    def get_source_directory(cls) -> Path:
        """Get source directory path.

        Returns:
            Absolute path to source directory
        """
        if cls._config:
            return ProjectContext.project_root() / cls._config.source_directory
        return ProjectContext.project_root() / "src"  # Default

    @classmethod
    def get_docs_directory(cls) -> Path:
        """Get docs directory path.

        Returns:
            Absolute path to docs directory
        """
        if cls._config:
            return ProjectContext.project_root() / cls._config.docs_directory
        return ProjectContext.project_root() / "docs"  # Default

    @classmethod
    def exists(cls, path_type: str) -> bool:
        """Check if a path type exists in the project.

        Args:
            path_type: One of "plan", "test", "source", "docs"

        Returns:
            True if directory exists
        """
        path_map = {
            "plan": cls.get_plan_directory,
            "test": cls.get_test_directory,
            "source": cls.get_source_directory,
            "docs": cls.get_docs_directory,
        }

        getter = path_map.get(path_type)
        if not getter:
            return False

        return getter().exists()
```

### 1.3 Extended LanguageConfig

**File**: `src/claude_code_hooks_daemon/core/language_config.py` (update existing)

```python
@dataclass(frozen=True)
class LanguageConfig:
    """Language-specific configuration."""
    name: str
    extensions: tuple[str, ...]

    # NEW: Test file configuration
    test_file_patterns: tuple[str, ...]  # e.g., ("test_{filename}", "{basename}_test.py")
    test_directory: str  # Default test directory for language

    # Existing fields
    qa_forbidden_patterns: tuple[str, ...]
    qa_tool_names: tuple[str, ...]
    qa_tool_docs_urls: tuple[str, ...]
    skip_directories: tuple[str, ...]


# Updated configs
PYTHON_CONFIG = LanguageConfig(
    name="Python",
    extensions=(".py",),
    test_file_patterns=("test_{filename}", "{basename}_test.py"),  # NEW
    test_directory="tests",  # NEW
    qa_forbidden_patterns=(...),
    # ... rest unchanged
)

GO_CONFIG = LanguageConfig(
    name="Go",
    extensions=(".go",),
    test_file_patterns=("{basename}_test.go",),  # NEW
    test_directory=".",  # NEW - Go colocates tests
    qa_forbidden_patterns=(...),
    # ... rest unchanged
)

# NEW: TypeScript config
TYPESCRIPT_CONFIG = LanguageConfig(
    name="TypeScript",
    extensions=(".ts", ".tsx"),
    test_file_patterns=("{basename}.test.ts", "{basename}.spec.ts", "{basename}.test.tsx", "{basename}.spec.tsx"),
    test_directory="__tests__",  # Jest convention
    qa_forbidden_patterns=(
        r"@ts-ignore",
        r"@ts-nocheck",
        r"@ts-expect-error",
        r"eslint-disable",
    ),
    qa_tool_names=("TypeScript", "ESLint"),
    qa_tool_docs_urls=(
        "https://www.typescriptlang.org/",
        "https://eslint.org/",
    ),
    skip_directories=("node_modules", "dist", "build", "coverage"),
)

# NEW: PHP config (if not exists)
PHP_CONFIG = LanguageConfig(
    name="PHP",
    extensions=(".php",),
    test_file_patterns=("{basename}Test.php",),
    test_directory="tests",
    # ... rest as before
)
```

## Phase 2: TDD Handler Refactoring

### Before (Python-only, hardcoded)

```python
class TddEnforcementHandler(Handler):
    def matches(self, hook_input: dict[str, Any]) -> bool:
        # Only Python files
        if not file_path.endswith(".py"):
            return False

        # Hardcoded test pattern
        if "/tests/" in file_path or filename.startswith("test_"):
            return False

        # Hardcoded source pattern
        return bool("handlers/" in file_path or "/src/" in file_path)

    def _get_test_file_path(self, handler_path: str) -> Path:
        # Hardcoded Python test naming
        test_filename = f"test_{handler_filename}"

        # Hardcoded path structure
        if "claude_code_hooks_daemon" in path_parts:
            workspace_root = Path("/workspace")  # HARDCODED!
            return workspace_root / "tests" / "unit" / "handlers" / event_type / test_filename
```

### After (Multi-language, configurable)

```python
from claude_code_hooks_daemon.core.language_config import get_language_config
from claude_code_hooks_daemon.core.project_paths import ProjectPaths


class TddEnforcementHandler(Handler):
    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is a Write operation to a production file in a supported language."""
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.WRITE:
            return False

        file_path = get_file_path(hook_input)
        if not file_path:
            return False

        # Get language config based on file extension
        lang_config = get_language_config(file_path)
        if not lang_config:
            return False  # Unsupported language

        # Exclude __init__.py and similar
        if Path(file_path).name in ("__init__.py", "__init__.go"):
            return False

        # Check if this is a test file (language-specific patterns)
        if self._is_test_file(file_path, lang_config):
            return False

        # Check if in source directory (configurable)
        source_dir = ProjectPaths.get_source_directory()
        try:
            Path(file_path).relative_to(source_dir)
            return True
        except ValueError:
            # Not in source directory
            return False

    def _is_test_file(self, file_path: str, lang_config: LanguageConfig) -> bool:
        """Check if file is a test file using language-specific patterns.

        Args:
            file_path: Path to check
            lang_config: Language configuration

        Returns:
            True if this is a test file
        """
        filename = Path(file_path).name
        basename = Path(file_path).stem

        # Check against language-specific patterns
        for pattern in lang_config.test_file_patterns:
            # Pattern substitution
            if "{filename}" in pattern:
                expected = pattern.replace("{filename}", filename)
            elif "{basename}" in pattern:
                # Extract extension
                ext = "".join(Path(file_path).suffixes)
                expected = pattern.replace("{basename}", basename) + ext
            else:
                expected = pattern

            if filename == expected or filename.endswith(expected):
                return True

        # Also check if in test directory
        test_dir = ProjectPaths.get_test_directory(lang_config.test_directory)
        try:
            Path(file_path).relative_to(test_dir)
            return True
        except ValueError:
            return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Check if test file exists, deny if not."""
        handler_path = get_file_path(hook_input)
        if not handler_path:
            return HookResult(decision=Decision.ALLOW)

        # Get language config
        lang_config = get_language_config(handler_path)
        if not lang_config:
            return HookResult(decision=Decision.ALLOW)

        # Find test file path
        test_file_path = self._get_test_file_path(handler_path, lang_config)

        # Check if test file exists
        if test_file_path and test_file_path.exists():
            return HookResult(decision=Decision.ALLOW)

        # Build helpful message
        return self._build_denial_message(handler_path, test_file_path, lang_config)

    def _get_test_file_path(
        self, handler_path: str, lang_config: LanguageConfig
    ) -> Optional[Path]:
        """Get expected test file path using language-specific conventions.

        Args:
            handler_path: Path to source file
            lang_config: Language configuration

        Returns:
            Path to expected test file, or None if cannot determine
        """
        filename = Path(handler_path).name
        basename = Path(handler_path).stem
        test_dir = ProjectPaths.get_test_directory(lang_config.test_directory)

        # Try each pattern until we find an existing file
        for pattern in lang_config.test_file_patterns:
            test_filename = self._apply_pattern(filename, basename, pattern)

            # For colocated tests (Go), check same directory
            if lang_config.test_directory == ".":
                test_path = Path(handler_path).parent / test_filename
            else:
                # Mirror source structure in test directory
                try:
                    source_dir = ProjectPaths.get_source_directory()
                    rel_path = Path(handler_path).parent.relative_to(source_dir)
                    test_path = test_dir / rel_path / test_filename
                except ValueError:
                    # Not in source directory, use test dir directly
                    test_path = test_dir / test_filename

            # Return first existing test file
            if test_path.exists():
                return test_path

        # No test file found, return first pattern as expected
        first_pattern = lang_config.test_file_patterns[0]
        test_filename = self._apply_pattern(filename, basename, first_pattern)

        if lang_config.test_directory == ".":
            return Path(handler_path).parent / test_filename
        else:
            try:
                source_dir = ProjectPaths.get_source_directory()
                rel_path = Path(handler_path).parent.relative_to(source_dir)
                return test_dir / rel_path / test_filename
            except ValueError:
                return test_dir / test_filename

    def _apply_pattern(self, filename: str, basename: str, pattern: str) -> str:
        """Apply test file pattern with substitutions.

        Args:
            filename: Full filename (e.g., "auth.py")
            basename: Filename without extension (e.g., "auth")
            pattern: Pattern with placeholders (e.g., "test_{filename}")

        Returns:
            Test filename (e.g., "test_auth.py")
        """
        if "{filename}" in pattern:
            return pattern.replace("{filename}", filename)
        elif "{basename}" in pattern:
            # Keep original extension
            ext = "".join(Path(filename).suffixes)
            return pattern.replace("{basename}", basename) + ext
        else:
            return pattern

    def _build_denial_message(
        self, handler_path: str, test_path: Optional[Path], lang_config: LanguageConfig
    ) -> HookResult:
        """Build helpful denial message with language-specific guidance."""
        handler_filename = Path(handler_path).name
        test_filename = test_path.name if test_path else "test_file"

        # Language-specific test examples
        test_patterns_examples = ", ".join(
            f'"{p}"' for p in lang_config.test_file_patterns[:3]
        )

        return HookResult(
            decision=Decision.DENY,
            reason=(
                f"🚫 TDD REQUIRED: Cannot create {lang_config.name} file without test\n\n"
                f"Source file: {handler_filename}\n"
                f"Missing test: {test_filename}\n\n"
                f"PHILOSOPHY: Test-Driven Development\n"
                f"In TDD, we write the test first, then implement the source.\n\n"
                f"{lang_config.name} TEST CONVENTIONS:\n"
                f"  Test file patterns: {test_patterns_examples}\n"
                f"  Test directory: {lang_config.test_directory or 'colocated with source'}\n\n"
                f"REQUIRED ACTION:\n"
                f"1. Create the test file first:\n"
                f"   {test_path}\n\n"
                f"2. Write comprehensive tests\n"
                f"3. Run tests (they should fail - red)\n"
                f"4. THEN create the source file:\n"
                f"   {handler_path}\n"
                f"5. Run tests again (they should pass - green)\n\n"
                f"See existing test files for examples."
            ),
        )
```

## Phase 3: Plan Handler Refactoring

### ValidatePlanNumberHandler - After

```python
from claude_code_hooks_daemon.core.project_paths import ProjectPaths


class ValidatePlanNumberHandler(Handler):
    def __init__(self) -> None:
        super().__init__(...)
        # Remove hardcoded workspace_root
        # Will use ProjectPaths instead

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if creating a plan folder."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)

        # Get plan directory from config
        plan_dir = ProjectPaths.get_plan_directory()
        plan_dir_str = str(plan_dir.relative_to(ProjectContext.project_root()))

        if tool_name == ToolName.WRITE:
            file_path = get_file_path(hook_input)
            if file_path:
                # Match plan folder creation using configured path
                if re.search(rf"{re.escape(plan_dir_str)}/(\d{{3}})-([^/]+)/", file_path):
                    return True

        # Similar for Bash commands...

    def _get_highest_plan_number(self) -> int:
        """Find highest plan number from both active and completed plans."""
        plan_root = ProjectPaths.get_plan_directory()  # CONFIGURABLE NOW!

        if not plan_root.exists():
            return 0

        # Rest of logic unchanged...
```

### MarkdownOrganizationHandler - After

```python
from claude_code_hooks_daemon.core.project_paths import ProjectPaths


class MarkdownOrganizationHandler(Handler):
    def __init__(self) -> None:
        super().__init__(...)
        # Configuration attributes
        self._allowed_directories: list[str] = []  # Set by registry

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if writing markdown to wrong location."""
        # ... existing checks ...

        # Use configured paths instead of hardcoded
        plan_dir = ProjectPaths.get_plan_directory()
        docs_dir = ProjectPaths.get_docs_directory()
        source_dir = ProjectPaths.get_source_directory()

        normalized = self.normalize_path(file_path)

        # Check against configured allowed directories
        allowed = [
            str(plan_dir.relative_to(ProjectContext.project_root())),
            str(docs_dir.relative_to(ProjectContext.project_root())),
            ".claude/commands",
            "untracked",
        ]

        # Add user-configured directories
        allowed.extend(self._allowed_directories)

        for allowed_path in allowed:
            if normalized.lower().startswith(allowed_path.lower()):
                return False  # Allow

        return True  # Block
```

## Phase 4: QA Handler Refactoring

### Make Skip Directories Configurable

```python
class PythonQaSuppressionBlocker(Handler):
    def __init__(self) -> None:
        super().__init__(...)
        # Configuration attributes (set by registry)
        self._skip_directories: tuple[str, ...] = PYTHON_CONFIG.skip_directories

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if writing Python QA suppression comments."""
        # ... existing checks ...

        # Use configured skip directories instead of hardcoded
        if any(skip in file_path for skip in self._skip_directories):
            return False

        # ... rest unchanged
```

**Configuration:**
```yaml
handlers:
  pre_tool_use:
    python_qa_suppression:
      enabled: true
      skip_directories:
        - "tests/fixtures/"
        - "migrations/"
        - "vendor/"
        - ".venv/"
        - "build/"  # Custom addition
```

## Testing Strategy

### Unit Tests

```python
# tests/unit/core/test_project_paths.py
def test_project_paths_defaults():
    """Test ProjectPaths returns correct defaults."""
    assert ProjectPaths.get_test_directory() == ProjectContext.project_root() / "tests"

def test_project_paths_custom_config():
    """Test ProjectPaths uses custom configuration."""
    config = ProjectPathsConfig(test_directory="spec")
    ProjectPaths.initialize(config)
    assert ProjectPaths.get_test_directory() == ProjectContext.project_root() / "spec"

# tests/unit/handlers/pre_tool_use/test_tdd_enforcement.py
def test_tdd_python_test_pattern():
    """Test Python test file pattern matching."""
    handler = TddEnforcementHandler()
    assert handler._is_test_file("test_auth.py", PYTHON_CONFIG)
    assert handler._is_test_file("auth_test.py", PYTHON_CONFIG)

def test_tdd_go_test_pattern():
    """Test Go test file pattern matching."""
    handler = TddEnforcementHandler()
    assert handler._is_test_file("auth_test.go", GO_CONFIG)
    assert not handler._is_test_file("test_auth.go", GO_CONFIG)

def test_tdd_typescript_test_pattern():
    """Test TypeScript test file pattern matching."""
    handler = TddEnforcementHandler()
    assert handler._is_test_file("auth.test.ts", TYPESCRIPT_CONFIG)
    assert handler._is_test_file("auth.spec.ts", TYPESCRIPT_CONFIG)
```

### Integration Tests

```python
# tests/integration/test_multi_language_tdd.py
def test_python_tdd_enforcement(tmp_path):
    """Test TDD enforcement for Python files."""
    # Setup project structure
    # Test blocking without test file
    # Test allowing with test file

def test_go_tdd_enforcement(tmp_path):
    """Test TDD enforcement for Go files."""
    # Test colocated test files

def test_typescript_tdd_enforcement(tmp_path):
    """Test TDD enforcement for TypeScript files."""
    # Test both .test and .spec patterns
```

## Migration Checklist

- [ ] Phase 1: Infrastructure
  - [ ] Create ProjectPathsConfig dataclass
  - [ ] Create ProjectPaths utility
  - [ ] Extend LanguageConfig with test patterns
  - [ ] Add TypeScript, Rust, Java configs
  - [ ] Update config schema
  - [ ] Write unit tests

- [ ] Phase 2: TDD Handler
  - [ ] Refactor matches() for multi-language
  - [ ] Refactor _get_test_file_path()
  - [ ] Add pattern substitution logic
  - [ ] Update error messages
  - [ ] Write comprehensive tests
  - [ ] Verify 95%+ coverage

- [ ] Phase 3: Plan Handlers
  - [ ] Refactor ValidatePlanNumberHandler
  - [ ] Refactor PlanNumberHelperHandler
  - [ ] Refactor PlanWorkflowHandler
  - [ ] Refactor PlanCompletionAdvisorHandler
  - [ ] Refactor MarkdownOrganizationHandler
  - [ ] Test with custom paths

- [ ] Phase 4: QA Handlers
  - [ ] Make skip_directories configurable
  - [ ] Update all QA blockers
  - [ ] Test with custom skip dirs

- [ ] Phase 5: Documentation
  - [ ] Update CLAUDE.md
  - [ ] Create configuration guide
  - [ ] Add multi-language examples
  - [ ] Update handler development docs

- [ ] Phase 6: Validation
  - [ ] All tests pass
  - [ ] Daemon restarts successfully
  - [ ] This project behavior unchanged
  - [ ] Test with Go project structure
  - [ ] Test with TypeScript project structure
  - [ ] Full QA suite passes

## Success Metrics

- ✅ All 11 handlers use configuration (no hardcoded paths)
- ✅ TDD enforcement supports 5+ languages
- ✅ This project works identically (backward compatible)
- ✅ 95%+ test coverage maintained
- ✅ All QA checks pass
- ✅ Daemon restarts successfully
- ✅ Documentation includes 3+ project type examples
