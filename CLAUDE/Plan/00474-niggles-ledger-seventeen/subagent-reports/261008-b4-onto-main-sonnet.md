# B4 (N296) merged onto main after v3.69.0

Branch `agent-a97b9f550d36dd2b9-d55aa27d` = main (8a766eacd) + `git merge --no-ff agent-ac99a72836eafa143-24488d95`.

## Conflicts

One: `src/claude_code_hooks_daemon/docs_qa/checks/unlisted_fake_value.py` (`_run_sweep`, unreadable document).
Main made the unreadable file a finding of its own (`_unreadable_finding`, WARNING log); B4 replaced the
inline log with `log_and_continue(..., level=DEBUG)`. Resolved by keeping both: `log_and_continue` with
`level=logging.WARNING` (main's level), then main's `findings.append(_unreadable_finding(...))`. Main's behaviour is unchanged.

Auto-merged cleanly with main's release changes: `utils/usage_pause.py`, `cli.py`, `utils.py`, `destructive_git.py`, others.

## Follow-up fixes

- `utils/plan_fact_check.py` (new on main since B4 forked): the widened audit flagged the debug-log-then-continue
  in `deliver_pending`; converted to `log_and_continue` with a reason (level DEBUG, unchanged).
- Release note: B4 carried none and nothing about it is in `v3.68.0-to-v3.69.0`. Added
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/001-log-and-continue-is-one-named-helper.md` (audience: handler authors).

## QA

`llm_qa.py changed`: `QA: 37/38 PASSED, 1/38 FAILED`. The one failure is `changed_tests`, which cannot run here:
B4 touches 143 files, selecting 463 test files (33% of the suite), and the sink refuses a sub-agent run over 25%
without the full-QA lock. It also reports 47 src files as unmapped ("too-broad") for the same reason.
Every other check passes, including error_hiding, pyright (0 errors), type_check, lint, format, project_handlers (232), docs checks.

Because of that, the tests were run directly in chunks, each under the 25% limit:

| Chunk                                                                       | Result                  |
| --------------------------------------------------------------------------- | ----------------------- |
| tests/unit/handlers                                                         | 14023 passed            |
| tests/unit/daemon, config, install, block_report, config_optimisation       | 4866 passed             |
| remaining unit dirs, tests/unit/test\_\*.py, tests/claude_code_hooks_daemon | 6002 passed, 1 skipped  |
| tests/unit/utils, core, qa, docs_qa                                         | 11406 passed, 23 failed |

The 23 failures are all in `tests/unit/qa/test_llm_qa_main_moved.py`. They fail with "no QA interpreter" because
this worktree has no `untracked/venv-*` of its own (I borrowed the main checkout's venv through
`HOOKS_DAEMON_VENV_PATH` plus `PYTHONPATH`, which those tests' subprocesses do not inherit). B4 does not touch that
test or `llm_qa.py`; it is an environment limit, not a regression. Not re-run on a worktree with its own venv.
`tests/unit/utils/test_plan_fact_check.py` re-run after the fix: 34 passed.
`tests/integration` and `tests/acceptance` were not run.

## Left for the coordinator

- Run the full gate (`llm_qa.py all`) on the merged head from the main thread; it covers `changed_tests` and the
  `test_llm_qa_main_moved` cases.
