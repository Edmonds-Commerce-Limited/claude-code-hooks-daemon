# Plan: Lint-on-Edit Handler with Strategy Pattern

**Status**: Complete (2026-02-12)

## Context

The project has a `ValidateEslintOnWriteHandler` (PostToolUse) that runs ESLint after Write/Edit on TypeScript files. The user wants to generalise this into a **language-aware lint-on-edit handler** using the Strategy Pattern (same architecture as TDD and QA suppression strategies).

Each language defines a **default lint command** (e.g., `bash -n`, `python -m py_compile`) and an optional **extended lint command** (e.g., `shellcheck`, `ruff`). Commands are overridable at project level via config. Shell/bash is not currently a supported language and must be added.

## Scope

- New `strategies/lint/` domain (Protocol, Registry, per-language strategies)
- New `LintOnEditHandler` PostToolUse handler (generalises `ValidateEslintOnWriteHandler`)
- Shell/bash as a new language (lint strategies only, NOT adding to TDD/QA suppression)
- Config support for language filtering and per-language command overrides
- Full TDD, QA, daemon verification

## Phase 1: Lint Strategy Domain (`strategies/lint/`)

### 1.1 Protocol (`strategies/lint/protocol.py`)

```python
@runtime_checkable
class LintStrategy(Protocol):
    @property
    def language_name(self) -> str: ...
    @property
    def extensions(self) -> tuple[str, ...]: ...
    @property
    def default_lint_command(self) -> str: ...
    @property
    def extended_lint_command(self) -> str | None: ...
    @property
    def skip_paths(self) -> tuple[str, ...]: ...
    def get_acceptance_tests(self) -> list[Any]: ...
```

- `default_lint_command`: Built-in linter (e.g., `bash -n {file}`)
- `extended_lint_command`: Optional extra tool (e.g., `shellcheck {file}`)
- `{file}` placeholder replaced at runtime with actual file path
- `skip_paths`: Paths to skip (vendor, dist, node_modules, etc.)

### 1.2 Common utilities (`strategies/lint/common.py`)

- `COMMON_SKIP_PATHS`: Shared skip paths (node_modules, dist, vendor, .build, coverage)
- `matches_skip_path(file_path, skip_paths)`: Reuse pattern from TDD common

### 1.3 Registry (`strategies/lint/registry.py`)

- `LintStrategyRegistry` - same pattern as `TddStrategyRegistry`
- `create_default()` registers all language strategies
- `filter_by_languages()` for config filtering
- `get_strategy(file_path)` returns strategy by extension

### 1.4 Per-language strategies

Only languages with a meaningful built-in lint command. Each in `strategies/lint/{language}_strategy.py`:

| Language | Extensions | Default Lint Command | Extended Lint Command |
|----------|-----------|---------------------|----------------------|
| Shell | `.sh`, `.bash` | `bash -n {file}` | `shellcheck {file}` |
| Python | `.py` | `python -m py_compile {file}` | `ruff check {file}` |
| Go | `.go` | `go vet {file}` | `golangci-lint run {file}` |
| Rust | `.rs` | `rustc --edition 2021 --crate-type lib -Z parse-only {file}` | `clippy-driver {file}` |
| Ruby | `.rb` | `ruby -c {file}` | `rubocop {file}` |
| PHP | `.php` | `php -l {file}` | `phpstan analyse {file}` |
| Dart | `.dart` | `dart analyze {file}` | `null` |
| Kotlin | `.kt` | `kotlinc -script {file} 2>&1` | `ktlint {file}` |
| Swift | `.swift` | `swiftc -typecheck {file}` | `swiftlint lint {file}` |

**Not included** (no built-in single-file lint):
- JavaScript/TypeScript: Already covered by `ValidateEslintOnWriteHandler` (project-specific tooling, not built-in)
- Java: `javac` requires classpath setup, not practical as a quick lint
- C#: `dotnet build` requires project context, not single-file

### 1.5 `__init__.py`

Public API: `LintStrategy`, `LintStrategyRegistry`

