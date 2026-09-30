## N81-N83 gate fix report

Branch: `worktree-n466-n81-83` (worktree at
`/workspace/untracked/worktrees/worktree-n466-n81-83`), HEAD `f9276d4ca`.

### 1. Merged main

`git merge` of `main` (`b85759a8a`) picked up the Python 3.13
`test_symlink_loop_never_raises` fix and the `lsp_enforcement` hermeticity
fix. The only conflict was the `PLAN.md` niggles table: resolved by keeping
this branch's N81-N83 rows as ✅ Remedied and adding main's new N84-N94 rows
in their original position (commit `f9276d4ca`).

### 2. Stop/SubagentStop/forwarder/smoke failures -- worktree provisioning gap, not a product defect

Root cause: `.claude/hooks-daemon.env` was **missing** from this worktree.
Every other live worktree under `untracked/worktrees/` (except
`worktree-upgrade-scripts`) carries this gitignored file with
`HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH"`, which tells `.claude/init.sh` this
is a self-install checkout. Without it, `init.sh` defaulted
`HOOKS_DAEMON_ROOT_DIR` to `.claude/hooks-daemon` (the CLIENT-clone
convention), which has no `scripts/lib/resolve_venv.sh` and no venv here --
so every hook fell back to "Hooks daemon not installed ... protection not
active" with exit 0 instead of a real decision. That is exactly what
`test_stop_hook_hard_block`, `test_documented_stop_probe`,
`test_forwarder_socket_stdin` and `test_playbook_harness` caught (each
asserts a real `exit=2`/reason, and got the not-installed fallback instead),
and why `smoke_test` failed 2 of 3 probes.

Fix: created `.claude/hooks-daemon.env` (gitignored, matches every sibling
worktree's content) with `HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH"`, then
`bin/hooks-daemon restart` -- verified RUNNING against the worktree root, not
`.claude/hooks-daemon`. All 19 previously-failing tests in this group now
pass (`tests/acceptance/test_stop_hook_hard_block.py`,
`test_documented_stop_probe.py`, `test_playbook_harness.py`,
`tests/integration/test_forwarder_socket_stdin.py`). This file is
per-worktree and gitignored, so it is not part of the commit -- the gap was
in how this one worktree was provisioned, not in tracked code.

### 3. `test_excluded_path_is_not_inspected` -- errored, not fixed (load, not a defect)

The recorded failure was `subprocess.TimeoutExpired` on `git commit -q -m initial` inside the test's own `repo` fixture, timing out at
`Timeout.GIT_CONTEXT` (5s) -- the *last* test of a 28,651-test run. That
constant is the standard convention for every git-fixture helper in this
suite (86 test files use it, including the shared
`tests/support/git_fixtures.py:run_git`), so this is not a fixture unique to
this file, and the project's own quality rule forbids widening timing
bounds to paper over a flaky assertion. The test passed cleanly alone and
alongside 547 related tests in this session. Live evidence for the cause:
`/proc/loadavg` on this shared container reads `6.00` against `nproc=8`
*right now*, with dozens of other agent worktrees in this same session
running their own gates concurrently -- a plain `git commit` in an empty
tmpfs repo taking >5s is consistent with CPU contention, not with a hang or
a code defect. No src/test change made for this item; recommend the
coordinator treat it as a load-flake to watch for recurrence outside a
heavily loaded gate window, not a defect to fix in this branch.

### 4. Errored test in tests.json

Same test as item 3 -- `tests.json`'s single `errored` entry is
`test_excluded_path_is_not_inspected` (pytest reports a fixture-setup
`TimeoutExpired` as an error, not a failure); already covered above.

### Verification

- Targeted run (547 tests: `test_sensitive_content.py`,
  `test_documented_stop_probe.py`, `test_playbook_harness.py`,
  `test_stop_hook_hard_block.py`, `test_forwarder_socket_stdin.py`,
  `test_plan_trigger.py`, `test_lsp_enforcement.py`,
  `test_acceptance_contract.py`, `test_sed_blocker.py`,
  `test_config_key_consistency.py`, `test_registry_builtin_iteration.py`,
  `test_bash_write_destinations.py`, `test_llm_qa_live_daemon.py`): all
  passed.
- ruff and black clean on `src/` and `tests/`; mypy `--strict` clean on the
  five files main's merge touched.
- Daemon repaired (`bin/hooks-daemon repair`) and restarted; `status`
  confirms RUNNING against the correct project root.
- Release gate queued in the background:
  `bash /workspace/untracked/scratch/gate.sh worktree-n466-n81-83`.
