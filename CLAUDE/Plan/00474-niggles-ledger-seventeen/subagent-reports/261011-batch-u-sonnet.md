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

## Results

- Targeted pytest (pip handler tests, `tests/unit/utils`, the corpus gate
  `tests/integration/test_ordinary_command_regression_gate.py`): 2464 passed.
- black, ruff, mypy and pyright clean on the touched files.
- Full suite not run, as instructed.
