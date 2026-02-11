# Plan 00045: Proper Language Strategy

**Status**: Proposed
**Created**: 2026-02-11
**Priority**: High

## Context

The codebase has THREE inconsistent language-aware systems:

1. **TDD Strategy Pattern** (11 languages, well-architected) - `strategies/tdd/`
2. **LanguageConfig dataclass** (6 languages, flat data) - `core/language_config.py`, used by 3 near-identical QA suppression handlers with 95% code duplication
3. **ESLint Disable Handler** (1 language, hardcoded) - should be part of QA suppression

The user wants:
- **ONE** canonical list of supported languages
- **Project-level** `languages` config (under `daemon:`) that all handlers respect
- **Handler override** capability (handler-level `options.languages` overrides project default)
- **Default = ALL** if no languages defined
- **QA suppression handlers migrated** to strategy pattern (like TDD)

## Goals

- Unified language strategy across all language-aware handlers
- Project-level `daemon.languages` config with handler override capability
- QA suppression refactored from 4 duplicated handlers to 1 handler + strategies
- LanguageConfig deprecated and absorbed into QA suppression strategies
- All 11 languages supported for both TDD and QA suppression

## Non-Goals

- Additive language override (e.g., "project languages + extra") - YAGNI for v1
- Shared Protocol between TDD and QA suppression (different concerns)
- New language additions beyond the existing 11

## Pre-Work: Revert Partial Implementation

Before starting, revert the partial handler-level language filtering added earlier in this session:
- `tdd_enforcement.py`: Remove `_apply_language_filter()`, `_languages`, `_languages_applied` (will be re-implemented properly in Phase 4)
- `test_tdd_enforcement.py`: Remove language filtering tests (will be rewritten for project-level flow)
- `test_tdd_strategy_registry.py`: Keep `filter_by_languages` tests (registry method stays)
- `.claude/hooks-daemon.yaml`: Remove commented-out languages block under tdd_enforcement
- `examples/basic_setup/hooks-daemon.yaml`: Remove commented-out tdd_enforcement block
- `daemon/init_config.py`: Remove commented-out languages block under tdd_enforcement
- Registry's `filter_by_languages()` method stays - it will be used by the proper implementation

---

## Phase 1: Project-Level Languages Config Infrastructure

**Goal**: Add `daemon.languages` and flow it to all handlers.

### Config Schema Change

```yaml
daemon:
  languages:           # NEW - optional, defaults to ALL
    - Python
    - Go
    - JavaScript/TypeScript
    # ... (all 11 shown commented-out in examples)
```

### Files to Modify

| File | Change |
|------|--------|
| `src/.../config/models.py` | Add `languages: list[str] \| None = None` to `DaemonConfig` |
| `src/.../handlers/registry.py` | Modify `register_all()` to accept + inject `_project_languages` into all handlers via setattr |
| `src/.../daemon/controller.py` | Extract `daemon.languages` and pass to `register_all()` |
| `src/.../daemon/init_config.py` | Add commented-out `languages:` to config templates |

### Tasks

- [ ] Write failing tests for DaemonConfig accepting languages field
- [ ] Write failing tests for registry injecting _project_languages
- [ ] Implement DaemonConfig.languages field
- [ ] Implement registry injection of _project_languages
- [ ] Wire controller to pass languages through
- [ ] Update config templates with commented-out languages list
- [ ] QA + daemon restart

---

## Phase 2: QA Suppression Strategy Pattern

**Goal**: Create `strategies/qa_suppression/` mirroring the TDD archetype.

### New Files

```
src/claude_code_hooks_daemon/strategies/qa_suppression/
  __init__.py
  protocol.py          # QaSuppressionStrategy Protocol
  common.py            # Shared utilities
  registry.py          # QaSuppressionStrategyRegistry
  python_strategy.py   # Absorbs PYTHON_CONFIG data
  go_strategy.py       # Absorbs GO_CONFIG data
  php_strategy.py      # Absorbs PHP_CONFIG data
  javascript_strategy.py  # Absorbs JAVASCRIPT_CONFIG + ESLint patterns
  rust_strategy.py     # Absorbs RUST_CONFIG data
  java_strategy.py     # Absorbs JAVA_CONFIG data
  csharp_strategy.py   # NEW
  kotlin_strategy.py   # NEW
  ruby_strategy.py     # NEW
  swift_strategy.py    # NEW
  dart_strategy.py     # NEW
  CLAUDE.md            # Archetype documentation

tests/unit/strategies/qa_suppression/
  test_protocol.py
  test_registry.py
  test_{language}_strategy.py (x11)
  test_acceptance_tests.py
```

### Protocol Design

```python
@runtime_checkable
class QaSuppressionStrategy(Protocol):
    language_name: str                    # property
    extensions: tuple[str, ...]           # property
    forbidden_patterns: tuple[str, ...]   # regex patterns to block
    skip_directories: tuple[str, ...]     # dirs to skip
    tool_names: tuple[str, ...]           # QA tool names for messages
    tool_docs_urls: tuple[str, ...]       # doc URLs for messages

    def get_acceptance_tests(self) -> list[Any]: ...
```

