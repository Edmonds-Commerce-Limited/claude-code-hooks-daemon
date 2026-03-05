# Plan: Collocated Test Support for TDD Enforcement Handler

## Context

The TDD enforcement handler blocks Write operations to production source files unless a corresponding test file exists. Currently, it only searches for test files in **separate test directories** (`tests/`, `tests/unit/`, fallback). It does NOT check for:

- **Collocated tests** — test file in same directory as source (e.g., `src/foo/bar.test.ts` next to `src/foo/bar.ts`)
- **`__tests__/` subdirectory** — test file in `__tests__/` dir next to source (e.g., `src/foo/__tests__/bar.test.ts`)

This incorrectly blocks Go (collocated `_test.go` is THE convention), React/Vitest/Jest projects (`*.test.ts` collocated or `__tests__/`), and Dart projects.

**Important**: The strategies' `is_test_file()` already recognizes collocated test filenames — the gap is solely in `_get_test_file_paths()` which only generates candidate paths in `tests/` directories.

## Approach

Add a `test_locations` config option to the handler with three named presets. All enabled by default. Handler-only change — zero strategy modifications.

### Config Option

```yaml
tdd_enforcement:
  options:
    test_locations:       # default: all three
      - separate          # tests/ directory tree (existing behavior)
      - collocated        # test file next to source file
      - test_subdir       # __tests__/ subdirectory next to source
```

### Files to Modify

| File | Change |
|------|--------|
| `src/.../handlers/pre_tool_use/tdd_enforcement.py` | Add constants, `_test_locations` attr, `_effective_test_locations` property, 2 new static methods, modify `_get_test_file_paths()` |
| `tests/unit/handlers/test_tdd_enforcement.py` | ~30 new test methods (TDD: written first) |
| `.claude/hooks-daemon.yaml` | Add commented `test_locations` example |

### Files NOT Modified

- 0 of 11 strategy files, protocol.py, common.py, registry.py — unchanged

---

## Implementation Phases (TDD)

### Phase 1: Constants + Config Option (RED → GREEN)

**RED**: Add failing tests for:
- Module constants: `_TEST_LOCATION_SEPARATE`, `_TEST_LOCATION_COLLOCATED`, `_TEST_LOCATION_TEST_SUBDIR`, `_TEST_SUBDIR_NAME`, `_DEFAULT_TEST_LOCATIONS`
- `handler._test_locations` defaults to `None`
- `handler._effective_test_locations` returns all 3 when None/empty, respects config when set

**GREEN**: Add constants after existing ones (~line 27) and `_test_locations` attr in `__init__`, plus `_effective_test_locations` property.

**Checkpoint commit.**

### Phase 2: Collocated Path Method (RED → GREEN)

**RED**: Add failing tests for `_map_collocated_test_path(source_path, test_filename)`:
- Same directory as source: `src/pkg/utils/helpers.ts` → `src/pkg/utils/helpers.test.ts`
- Works for Python, Go, deeply nested paths

**GREEN**: Static method — `Path(source_path).parent / test_filename`

**Checkpoint commit.**

### Phase 3: Test Subdir Path Method (RED → GREEN)

**RED**: Add failing tests for `_map_test_subdir_path(source_path, test_filename)`:
- `__tests__/` subdir: `src/pkg/utils/helpers.ts` → `src/pkg/utils/__tests__/helpers.test.ts`
- Works for all languages

**GREEN**: Static method — `Path(source_path).parent / _TEST_SUBDIR_NAME / test_filename`

**Checkpoint commit.**

### Phase 4: Wire Into `_get_test_file_paths()` (RED → GREEN)

**RED**: Add failing tests for:
- `_get_test_file_paths()` includes collocated candidate in results
- `_get_test_file_paths()` includes `__tests__/` candidate in results
- Config `["separate"]` excludes collocated/test_subdir candidates
- Config `["collocated"]` excludes separate candidates
- Config `["collocated", "test_subdir"]` includes both, excludes separate
- Integration: `handle()` allows when collocated test exists (Go, JS/TS)
- Integration: `handle()` allows when `__tests__/` test exists
- Regression: existing mirror/unit tests still found

**GREEN**: Modify `_get_test_file_paths()` to gate existing separate logic behind `_TEST_LOCATION_SEPARATE in effective_locations`, then append collocated/test_subdir candidates when their styles are active.

**Checkpoint commit.**

### Phase 5: Refactor + QA + Config Docs

- Deduplicate candidates (order-preserving) if needed
- Update `.claude/hooks-daemon.yaml` with commented `test_locations` example
- Run `./scripts/qa/run_autofix.sh` + `./scripts/qa/run_all.sh`
- Verify daemon loads: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart && status`

**Final commit.**

## Verification

```bash
# TDD tests pass
pytest tests/unit/handlers/test_tdd_enforcement.py -v

# Full QA
./scripts/qa/run_all.sh

# Daemon loads
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
# Expected: RUNNING
```
