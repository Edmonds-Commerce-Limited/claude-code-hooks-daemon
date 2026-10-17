# rfix2-rust-attr: stand-alone Rust module using external derive-helper attributes

## Assumptions

None needed.

## Defect

`RustLintStrategy.is_tool_unavailable_output` excused a stand-alone rustc run only when every error carried
E0432/E0433/E0463/E0583. A module using `#[serde(...)]` also gets the uncoded
`error: cannot find attribute `serde` in this scope` (probe: `untracked/scratch/rv-rust/out.txt`), so the
all-errors-excused test failed and an ordinary crate module was denied.

## Fix

`_CRATE_CONTEXT_ERROR` in `src/claude_code_hooks_daemon/strategies/lint/rust_strategy.py` now also matches
`error: cannot find attribute|macro|derive macro|attribute macro `...\`\` (names only an external crate can supply).
A syntax error or a coded type error beside them still denies (N474 intent kept).

## Tests (tests/unit/strategies/lint/test_rust_crate_context.py)

Red before the fix: `5 failed, 31 passed` (four parametrised external-name rows plus the serde-module row).
Rows added:

- attribute / derive macro / macro / attribute macro each alone: excused
- the serde probe shape (E0432 + two uncoded attribute errors): excused
- unresolved attribute + syntax error: still a finding
- unresolved macro + E0308: still a finding

Green after: lint strategy dir + `test_lint_on_edit_rust_crate.py` + `test_staged_lint_gate_rust.py`: 336 passed, 5 skipped.

## Siblings checked

`_ERROR_LINE` / `_ERROR_SUMMARY_LINE` need no change. Both callers of the strategy method
(lint_on_edit, staged lint gate) go through the same method, so both are fixed. Go strategy has its own
classifier and was not named by the reviewer.

## Callouts

No existing release-notes/callout file mentions this behaviour; none edited.
