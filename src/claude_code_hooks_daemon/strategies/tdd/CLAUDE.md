# TDD Strategy Pattern - Archetype Documentation

**Status**: Reference Architecture
**Pattern**: Strategy Pattern (GoF) with Protocol interface
**Purpose**: Language-specific TDD enforcement with zero coupling to the handler

This module is the **canonical archetype** for all language-aware strategy implementations in the hooks daemon. Any future handler that needs language-specific behavior MUST follow this pattern exactly.

---

## Architecture Overview

```
TddEnforcementHandler (Orchestrator)
    │
    │  Zero language logic. Pure workflow.
    │
    ├── TddStrategyRegistry (Lookup)
    │       │
    │       │  Maps file extensions → strategy instances
    │       │
    │       └── TddStrategy (Protocol Interface)
    │               │
    │               │  Contract: 7 methods, structural typing
    │               │
    │               ├── PythonTddStrategy
    │               ├── GoTddStrategy
    │               ├── JavaScriptTddStrategy  (covers JS + TS)
    │               ├── PhpTddStrategy
    │               ├── RustTddStrategy
    │               ├── JavaTddStrategy
    │               ├── CSharpTddStrategy
    │               ├── KotlinTddStrategy
    │               ├── RubyTddStrategy
    │               ├── SwiftTddStrategy
    │               └── DartTddStrategy
    │
    └── common.py (DRY Utilities)
            │
            ├── COMMON_TEST_DIRECTORIES  (shared constant)
            ├── is_in_common_test_directory()
            └── matches_directory()
```

### Separation of Concerns (SOLID)

| Component | Responsibility | Knows About Languages? |
|-----------|---------------|----------------------|
| **Handler** | Orchestrates workflow (matches → handle → test path) | NO |
| **Protocol** | Defines the contract all strategies must satisfy | NO |
| **Registry** | Maps extensions to strategy instances | NO (data-driven) |
| **Strategy** | ALL language-specific logic for one language | YES (its own only) |
| **Common** | Shared utilities used by multiple strategies | NO |
| **LanguageConfig** | Pure config data (names, extensions) | N/A (data only) |

---

## The Protocol (Interface Contract)

```python
@runtime_checkable
class TddStrategy(Protocol):
    @property
    def language_name(self) -> str: ...

    @property
    def extensions(self) -> tuple[str, ...]: ...

    def is_test_file(self, file_path: str) -> bool: ...

    def is_production_source(self, file_path: str) -> bool: ...

    def should_skip(self, file_path: str) -> bool: ...

    def compute_test_filename(self, source_filename: str) -> str: ...

    def get_acceptance_tests(self) -> list[Any]: ...
```

### Why Protocol, Not ABC?

| Feature | Protocol (chosen) | ABC |
|---------|-------------------|-----|
| Typing | Structural (duck typing) | Nominal (inheritance) |
| Coupling | Zero - no base class import needed | Tight - must inherit |
| Testing | Any object satisfying shape works | Must subclass ABC |
| Runtime check | `@runtime_checkable` + `isinstance()` | `isinstance()` |
| Python idiom | Pythonic, modern (PEP 544) | Traditional OOP |

**Decision**: Protocol enables true Open/Closed Principle. New strategies need zero imports from the framework - they just need to match the shape.

### Method Contract Details

#### `language_name: str` (property)
- Human-readable name for error messages (e.g., `"Python"`, `"JavaScript/TypeScript"`)
- Used in TDD denial messages shown to the developer
- Must be stable - changing it changes user-facing output

#### `extensions: tuple[str, ...]` (property)
- File extensions this strategy handles (e.g., `(".py",)`, `(".js", ".jsx", ".ts", ".tsx")`)
- Must include the dot prefix
- Must be lowercase
- Used by Registry for extension-to-strategy mapping
- One strategy can handle multiple extensions (JS/TS pattern)

#### `is_test_file(file_path: str) -> bool`
- Returns `True` if the file IS a test file (should be allowed through)
- MUST check common test directories via `is_in_common_test_directory()`
- MUST check language-specific naming patterns (e.g., `test_*.py`, `*_test.go`)
- Called by handler's `matches()` to skip test files

