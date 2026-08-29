# Strategy Pattern — the language-aware handler archetype

**Pattern**: Strategy Pattern (GoF) with a Python `Protocol` interface.
**Archetype module**: `src/claude_code_hooks_daemon/strategies/tdd/` — the
reference implementation every language-aware handler MUST follow. Sibling
domains (`lint`, `security`, `qa_suppression`, `pipe_blocker`, `comments`,
`error_hiding`) follow the same structure.

Promoted from the archetype module's own `CLAUDE.md` (Plan 00289) so the
pattern has a canonical home in the agent tree; the module doc is now a
pointer here. The TDD domain is used as the worked example throughout.

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
    │               │  Contract: structural typing — implementations
    │               │  satisfy the shape, they inherit nothing
    │               │
    │               └── One {Language}TddStrategy per language
    │
    └── common.py (DRY Utilities)
            │
            ├── COMMON_TEST_DIRECTORIES  (shared constant)
            ├── is_in_common_test_directory()
            └── matches_directory()
```

### Separation of Concerns (SOLID)

| Component          | Responsibility                                       | Knows About Languages? |
| ------------------ | ---------------------------------------------------- | ---------------------- |
| **Handler**        | Orchestrates workflow (matches → handle → test path) | NO                     |
| **Protocol**       | Defines the contract all strategies must satisfy     | NO                     |
| **Registry**       | Maps extensions to strategy instances                | NO (data-driven)       |
| **Strategy**       | ALL language-specific logic for one language         | YES (its own only)     |
| **Common**         | Shared utilities used by multiple strategies         | NO                     |
| **LanguageConfig** | Pure config data (names, extensions)                 | N/A (data only)        |

## The Protocol (Interface Contract)

The authoritative contract is `strategies/tdd/protocol.py` — read it rather
than a copy here. Shape (TDD domain): two properties (`language_name`,
`extensions`) and five methods (`is_test_file`, `is_production_source`,
`should_skip`, `compute_test_filename`, `get_acceptance_tests`), decorated
`@runtime_checkable`.

### Why Protocol, Not ABC?

| Feature       | Protocol (chosen)                     | ABC                   |
| ------------- | ------------------------------------- | --------------------- |
| Typing        | Structural (duck typing)              | Nominal (inheritance) |
| Coupling      | Zero - no base class import needed    | Tight - must inherit  |
| Testing       | Any object satisfying shape works     | Must subclass ABC     |
| Runtime check | `@runtime_checkable` + `isinstance()` | `isinstance()`        |
| Python idiom  | Pythonic, modern (PEP 544)            | Traditional OOP       |

**Decision**: Protocol enables true Open/Closed Principle. New strategies need
zero imports from the framework — they just need to match the shape.

### Method Contract Semantics (TDD domain)

- **`language_name`** — human-readable name used in denial messages (e.g.
  `"Python"`, `"JavaScript/TypeScript"`). Stable: changing it changes
  user-facing output.
- **`extensions`** — lowercase, dot-prefixed extensions this strategy
  handles; one strategy may cover several (the JS/TS pattern). Used by the
  registry for lookup.
- **`is_test_file`** — `True` when the file IS a test (allowed through).
  MUST check `is_in_common_test_directory()` first, then the language's own
  naming pattern (e.g. `test_*.py`, `*_test.go`).
- **`is_production_source`** — `True` for files in the language's production
  source directories (e.g. `/src/`, `/lib/`), excluding init/config files
  such as Python's `__init__.py`.
- **`should_skip`** — `True` to skip enforcement entirely (vendor dirs,
  build output, virtualenvs). The optional `content` argument enables
  content-based skipping where the path alone is not decisive (e.g. PHP
  interface declarations); strategies that do not need it still MUST accept
  it — the parameter is part of the contract so the handler can call every
  strategy identically.
- **`compute_test_filename`** — source filename → expected test filename
  (e.g. `module.py` → `test_module.py`; `server.go` → `server_test.go`).
  Each strategy's docstring records its language's convention — the strategy
  files are the source of truth for the per-language patterns.
- **`get_acceptance_tests`** — MANDATORY; see below.

## Acceptance Test Provision (MANDATORY)

Every strategy MUST provide at least one acceptance test. Enforced by:

1. **Protocol contract**: `get_acceptance_tests()` is part of the Protocol
2. **Unit tests**: `tests/unit/strategies/tdd/test_acceptance_tests.py`
   validates every registered strategy provides valid tests
3. **QA checker**: `qa/strategy_pattern_checker.py` AST-checks for a missing
   `get_acceptance_tests()`

Rules:

1. **Every strategy provides its own tests** — strategies own their test
   definitions
2. **Handler is a thin aggregator** — collects from all strategies via
   `get_acceptance_tests()`, deduplicates by `language_name`, adds nothing
   of its own
3. **Tests use safe paths** — `/tmp/acceptance-test-tdd-{language}/` only,
   with `setup_commands` and `cleanup_commands`
4. **`expected_message_patterns` include the exact `language_name` string**
   — deduplication verification depends on it
5. **Tests are BLOCKING type** (`expected_decision=Decision.DENY`)

See any existing strategy for the `AcceptanceTest(...)` shape; the dataclass
contract lives in `core` and is documented in
[CLAUDE/AcceptanceTests/GENERATING.md](../AcceptanceTests/GENERATING.md).

## Strategy Implementation Pattern

Every strategy follows this exact structure. No exceptions.

```python
"""[Language] TDD strategy implementation."""