### Shared Utilities

Extract `matches_directory()` from `strategies/tdd/common.py` to `strategies/common.py`. Both TDD and QA suppression import from shared location. TDD common re-exports for backward compatibility.

### Tasks

- [ ] Create shared `strategies/common.py`, refactor TDD common to use it
- [ ] Write Protocol + tests
- [ ] Write Registry + tests
- [ ] Write 6 strategies from existing LanguageConfig data (Python, Go, PHP, JS/TS, Rust, Java) + tests
- [ ] Write 5 new language strategies (C#, Kotlin, Ruby, Swift, Dart) + tests
- [ ] Write acceptance test provision tests
- [ ] QA + daemon restart

---

## Phase 3: Unified QA Suppression Handler

**Goal**: Replace 4 handlers with 1 strategy-driven handler.

### New File

`src/.../handlers/pre_tool_use/qa_suppression.py` - single `QaSuppressionHandler`:
- Creates registry, delegates all language logic to strategies
- Has `_languages` (handler override) and `_project_languages` (project default)
- `_apply_language_filter()`: handler languages > project languages > ALL
- `matches()`: check tool (Write/Edit), lookup strategy, check skip dirs, scan content
- `handle()`: build denial from strategy data
- `get_acceptance_tests()`: aggregate from strategies

### Config

```yaml
handlers:
  pre_tool_use:
    qa_suppression:       # NEW - replaces 4 separate handlers
      enabled: true
      priority: 26
      # options:
      #   languages:      # Override project-level for this handler only
```

### Tasks

- [ ] Add HandlerID.QA_SUPPRESSION + Priority.QA_SUPPRESSION constants
- [ ] Write failing handler tests (matches, handle, language filtering)
- [ ] Implement unified handler
- [ ] Register in config + dogfooding config
- [ ] QA + daemon restart

---

## Phase 4: TDD Handler Project-Languages Support

**Goal**: Make TDD handler respect `_project_languages` as fallback.

### File to Modify

`src/.../handlers/pre_tool_use/tdd_enforcement.py` - update `_apply_language_filter()`:
- Check `self._languages` (handler override) first
- If not set, check `self._project_languages` (project default)
- If neither, ALL languages (current behavior)

### Tasks

- [ ] Write failing tests for project_languages fallback
- [ ] Update _apply_language_filter() logic
- [ ] QA + daemon restart

---

## Phase 5: Deprecation and Migration

**Goal**: Remove old handlers, deprecate LanguageConfig.

### Backwards Compatibility

In `register_all()`: if old config keys (`python_qa_suppression_blocker`, etc.) are found and `qa_suppression` is not configured, log deprecation warning and auto-map to new handler.

### Removal

- Delete 4 old handler files + their test files
- Delete `core/language_config.py`
- Remove old HandlerID/Priority constants
- Update all config files to use `qa_suppression`

### Tasks

- [ ] Add backward-compat mapping in registry
- [ ] Delete old handler files + tests
- [ ] Delete language_config.py
- [ ] Update all configs (dogfooding, example, init_config)
- [ ] Full QA + acceptance tests

---

## Phase 6: Documentation

- [ ] Update `CLAUDE.md` with unified language strategy
- [ ] Create `strategies/qa_suppression/CLAUDE.md`
- [ ] Update `strategies/tdd/CLAUDE.md` re: shared common
- [ ] Update config examples in all docs

---

## Critical Files

| File | Role |
|------|------|
| `src/.../config/models.py` | Add daemon.languages field |
| `src/.../handlers/registry.py` | Inject _project_languages into all handlers |
| `src/.../core/language_config.py` | Data source to absorb then deprecate |
| `src/.../handlers/pre_tool_use/python_qa_suppression_blocker.py` | Source of truth for duplicated QA logic |
| `src/.../handlers/pre_tool_use/tdd_enforcement.py` | Update for project-languages fallback |
| `src/.../strategies/tdd/common.py` | Extract shared utils to strategies/common.py |
| `src/.../strategies/tdd/protocol.py` | Reference archetype for QA Protocol |

## Verification

After each phase:
1. `./scripts/qa/run_all.sh` - all 7 checks pass
2. `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart` - daemon starts
3. `$PYTHON -m claude_code_hooks_daemon.daemon.cli status` - RUNNING
4. After Phase 5: `/acceptance-test all` - full acceptance suite passes

## Risks

| Risk | Mitigation |
|------|------------|
| Breaking existing QA suppression | Phase 5 provides backward-compat config mapping; old handlers stay until verified |
| TDD common.py refactor breaks imports | Re-export from old path for backward compat |
| New languages have wrong QA patterns | Research correct linter patterns; mark as best-effort |
