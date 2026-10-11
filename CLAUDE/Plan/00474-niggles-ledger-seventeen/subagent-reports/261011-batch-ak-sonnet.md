# Batch AK report (N415 residuals)

Branch `agent-a0185235fea7b616a-d1a5235a`, based on 7305e56a1.

## Changed

- `src/claude_code_hooks_daemon/handlers/pre_tool_use/subagent_full_qa_blocker.py`
  - `_file_read_by` unwraps, in one iterative pass, `compile(...)`, `str(...)`, a plain f-string field (not `!r`, no
    format spec) and `.strip/.rstrip/.lstrip/.replace/.format/.encode/.decode` around a file read or a tracked name.
    Names bound to such a chain are tracked through the existing `_bind_file_names`.
  - `_operands_run_in_process` binds the variable of a `for` over a literal list/tuple of string constants to all of
    them (`loops` map, put back when the loop or a shadowing function ends, dropped on rebind) and judges each path
    (`_alternatives`, `_literal_paths`, `_loop_valued`). Non-literal iterables and a list held in a name are untouched.
- Tests in `tests/unit/handlers/pre_tool_use/test_subagent_full_qa_blocker.py`: `_TEXT_CHAIN_AND_LOOP_FULL_RUNS` (26
  deny shapes), `_TEXT_CHAIN_AND_LOOP_ALLOWED` (15), `_TEXT_FLOW_LIMITS_ALLOWED` (2, the deliberate limits), a
  non-literal-iterable test, and a timing test.
- N415 in NIGGLES.md and its STATUS-INDEX.md row updated; the two limits are worded as "coordinator's engineering
  judgement, not an owner ruling" and say flow analysis is needed.

## Verification

- Unit directory `tests/unit/handlers/pre_tool_use` plus `tests/integration/test_ordinary_command_regression_gate.py`:
  no failures. Black (py311), mypy, pyright, ruff clean on the changed source.
- The reviewer probe's `src_strip` and `loop_files` shapes are covered by the new deny tests; `if_else_bind` and
  `func_before_bind` are the pinned limits. The probe itself was not run (its runner targets another worktree).