from claude_code_hooks_daemon.strategies.tdd.common import (
    is_in_common_test_directory,
    matches_directory,
)

# ── Language-specific constants (NO MAGIC STRINGS) ──────────────
_LANGUAGE_NAME = "[Language]"
_EXTENSIONS: tuple[str, ...] = (".[ext]",)
_SOURCE_DIRECTORIES: tuple[str, ...] = ("/src/",)
_SKIP_DIRECTORIES: tuple[str, ...] = ("vendor/",)


class [Language]TddStrategy:
    """TDD enforcement strategy for [Language] projects.

    Test convention: source.[ext] -> [test pattern]
    """

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    def is_test_file(self, file_path: str) -> bool:
        # ALWAYS check common directories first (DRY),
        # then the language-specific naming pattern.
        if is_in_common_test_directory(file_path):
            return True
        ...

    def is_production_source(self, file_path: str) -> bool:
        return matches_directory(file_path, _SOURCE_DIRECTORIES)

    def should_skip(self, file_path: str, content: str = "") -> bool:
        # Accept `content` even when unused - part of the Protocol contract.
        return matches_directory(file_path, _SKIP_DIRECTORIES)

    def compute_test_filename(self, source_filename: str) -> str:
        ...

    def get_acceptance_tests(self) -> list[Any]:
        ...
