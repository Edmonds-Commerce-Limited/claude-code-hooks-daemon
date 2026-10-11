# Batch U: N407 residuals from the batch S review round 2

All four cleared, test-first (the new test file was run red before the fix).

## Changes

- `src/claude_code_hooks_daemon/utils/command_position.py`: new
  `command_position_code_segments_with_separators`, returning
  `(separator before, segment)` pairs. A blank segment is dropped and its
  separator merged forward, so `a |& b` gives `("|&", "b")`. This is the accessor that
  tells which operator split two segments.
- `src/claude_code_hooks_daemon/handlers/pre_tool_use/pip_break_system.py`:
  `_env_var_governs_pip_install` now takes those pairs and tracks the export state.
- Tests: `tests/unit/handlers/pre_tool_use/test_pip_break_system_env_scope.py`
  (new, deny and allow tables), a helper test in
  `tests/unit/utils/test_command_position_comments.py`, and four corpus rows
  in `tests/fixtures/ordinary_command_corpus.yaml` after the `n407-*` rows.
- `NIGGLES.md`: the four residual lines are marked "cleared by batch U".

## Items

1. `unset X` and `export -n X` cancel an earlier truthy export (`unset -v` and
   `unset OTHER X` too). Inside a pipeline stage they do not.
2. An export or unset in a pipe stage (`|` or `|&`) is neither made nor undone,
   since each stage is a subshell. A stage still inherits an export made before
   the pipeline, so `export X=1; echo x | pip install x` still denies.
3. A leading `(` is stripped, one level per paren, and the export state at each
   open is saved. A matching trailing `)` restores it, so
   `(export X=1); pip install x` allows deliberately, not by accident. An
   `unset` inside a group does not cancel the outer export. The three required
   deny forms deny, plus nested `(export X=1; (pip install x))`.
4. `command` (with options) and `xargs` (with options, including a numeric or
   `{}` value such as `-n 1` and `-I {}`) are allowed before pip in
   `_PIP_INSTALL_HEAD`.

## Known limits (not fixed, not required)

- Only a `(` at the start of a segment opens a tracked group, and a `)` is
  stripped only while such a group is open. A group opened mid-segment is not
  tracked.
- An `xargs` option whose value is neither numeric nor `{}` (`-I %`, `-d ,`)
  breaks the head match, so that form allows.

## Round 2 (review found one regression)

1. Regression fixed: a trailing redirect after the closing paren (`2>/dev/null`,
   `> log`, `&>log`, `2>&1`) is looked past when closing a group, so
   `(export X=1) 2>/dev/null; pip install x` allows again. Three allow tests
   (plus `2>&1`) and three corpus rows.
2. A `&` after a segment is treated like a pipe for export persistence, so
   `export X=1 & pip install x` allows (also with a newline after `&` or `|`).
3. A leading reserved word (`then`, `do`...) is stripped before groups are
   opened, so `if true; then ( X=1 pip install x ); fi` denies.
4. Helper tests added for newline, `&`, `;;` and `2>&1 |`, plus a parity test
   over every corpus command. The newline case found a real bug: the helper
   stripped the newline out of the separator, so it now strips only spaces and tabs.
5. Recorded as residuals under N407, not fixed: `x=$(pip install x)` after an
   export, `xargs -a r.txt pip install`, and the splitter splitting inside a
   trailing comment.

## Results

- Targeted pytest (pip handler tests, `tests/unit/utils`, the corpus gate
  `tests/integration/test_ordinary_command_regression_gate.py`): 2464 passed
  in round 1; round 2 ran a wider selection of the same directories, 9248
  passed, 1 skipped.
- black, ruff, mypy and pyright clean on the touched files.
- Full suite not run, as instructed.
