# Plan 00512 implementation report (python-developer, Sonnet)

Branch: worktree-issue-82-worktree-budget. The coordinator ruling was implemented as written; no disagreement.

## Design (one declared source of truth)

`Timeout` in `src/claude_code_hooks_daemon/constants/timeout.py` gains three per-event tables keyed by `EventType`:

| Event          | EVENT_HANDLER_BUDGET | EVENT_CHAIN_DEADLINE | EVENT_CLIENT_WAIT |
| -------------- | -------------------- | -------------------- | ----------------- |
| WorktreeCreate | 50                   | 55                   | 60                |
| WorktreeRemove | 60                   | 65                   | 70                |

- Create budget = `GIT_WORKTREE` (30) + 4 short calls of `GIT_WORKTREE_CLEANUP` (= `GIT_CONTEXT`, 5): the branch pre-check plus the three cleanup calls. Remove budget = 2 x `GIT_WORKTREE` (remove, then prune).
- Deadline = budget + `CHAIN_DEADLINE_HANDLER_MARGIN_SECONDS` (5). Client wait = deadline + the existing `CHAIN_DEADLINE_SOCKET_MARGIN_SECONDS` (5).
- `ChainConfig.deadline_for(event)` (config/models.py) returns `deadline_seconds` unchanged for every event not in the table, `None` stays `None`, and for the two worktree events `max(deadline_seconds, floor)`. `daemon/controller.py` passes `deadline_for(event.event_type)` to the router (the only call site). No guard deadline, decision logic or PreToolUse path changed.
- Client mirrors: `init.sh` (`.claude/init.sh` is a symlink to it) computes `_event_socket_wait` once (case: 60 / 70 / default 30) and uses it for both the nc rung `-w` default and the python rung default (`DEFAULT_SOCKET_TIMEOUT`); `CLAUDE_HOOKS_SOCKET_TIMEOUT` still overrides. The relay forwarder generator (`install/forwarder_generator.py` `build_relay_guard_block`) uses `max(transport.timeout_seconds, event wait)`; the tracked `.claude/hooks/worktree-remove` had its `--timeout-ms` changed 30000 -> 70000 by hand to match what the generator now emits (regenerating inside the worktree would bake the worktree's absolute paths). WorktreeCreate has no relay (raw_stdout event), so only the python rung matters for it.
- Cleanup (worktree_create_handler.py): `_git_worktree_add` first checks whether `refs/heads/<branch>` already exists; on a non-zero add (including run_git's timeout, which it reports as non-zero) `_undo_failed_add` runs `worktree remove --force <path>`, `worktree prune`, and `branch -D <branch>` only when the branch did not pre-exist (`add -b` refuses an existing branch, so it is not this call's to delete). A cleanup failure is logged and never masks the add error.
- Handler guidance (`get_claude_md`) does not state a budget, so it is unchanged. Docs: `docs/guides/CONFIGURATION.md` Chain Deadline section. Release note 035 added.

## RED (before any production change)

`tests/unit/constants/test_event_budgets.py` first run: `AttributeError: type object 'Timeout' has no attribute 'EVENT_HANDLER_BUDGET'` (the tables did not exist; the underlying defect is that `GIT_WORKTREE` = 30 >= `CHAIN_DEADLINE_DEFAULT` = 20 and the client wait is 30).

Handler tests, `tests/unit/handlers/worktree_create`, `TestFailedAddLeavesNoOrphan`:

```
FAILED ...::test_failing_add_removes_the_worktree_and_its_branch
FAILED ...::test_timed_out_add_removes_the_worktree_and_its_branch
E   AssertionError: assert ['master', 'orphan-ae84c627'] == ['master']
E     Left contains one more item: 'orphan-ae84c627'
```

(The pre-existing-branch survival test and the cleanup-does-not-mask-error test pass before and after, as guards.)

## GREEN

88 passed across test_event_budgets.py and the two worktree handler directories. Also green: tests/unit/constants, tests/unit/install, tests/unit/core, tests/unit/config chain and transport tests, tests/unit/daemon controller and chain-deadline wiring tests, tests/integration init.sh fail-closed and relay-guard tests.

## Tests added

- test_event_budgets.py: handler budget < chain deadline < client wait (with margins) for each table event; recorded `run_git` timeouts of the real create and remove handlers sum within their budget; every other `EventType` keeps the guard deadline (20, or the configured value); `null` stays disabled; a low configured value cannot undercut a worktree floor; a slow add (0.6s against a 0.2s guard-sized deadline, floor patched down) still yields the path through `HandlerChain.execute`; `init.sh` case table equals `EVENT_CLIENT_WAIT`; relay guard `--timeout-ms` equals the event wait (and `pre-tool-use` keeps the transport timeout).
- test_worktree_create_handler.py: failing add (post-checkout `exit 1`) and timed-out add (hook `sleep 2`, `GIT_WORKTREE` patched to 0.5) leave no branch and no worktree registration; a pre-existing branch survives a failed add; cleanup failure does not mask the add error.
- One existing test adjusted: `test_the_bounds_on_the_start_path_sum_below_the_hook_timeout` read the python default from `_resolve_socket_timeout`'s literal; it now reads the guard default arm of the `init.sh` case (same value, 30).

## Caveats for the coordinator

- The worktree events have no `timeout` registered in settings.json, so the start-path bound in init.sh (`_HOOKS_DAEMON_START_DEADLINE` + lock wait + request, summed against `REGISTERED_HOOK_TIMEOUT` 60) is not applied to them; a cold daemon start plus a 60s wait can exceed 60s, which is fine only because the harness default for these hooks is minutes. Not changed.
- `chain_deadline_problems` (health) still compares the guard deadline with the guard client budget only; it does not evaluate the worktree floors.
- The live CLAUDE.md, a running daemon and a deployed relay binary pick up the new numbers only after the daemon restarts and forwarders are regenerated on upgrade.
- Time-out test sleeps 2s (orphaned `sleep` holds git's stderr pipe until it ends); the file runs in about 2s total.

## QA

Black, ruff check and mypy on all touched Python files: clean. shellcheck on init.sh reported nothing mentioning `_event_socket_wait`. `./scripts/qa/llm_qa.py changed`: every check green except two flags. `plan_qa` carries one advisory (journal-freshness on Plan 00495, unrelated, 0 block). `changed_tests` shows 3383 passed, 0 failed, 61 skipped over 88 test files, but is marked not recorded because the working tree changed during the run (this report was written while it ran); re-run it on a still tree if a certified record is wanted.
