# Plan 00527 Phases 3 and 4: Go tdd_enforcement and error_hiding_blocker

## Phase 3: tdd_enforcement (strategies/tdd/go_strategy.py, common.py)

- `is_production_source`: any `.go` file with a `go.mod` at or above it (new `has_ancestor_marker` in common.py, reusing the lint handlers' `find_module_root` walk, which is EACCES-safe). The `/src/ /cmd/ /pkg/ /internal/` allow-list is gone, so root-level and `api/`, `server/` packages are enforced. A `.go` file with no module above it is no longer gated.
- `should_skip(path, content)`: vendor/testdata; a `// Code generated .* DO NOT EDIT.` line before the `package` clause; a directory that already holds any `*_test.go` (read with `path_is_dir` plus `iterdir`; an unlistable directory counts as "no tests", so the gate stays on).
- `is_excluded_source_file`: `*.pb.go`, `*_gen.go`, `zz_generated*`, `doc.go`, `cmd/<name>/main.go` (only exactly one level under `cmd`).
- Acceptance test fixture now creates a `go.mod`, otherwise its DENY probe would not be gated.
- Existing handler tests used fake `/workspace/src/...` Go paths with no `go.mod`; an autouse fixture in `test_tdd_enforcement.py` patches `has_ancestor_marker`. Real behaviour is pinned in `test_tdd_enforcement_go.py` and `test_go_strategy_package.py` against tmp_path modules.

## Phase 4: error_hiding_blocker (strategies/error_hiding/go_strategy.py)

- New optional `ContentPreparingStrategy` protocol (protocol.py); the handler's `_find_violation` calls `prepare_content` when a strategy has it. Other languages are untouched.
- `GoErrorHidingStrategy.prepare_content` blanks the bodies of `//` and `/* */` comments, `"..."` strings, `'...'` runes and raw backtick strings (newlines kept; unterminated literals tolerated for Edit fragments). A comment-only `if err != nil` body therefore reads as empty and the existing "empty error check" regex catches it (Task 4.2).
- Blank-identifier regex now requires a blank LAST value assigned from a call (`f(`, `pkg.Func(`). `m[k]`, `y.(T)`, `range`, `<-ch` have no call head. `_, _ = f()` passes; `_, _ := f()` (not valid Go) still matches, which keeps the previously pinned test.
- `f(x).(T)` and `f(x)[k]` (type assertion or index on a call result) are un-called before matching, so `s, _ := ctx.Value(k).(string)` passes.

## Deviations and limits

- Task 4.2's one-line `if err != nil { // ignore }` is not valid Go (the brace sits inside the comment); the multi-line form and `{ /* ignore */ }` are pinned. PLAN.md says so.
- A longer chain such as `a.B().C(x).(T)` still matches at `a.B(`; only the last call before `.(` or `[` is un-called. Not seen in practice; not pinned.
- Test files (`*_test.go`) are still not exempt from the blank-identifier rule (not in this task's scope).

## Tests

`tests/unit/strategies/tdd/test_go_strategy.py`, `test_go_strategy_package.py`, `tests/unit/handlers/test_tdd_enforcement_go.py`, `tests/unit/handlers/pre_tool_use/test_error_hiding_blocker_go.py` (every audit-table form, both directions). All were run red first (11 and 27 failures for the intended reasons).

Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/061-go-tdd-per-package-and-error-hiding-precision.md`.
