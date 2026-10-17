# rfix-rust-mixed: Rust lint mixed-error allow

## Assumptions

None needed.

## Defect

`RustLintStrategy.is_tool_unavailable_output` used `search` for the crate-context codes (E0432/E0433/E0463/E0583), so one such error anywhere excused the whole run and `lint_on_edit` ALLOWed it, discarding real errors in the same output (E0432 + E0308).

## Red output

Two new tests failed before the fix:

- `test_crate_context_plus_type_error_is_a_finding`: `assert True is False`
- `test_crate_context_plus_syntax_error_is_a_finding`: `assert True is False`

(`2 failed, 27 passed`.)

## Fix

`src/claude_code_hooks_daemon/strategies/lint/rust_strategy.py`: the shim marker still excuses the run. Otherwise every error line (`error(\[E\d+\])?:` at line start, excluding `error: aborting due to` and `error: could not compile` trailers) must be a crate-context code, and at least one must exist. Same shape as Go's `is_mid_edit_output`.

## Tests

`tests/unit/strategies/lint/test_rust_crate_context.py`, class `TestCrateContextClassification`, added: crate-context + E0308 (False), crate-context + syntax error (False), several crate-context errors with summary and `could not compile` trailers (True), crate-context + warning (True), shim marker + other error (True). Existing tests unchanged and green (crate-context-only True, E0308-only False, syntax-only False, prose False, shim True). Also ran the strategies/lint directory, `test_lint_on_edit_rust_crate.py` and `test_staged_lint_gate_rust.py`: 329 passed, 5 skipped.

## Release note

Callout `029-rust-lint-uses-the-owning-crate-context.md` said unresolved imports ALLOW while other compiler errors still deny; reworded so it states the all-errors-must-be-crate-context condition and that mixed output denies. No new callout.

## Sibling check

Only two strategies implement `is_tool_unavailable_output`: Rust (fixed) and Go. Go matches `_MODULE_CONTEXT_MARKERS` by substring (`cannot find main module`, `go.mod file not found`, `build constraints exclude all Go files`). Those describe `go` failing before reading any file, so no finding about the file can coexist in that output; same-shape defect not confirmed, no change. Other strategies' module-level regexes (ansible `_PLAY_SIGNAL`, Go `_FINDING`/`_UNRESOLVED_NAME`) are not excusal-by-search of a run. Not checked: the reviewer's probe crate under untracked/scratch/revb/ was not used; the tests carry the reviewer's E0432 + E0308 shape directly.