#### `is_production_source(file_path: str) -> bool`
- Returns `True` if the file is in a production source directory
- Checks language-specific source directory conventions (e.g., `/src/`, `/lib/`, `/app/`)
- Should exclude language-specific init/config files (e.g., Python's `__init__.py`)
- Called by handler's `matches()` to identify files that need TDD enforcement

#### `should_skip(file_path: str) -> bool`
- Returns `True` if the file should be skipped entirely (no TDD enforcement)
- Checks for vendor dirs, build output, virtual environments, etc.
- Called by handler's `matches()` before any other checks

#### `compute_test_filename(source_filename: str) -> str`
- Takes a source filename (not full path), returns expected test filename
- Language-specific transformation:
  - Python: `module.py` -> `test_module.py`
  - Go: `server.go` -> `server_test.go`
  - JS/TS: `helpers.ts` -> `helpers.test.ts`
  - PHP: `UserService.php` -> `UserServiceTest.php`
  - Java: `UserService.java` -> `UserServiceTest.java`
  - Rust: `parser.rs` -> `parser_test.rs`
  - C#: `UserService.cs` -> `UserServiceTests.cs`
  - Kotlin: `UserService.kt` -> `UserServiceTest.kt`
  - Ruby: `user_service.rb` -> `user_service_spec.rb`
  - Swift: `Parser.swift` -> `ParserTests.swift`
  - Dart: `parser.dart` -> `parser_test.dart`
- Used by handler to construct the expected test file path

#### `get_acceptance_tests(self) -> list[Any]` (MANDATORY)
- Returns a list of `AcceptanceTest` instances for this language
- MUST return at least one test (enforced by QA checker)
- Tests should be BLOCKING type (expected_decision=Decision.DENY)
- Tests use `/tmp/acceptance-test-tdd-{language}/` paths for safety
- Must include `setup_commands` (create temp dirs) and `cleanup_commands` (remove them)
- `expected_message_patterns` MUST include the exact `language_name` string
- Handler aggregates tests from all strategies via `get_acceptance_tests()`
- See existing strategies for examples

---

## Acceptance Test Provision (MANDATORY)

Every strategy MUST provide acceptance tests. This is enforced by:
1. **Protocol contract**: `get_acceptance_tests()` is part of the TddStrategy Protocol
2. **Unit tests**: `test_acceptance_tests.py` validates all 11 strategies provide valid tests
3. **QA checker**: `strategy_pattern_checker.py` AST-checks for missing `get_acceptance_tests()`

### How It Works

```
Strategy (provides tests)     Handler (aggregates)      Playbook (executes)
┌─────────────────────┐      ┌──────────────────┐      ┌─────────────────┐
│ PythonTddStrategy   │─────▶│                  │      │                 │
│ GoTddStrategy       │─────▶│ TddEnforcement   │─────▶│ Acceptance Test │
│ JavaScriptStrategy  │─────▶│ Handler          │      │ Runner          │
│ ... (11 total)      │─────▶│ .get_acceptance  │      │ (Haiku agents)  │
│                     │      │  _tests()        │      │                 │
└─────────────────────┘      └──────────────────┘      └─────────────────┘
  Each returns 1+ test         Collects & dedupes        Runs in parallel
```

### AcceptanceTest Structure

```python
from claude_code_hooks_daemon.core import AcceptanceTest, Decision, TestType

AcceptanceTest(
    title="TDD Enforcement - {Language} source without test",
    command='Write file_path="/tmp/acceptance-test-tdd-{lang}/src/pkg/example.{ext}" content="..."',
    description="Should block creating {Language} source file without test",
    expected_decision=Decision.DENY,
    expected_message_patterns=["TDD REQUIRED", "{Language}", "test file"],
    test_type=TestType.BLOCKING,
    safety_notes="Uses /tmp path, cleaned up after test",
    setup_commands=["mkdir -p /tmp/acceptance-test-tdd-{lang}/src/pkg"],
    cleanup_commands=["rm -rf /tmp/acceptance-test-tdd-{lang}"],
)
```

### Rules

1. **Every strategy provides its own tests** - strategies own their test definitions
2. **Handler is a thin aggregator** - collects from all strategies, adds nothing of its own
3. **No duplicate languages** - handler deduplicates by `language_name`
4. **Tests use safe paths** - `/tmp/` only, with cleanup commands
5. **Patterns include language name** - exact match for deduplication verification

---

## Strategy Implementation Pattern

Every strategy follows this exact structure. No exceptions.

### Template

```python
"""[Language] TDD strategy implementation."""

from pathlib import Path  # Only if needed for stem/name operations

from claude_code_hooks_daemon.strategies.tdd.common import (
    is_in_common_test_directory,
    matches_directory,
)

# ── Language-specific constants (NO MAGIC STRINGS) ──────────────
_LANGUAGE_NAME = "[Language]"
_EXTENSIONS: tuple[str, ...] = (".[ext]",)
_SOURCE_DIRECTORIES: tuple[str, ...] = ("/src/",)
_SKIP_DIRECTORIES: tuple[str, ...] = ("vendor/",)

# Any additional constants specific to this language
# e.g., _INIT_FILENAME, _TEST_SUFFIX, _TEST_PREFIX


class [Language]TddStrategy:
    """TDD enforcement strategy for [Language] projects.

    Test convention: source.[ext] -> [test pattern]
    Source directories: [list]
    """

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    def is_test_file(self, file_path: str) -> bool:
        # ALWAYS check common directories first (DRY)
        if is_in_common_test_directory(file_path):
            return True

        # Then check language-specific naming pattern
        ...

    def is_production_source(self, file_path: str) -> bool:
        # Exclude init/config files if applicable
        ...

        # Check source directories
        return matches_directory(file_path, _SOURCE_DIRECTORIES)

    def should_skip(self, file_path: str) -> bool:
        return matches_directory(file_path, _SKIP_DIRECTORIES)

    def compute_test_filename(self, source_filename: str) -> str:
        # Language-specific transformation
        ...

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import AcceptanceTest, Decision, TestType
        return [
            AcceptanceTest(
                title="TDD Enforcement - [Language] source without test",
                command='Write file_path="/tmp/acceptance-test-tdd-[lang]/src/pkg/example.[ext]" content="..."',
                description="Should block creating [Language] source without test",
                expected_decision=Decision.DENY,
                expected_message_patterns=["TDD REQUIRED", _LANGUAGE_NAME, "test file"],
                test_type=TestType.BLOCKING,
                safety_notes="Uses /tmp path, cleaned up after test",
                setup_commands=["mkdir -p /tmp/acceptance-test-tdd-[lang]/src/pkg"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-tdd-[lang]"],
            )
        ]
```

### Rules

1. **ALL strings are named constants** - Module-level, prefixed with `_`
2. **Always use `common.is_in_common_test_directory()`** in `is_test_file()` - DRY
3. **Always use `common.matches_directory()`** for directory matching - DRY
4. **No imports from other strategies** - Each strategy is fully independent
5. **No imports from the handler** - Strategies know nothing about handlers
6. **No imports from LanguageConfig** - Config is config, strategy is behavior (SRP)
7. **Class does NOT inherit from anything** - Protocol is structural, not nominal
8. **One file per language** - Named `{language}_strategy.py`

---

## Registry

The `TddStrategyRegistry` is a simple extension-to-strategy map:

```python
registry = TddStrategyRegistry()
registry.register(PythonTddStrategy())  # Registers ".py"
registry.register(GoTddStrategy())      # Registers ".go"

strategy = registry.get_strategy("/workspace/src/app/server.go")
# Returns GoTddStrategy instance (matched ".go")

strategy = registry.get_strategy("/workspace/README.md")
# Returns None (no strategy for ".md")
```

### `create_default()` Factory

The `create_default()` class method creates a registry with ALL built-in strategies. This is the standard entry point used by the handler.

**Adding a new strategy**: Add one line to `create_default()`:
```python
registry.register(NewLanguageTddStrategy())
```

---

## Shared Utilities (DRY)

`common.py` contains logic used by multiple strategies:

### `COMMON_TEST_DIRECTORIES`
```python
COMMON_TEST_DIRECTORIES: tuple[str, ...] = (
    "/tests/",
    "/test/",
    "/__tests__/",
    "/spec/",
)
```
Cross-language test directory names. Every strategy's `is_test_file()` checks these first.

### `is_in_common_test_directory(file_path: str) -> bool`
Quick check if a file is in any common test directory. Called by ALL strategies in `is_test_file()`.

### `matches_directory(file_path: str, directories: tuple[str, ...]) -> bool`
Generic directory pattern matcher. Handles normalization (leading `/`, trailing `/`). Used by strategies for both `is_production_source()` and `should_skip()`.

### When to Add to Common vs Strategy

| Logic | Where | Why |
|-------|-------|-----|
| Test directory names used by 3+ languages | `common.py` | DRY |
| Directory matching utility | `common.py` | DRY |
| Test filename pattern (e.g., `test_*.py`) | Strategy | Language-specific |
| Source directory list (e.g., `/src/main/`) | Strategy | Language-specific |
| Skip directory list (e.g., `vendor/`) | Strategy | Language-specific |
| Init file exclusion (e.g., `__init__.py`) | Strategy | Language-specific |

**Rule**: If 3+ strategies share the same logic, extract to `common.py`. Otherwise keep it in the strategy.

---

## How to Add a New Language

### Step-by-Step (TDD)

#### 1. Create the test file FIRST

```bash
# File: tests/unit/strategies/tdd/test_{language}_strategy.py
```

Write comprehensive tests covering:

```python
"""Tests for {Language} TDD strategy."""

import pytest

from claude_code_hooks_daemon.strategies.tdd.{language}_strategy import {Language}TddStrategy


@pytest.fixture
def strategy() -> {Language}TddStrategy:
    return {Language}TddStrategy()


class TestProperties:
    def test_language_name(self, strategy: {Language}TddStrategy) -> None:
        assert strategy.language_name == "{Language}"

    def test_extensions(self, strategy: {Language}TddStrategy) -> None:
        assert strategy.extensions == (".[ext]",)


class TestIsTestFile:
    def test_common_test_directory(self, strategy: {Language}TddStrategy) -> None:
        assert strategy.is_test_file("/workspace/tests/foo.[ext]") is True

    def test_language_specific_pattern(self, strategy: {Language}TddStrategy) -> None:
        assert strategy.is_test_file("/workspace/src/test_foo.[ext]") is True

    def test_production_file(self, strategy: {Language}TddStrategy) -> None:
        assert strategy.is_test_file("/workspace/src/foo.[ext]") is False


class TestIsProductionSource:
    def test_in_source_directory(self, strategy: {Language}TddStrategy) -> None:
        assert strategy.is_production_source("/workspace/src/foo.[ext]") is True

    def test_outside_source(self, strategy: {Language}TddStrategy) -> None:
        assert strategy.is_production_source("/workspace/foo.[ext]") is False


class TestShouldSkip:
    def test_vendor_directory(self, strategy: {Language}TddStrategy) -> None:
        assert strategy.should_skip("/workspace/vendor/foo.[ext]") is True

    def test_normal_path(self, strategy: {Language}TddStrategy) -> None:
        assert strategy.should_skip("/workspace/src/foo.[ext]") is False


class TestComputeTestFilename:
    def test_standard_file(self, strategy: {Language}TddStrategy) -> None:
        assert strategy.compute_test_filename("foo.[ext]") == "[expected_test_name]"
```

#### 2. Run tests - they MUST FAIL

```bash
pytest tests/unit/strategies/tdd/test_{language}_strategy.py -v
# Expected: ImportError (no implementation yet)
```

#### 3. Create the strategy implementation

```bash
# File: src/claude_code_hooks_daemon/strategies/tdd/{language}_strategy.py
```

Follow the template above exactly.

#### 4. Run tests - they MUST PASS

```bash
pytest tests/unit/strategies/tdd/test_{language}_strategy.py -v
# Expected: ALL PASS
```

#### 5. Register in the Registry

Edit `registry.py`:

```python
# In create_default():
from claude_code_hooks_daemon.strategies.tdd.{language}_strategy import {Language}TddStrategy

registry.register({Language}TddStrategy())
```

#### 6. Update registry tests

Edit `tests/unit/strategies/tdd/test_registry.py`:
- Add language to `test_create_default_registers_all_languages` expected list
- Add extension test case to `test_get_strategy_returns_correct_strategy`

#### 7. Run full QA

```bash
./scripts/qa/run_all.sh
# Expected: ALL CHECKS PASSED
```

#### 8. Restart daemon

```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
# Expected: RUNNING
```

---

## Registered Languages (11 total)

| Language | Strategy Class | Extensions | Test Pattern | Source Dirs |
|----------|---------------|------------|-------------|-------------|
| Python | `PythonTddStrategy` | `.py` | `test_*.py` | `/src/` |
| Go | `GoTddStrategy` | `.go` | `*_test.go` | `/src/`, `/cmd/`, `/pkg/`, `/internal/` |
| JavaScript/TypeScript | `JavaScriptTddStrategy` | `.js`, `.jsx`, `.ts`, `.tsx` | `*.test.*`, `*.spec.*` | `/src/`, `/lib/`, `/app/` |
| PHP | `PhpTddStrategy` | `.php` | `*Test.php` | `/src/`, `/app/` |
| Rust | `RustTddStrategy` | `.rs` | `*_test.rs` | `/src/` |
| Java | `JavaTddStrategy` | `.java` | `*Test.java` | `/src/main/` |
| C# | `CSharpTddStrategy` | `.cs` | `*Tests.cs`, `*Test.cs` | `/src/` |
| Kotlin | `KotlinTddStrategy` | `.kt` | `*Test.kt` | `/src/main/` |
| Ruby | `RubyTddStrategy` | `.rb` | `*_spec.rb`, `*_test.rb` | `/lib/`, `/app/` |
| Swift | `SwiftTddStrategy` | `.swift` | `*Tests.swift` | `/Sources/`, `/src/` |
| Dart | `DartTddStrategy` | `.dart` | `*_test.dart` | `/lib/` |

---

## Design Principles Applied

### SOLID

- **S** (Single Responsibility): Each strategy handles exactly one language. Handler handles only workflow. Registry handles only lookup. Common handles only shared utilities.
- **O** (Open/Closed): Adding a language = adding a file + one registry line. Zero changes to handler, protocol, common, or other strategies.
- **L** (Liskov Substitution): Every strategy is substitutable through the Protocol. Handler calls the same 6 methods regardless of language.
- **I** (Interface Segregation): The Protocol has exactly 7 methods - no more. Every strategy uses all 7.
- **D** (Dependency Inversion): Handler depends on Protocol (abstraction), not on any concrete strategy class.

### DRY

- Common test directories defined once in `common.py`
- Directory matching logic defined once in `matches_directory()`
- Handler path mapping logic defined once (not per-language)

### NO MAGIC

- Every string literal is a named constant (`_LANGUAGE_NAME`, `_EXTENSIONS`, `_SOURCE_DIRECTORIES`, etc.)
- Module-level constants prefixed with `_` (private to module)
- Handler path constants also extracted (`_TEST_DIR`, `_TEST_UNIT_DIR`, `_SRC_DIR`)

### YAGNI

- No abstract base class (Protocol is sufficient)
- No config-driven strategy loading (create_default() is simple and explicit)
- No strategy caching (strategies are lightweight, stateless)
- No lazy loading (all strategies registered eagerly - they're cheap)

### FAIL FAST

- `get_strategy()` returns `None` for unknown extensions - handler allows through (no silent failure)
- `@runtime_checkable` Protocol enables isinstance validation if needed
- Missing strategy methods cause immediate `TypeError` at call site

---

## Anti-Patterns to Avoid

### DO NOT put language logic in the handler

```python
# WRONG - handler knows about Python
if file_path.endswith(".py"):
    test_name = f"test_{filename}"

# RIGHT - handler delegates to strategy
test_name = strategy.compute_test_filename(filename)
```

### DO NOT use if/elif chains for languages

```python
# WRONG - God method with language awareness
if config.name == "python":
    ...
elif config.name == "go":
    ...

# RIGHT - Strategy lookup via registry
strategy = registry.get_strategy(file_path)
strategy.is_test_file(file_path)
```

### DO NOT import between strategies

```python
# WRONG - coupling between strategies
from claude_code_hooks_daemon.strategies.tdd.python_strategy import _SOURCE_DIRECTORIES

# RIGHT - use common.py for shared logic
from claude_code_hooks_daemon.strategies.tdd.common import matches_directory
```

### DO NOT use magic strings

```python
# WRONG
if "/src/" in file_path:

# RIGHT
_SOURCE_DIRECTORIES: tuple[str, ...] = ("/src/",)
return matches_directory(file_path, _SOURCE_DIRECTORIES)
```

### DO NOT inherit from a base class

```python
# WRONG - nominal typing, tight coupling
class PythonTddStrategy(BaseTddStrategy):
    ...

# RIGHT - structural typing, zero coupling
class PythonTddStrategy:  # Just satisfies Protocol shape
    ...
```

---

## Applying This Pattern to Other Handlers

This TDD strategy is the archetype. Future language-aware handlers (e.g., linting enforcement, import validation, naming conventions) MUST follow the same structure:

1. **Define a Protocol** in `strategies/{domain}/protocol.py`
2. **Create shared utilities** in `strategies/{domain}/common.py`
3. **Implement one strategy per language** in `strategies/{domain}/{language}_strategy.py`
4. **Create a Registry** in `strategies/{domain}/registry.py`
5. **Keep the handler language-free** - delegate all language decisions to strategies
6. **TDD each strategy independently** with its own test file
7. **Document the pattern** with a `CLAUDE.md` in the strategy directory

### Example Future Domains

```
strategies/
├── tdd/           # THIS MODULE (archetype)
│   ├── CLAUDE.md
│   ├── protocol.py
│   ├── common.py
│   ├── registry.py
│   └── {language}_strategy.py (x11)
│
├── lint/          # Future: language-specific lint enforcement
│   ├── protocol.py     (LintStrategy)
│   ├── common.py
│   ├── registry.py
│   └── {language}_strategy.py
│
├── naming/        # Future: naming convention enforcement
│   ├── protocol.py     (NamingStrategy)
│   ├── common.py
│   ├── registry.py
│   └── {language}_strategy.py
│
└── imports/       # Future: import order/validation
    ├── protocol.py     (ImportStrategy)
    ├── common.py
    ├── registry.py
    └── {language}_strategy.py
```

---

## File Index

```
strategies/tdd/
├── CLAUDE.md                   # This document (archetype reference)
├── __init__.py                 # Public API: TddStrategy, TddStrategyRegistry
├── protocol.py                 # Strategy Protocol interface
├── common.py                   # Shared DRY utilities
├── registry.py                 # Extension-to-strategy mapping
├── python_strategy.py          # Python strategy
├── go_strategy.py              # Go strategy
├── javascript_strategy.py      # JavaScript/TypeScript strategy
├── php_strategy.py             # PHP strategy
├── rust_strategy.py            # Rust strategy
├── java_strategy.py            # Java strategy
├── csharp_strategy.py          # C# strategy
├── kotlin_strategy.py          # Kotlin strategy
├── ruby_strategy.py            # Ruby strategy
├── swift_strategy.py           # Swift strategy
└── dart_strategy.py            # Dart strategy

tests/unit/strategies/tdd/
├── test_protocol.py            # Protocol conformance tests
├── test_common.py              # Shared utility tests
├── test_registry.py            # Registry tests
├── test_acceptance_tests.py    # Acceptance test provision tests (127 tests)
├── test_python_strategy.py     # Python strategy tests
├── test_go_strategy.py         # Go strategy tests
├── test_javascript_strategy.py # JS/TS strategy tests
├── test_php_strategy.py        # PHP strategy tests
├── test_rust_strategy.py       # Rust strategy tests
├── test_java_strategy.py       # Java strategy tests
├── test_csharp_strategy.py     # C# strategy tests
├── test_kotlin_strategy.py     # Kotlin strategy tests
├── test_ruby_strategy.py       # Ruby strategy tests
├── test_swift_strategy.py      # Swift strategy tests
└── test_dart_strategy.py       # Dart strategy tests
```

---

**Pattern Source**: GoF Strategy Pattern adapted for Python Protocol typing
**Languages**: 11 (Python, Go, JS/TS, PHP, Rust, Java, C#, Kotlin, Ruby, Swift, Dart)
**Tests**: 175 strategy tests + 127 acceptance tests + 87 handler tests = 389 total
