# rfix3-rust-typo: rustc typos no longer excused as crate-context errors

## Assumptions

None needed.

## Red

Fixtures are real rustc 1.99.1 stderr (tests/fixtures/rustc-output/). Before the fix:

- `test_real_rustc_output[typo.txt-False]`: `assert True is False` (`prinln!`)
- `test_real_rustc_output[typo2.txt-False]`: `assert True is False` (`#[derive(Debg)]`, `#[tset]`)
- `test_typo_beside_unresolved_external_attribute_is_a_finding`: `assert True is False`

## Fix

`rust_strategy.py`: `is_tool_unavailable_output` now judges each diagnostic as a block (error line through the next
blank line, via `_error_blocks`). An uncoded "cannot find ..." error is excused only if its block carries no rustc
similar-name suggestion (`with a similar name exists` / `similarly named`, both present in real output for all three
typos). The serde case (`use serde`, `#[serde(..)]`, `json!`) has no suggestion in real output and stays allowed, as
does the coded E0432 path typo (`std::colections`), which is out of this defect's scope and unchanged.

## Checked

Sibling code: only rust_strategy.py classifies rustc output. Existing synthetic tests all still pass (lint strategies
dir: 321 passed, 5 skipped). No UNRELEASED callout mentions this behaviour (grep of the worktree found none), so no
callout edit is needed.

## Residual (not fixed, outside the brief)

A typo of an external-crate-style name with no near neighbour in std (for example `#[serd(...)]`) carries no
suggestion and is still excused; rustc gives no signal to separate it from `#[serde(...)]`.

## QA

`./scripts/qa/llm_qa.py changed`: 40/40 PASSED, exit 0 (the first run hit a format failure, fixed with
run_autofix.sh; the second ran on a still tree).
