# N398 hotfix report

## Cause

The first N398 fix gave two `WorktreeFileCopyHandler` probes `cwd: "/"`. The playbook harness drives probes through the
whole daemon chain, and `project_containment` runs first: `src/` read against `/` is `/src`, outside the project, so it
denied with R-WRITE-OUTSIDE-PROJECT-ROOT in the handler's place.

## Options evaluated

- (a) `$CLAUDE_PROJECT_DIR` as-is: expands to the suite's checkout, i.e. the worktree. Wrong in exactly the failing case.
- (b) cwd = main checkout computed by the harness: chosen, exposed as a placeholder so the probe declares it.
- (c) Absolute destination: the main checkout path is unknown to a declared probe.

## Fix

- `daemon/playbook_harness.py`: new `main_checkout_root(project_root)` (parent of `.claude/worktrees/` or
  `untracked/worktrees/`, else the root itself; prefixes come from `ProjectPath`). `expand_project_dir` now also resolves
  `$MAIN_CHECKOUT_DIR` / `${MAIN_CHECKOUT_DIR}`. Both harnesses plan probes with `plan_probe`, which expands
  `extra_hook_input`, so both get it.
- `handlers/pre_tool_use/worktree_file_copy.py`: `_MAIN_CHECKOUT_CWD` is `{cwd: "$MAIN_CHECKOUT_DIR"}`. Handler logic
  unchanged.

## Tests (red first)

- `tests/integration/test_acceptance_contract.py::TestWorktreeCopyProbesDoNotDependOnWhereTheSuiteRuns::test_the_event_the_playbook_dispatches_stays_inside_the_main_checkout`
  (parametrised: main root and a `.claude/worktrees/x` root). Builds the playbook event and asserts cwd is the main
  checkout and `src/` against it stays inside it, then drives the handler. Red before the fix (cwd was `/`), green after.
- `tests/unit/daemon/test_playbook_harness.py::TestMainCheckoutDir`: 7 tests of the resolver and expansion.

## Results

- Worktree, `tests/integration/test_acceptance_contract.py` + `tests/unit/daemon/test_playbook_harness.py`: 74 passed.
- Worktree, `tests/acceptance/test_playbook_harness.py` + contract file: 5 passed, 5 skipped (the acceptance file skips:
  no live daemon socket under the worktree's `untracked/`).
- Main checkout (`cd /workspace`, `PYTHONPATH=<wt>/src`, `--rootdir=<wt>`, test paths in the worktree): same 5 passed,
  5 skipped. The acceptance file finds sockets from the test file's own location (the worktree), and the main daemon's
  staleness check would also compare against the worktree source, so this form cannot reach a live daemon without
  starting one. I did not start or stop any daemon.
- Substitute that does reach the daemon: `untracked/scratch/probe114.py` plans both probes with the real `plan_probe`
  and `build_event` (the playbook path), sends them to the live daemon guarding `/workspace`, and applies the
  decision and message patterns. Run with suite root = `/workspace` and suite root = the worktree: both probes were
  deny with the handler's own messages, cwd `/workspace` in both. This simulates only the dispatch; it is not the
  pytest file itself, and the running daemon holds main's handler code (unchanged by this fix).