## Phase 2: LintOnEditHandler (`handlers/post_tool_use/lint_on_edit.py`)

### Handler design

- **Event**: PostToolUse (runs after Write/Edit)
- **Priority**: 25 (code quality range, after safety handlers, before workflow)
- **Terminal**: False (non-terminal, allows other PostToolUse handlers to run)
- **Tags**: VALIDATION, MULTI_LANGUAGE, QA_ENFORCEMENT, NON_TERMINAL

### Logic flow

1. `matches()`: Check tool is Write/Edit, file has known extension, file exists, not in skip paths
2. `handle()`:
   - Get strategy from registry
   - Build lint command (check config overrides first, then strategy defaults)
   - Run default lint command via subprocess
   - If extended command configured and default passes, run extended command
   - On failure: return DENY with lint output and fix instructions
   - On success: return ALLOW (silent, no noise)

### Config support

```yaml
handlers:
  post_tool_use:
    lint_on_edit:
      enabled: true
      priority: 25
      options:
        # Restrict to specific languages (default: ALL)
        languages:
          - Shell
          - Python
        # Override lint commands per language
        command_overrides:
          Python:
            default: "ruff check {file}"
            extended: null
          Shell:
            default: "bash -n {file}"
            extended: "shellcheck -x {file}"
```

### Relationship to ValidateEslintOnWriteHandler

The existing ESLint handler stays as-is. It has project-specific logic (llm: commands detection, workspace-aware ESLint wrapper, worktree support) that doesn't fit the generic lint pattern. The new handler covers languages with simple CLI linters.

## Phase 3: Constants & Config

### Files to modify

- `src/claude_code_hooks_daemon/constants/handlers.py`: Add `LINT_ON_EDIT` HandlerIDMeta
- `src/claude_code_hooks_daemon/constants/priority.py`: Add `LINT_ON_EDIT = 25`
- `src/claude_code_hooks_daemon/constants/__init__.py`: Export if needed
- `.claude/hooks-daemon.yaml`: Add handler config entry (enabled for dogfooding)

### HandlerKey literal

Add `"lint_on_edit"` to the `HandlerKey` Literal type.

## Phase 4: Tests (TDD)

### Unit tests (write FIRST)

- `tests/unit/strategies/lint/test_protocol.py` - Protocol conformance
- `tests/unit/strategies/lint/test_common.py` - Common utilities
- `tests/unit/strategies/lint/test_registry.py` - Registry create_default, get_strategy, filter
- `tests/unit/strategies/lint/test_{language}_strategy.py` - One per language (9 files)
- `tests/unit/strategies/lint/test_acceptance_tests.py` - All strategies provide valid acceptance tests
- `tests/unit/handlers/post_tool_use/test_lint_on_edit.py` - Handler matches/handle/config

### Integration tests

- `tests/integration/test_all_handlers_response_validation.py` - Add lint_on_edit case

## Phase 5: Wiring & Verification

1. Register handler in `handlers/post_tool_use/__init__.py` (or wherever handler discovery happens)
2. Add to `.claude/hooks-daemon.yaml` with languages restricted to Shell + Python for dogfooding
3. Run full QA: `./scripts/qa/run_all.sh`
4. Daemon restart verification: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart && status`

## Implementation Order

1. **Phase 1.1-1.2**: Protocol + common (with tests first)
2. **Phase 1.4**: Shell strategy (with tests first) - start with one language to validate pattern
3. **Phase 1.3**: Registry (with tests first)
4. **Phase 2**: Handler (with tests first)
5. **Phase 3**: Constants, config, wiring
6. **Phase 1.4 continued**: Remaining 8 language strategies (with tests first)
7. **Phase 5**: Full QA + daemon verification
8. Checkpoint commits after each logical unit

## Verification

```bash
# After each phase
pytest tests/unit/strategies/lint/ -v
pytest tests/unit/handlers/post_tool_use/test_lint_on_edit.py -v

# Final verification
./scripts/qa/run_all.sh
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
```