```

### Rules

1. **ALL strings are named constants** — module-level, prefixed with `_`
2. **Always use `common.is_in_common_test_directory()`** in `is_test_file()`
3. **Always use `common.matches_directory()`** for directory matching
4. **No imports from other strategies** — each strategy is fully independent
5. **No imports from the handler** — strategies know nothing about handlers
6. **No imports from LanguageConfig** — config is config, strategy is
   behaviour (SRP)
7. **Class does NOT inherit from anything** — Protocol is structural
8. **One file per language** — named `{language}_strategy.py`

## Registry

`TddStrategyRegistry` is a simple extension-to-strategy map: `register()`
records each strategy under its extensions; `get_strategy(file_path)`
returns the instance for the file's extension or `None` (handler allows
through — no silent failure). The `create_default()` class method registers
ALL built-in strategies and is the standard entry point; **it is the single
source of truth for which languages are registered** — do not maintain a
language roster in documentation (the per-domain coverage table in root
`CLAUDE.md` is the human summary).

## Shared Utilities (DRY)

`common.py` holds cross-language logic: `COMMON_TEST_DIRECTORIES` (the
`/tests/`-style names every `is_test_file()` checks first),
`is_in_common_test_directory()`, and `matches_directory()` (normalising
directory matcher used for both source and skip checks).

| Logic                                     | Where       | Why               |
| ----------------------------------------- | ----------- | ----------------- |
| Test directory names used by 3+ languages | `common.py` | DRY               |
| Directory matching utility                | `common.py` | DRY               |
| Test filename pattern                     | Strategy    | Language-specific |
| Source / skip directory lists             | Strategy    | Language-specific |
| Init file exclusion (e.g. `__init__.py`)  | Strategy    | Language-specific |

**Rule**: shared by 3+ strategies → extract to `common.py`; otherwise keep it
in the strategy.

## How to Add a New Language (TDD workflow)

1. **Create the test file FIRST**:
   `tests/unit/strategies/tdd/test_{language}_strategy.py`, covering
   properties, `is_test_file` (common dir, language pattern, production
   file), `is_production_source`, `should_skip`, `compute_test_filename`
2. **Run it — it MUST FAIL** (ImportError: no implementation yet)
3. **Create `{language}_strategy.py`** following the template above
4. **Run it — it MUST PASS**
5. **Register**: one line in `registry.py`'s `create_default()`
6. **Update registry tests**
   (`tests/unit/strategies/tdd/test_tdd_strategy_registry.py`): expected
   language list + extension lookup case
7. **Full QA**: `./scripts/qa/llm_qa.py all`
8. **Restart the daemon and verify RUNNING**: `./bin/hooks-daemon restart`
   then `./bin/hooks-daemon status`

Zero handler modifications are needed — that is the point of the pattern.

## Design Principles Applied

- **SOLID**: one language per strategy (S); add a language = add a file +
  one registry line (O); every strategy substitutable through the Protocol
  (L); the Protocol carries exactly the members the handler uses, no more
  (I); the handler depends on the Protocol, never a concrete strategy (D).
- **DRY**: common test directories and directory matching defined once.
- **NO MAGIC**: every string literal a named constant.
- **YAGNI**: no ABC, no config-driven loading, no caching, no lazy loading —
  strategies are cheap, stateless, eagerly registered.
- **FAIL FAST**: unknown extension → `None` → handler allows through
  explicitly; a missing method fails immediately at the call site.

## Anti-Patterns to Avoid

```python
# WRONG - handler knows about a language
if file_path.endswith(".py"):
    test_name = f"test_{filename}"
# RIGHT - handler delegates
test_name = strategy.compute_test_filename(filename)

# WRONG - if/elif chain on language names
if config.name == "python": ...
elif config.name == "go": ...
# RIGHT - registry lookup
strategy = registry.get_strategy(file_path)

# WRONG - importing another strategy's constants
from ...tdd.python_strategy import _SOURCE_DIRECTORIES
# RIGHT - shared logic lives in common.py

# WRONG - magic string
if "/src/" in file_path: ...
# RIGHT - named constant + matches_directory()

# WRONG - nominal inheritance
class PythonTddStrategy(BaseTddStrategy): ...
# RIGHT - structural typing: satisfy the Protocol shape, inherit nothing
class PythonTddStrategy: ...
```

## Applying This Pattern to a New Domain

Future language-aware handlers MUST follow the same structure:

1. **Define a Protocol** in `strategies/{domain}/protocol.py`
2. **Create shared utilities** in `strategies/{domain}/common.py`
3. **Implement one strategy per language** in
   `strategies/{domain}/{language}_strategy.py`
4. **Create a Registry** in `strategies/{domain}/registry.py` with a
   `create_default()` factory
5. **Keep the handler language-free** — delegate every language decision
6. **TDD each strategy independently** with its own test file
7. **Point the domain's `CLAUDE.md` here** — do not fork this document
