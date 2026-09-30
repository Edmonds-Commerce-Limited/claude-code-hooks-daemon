# N276: the SessionStart chain overruns its budget and starves persistent_cron_assertor

## Where the budget is enforced

`HandlerChain.execute` (`src/claude_code_hooks_daemon/core/chain.py`) runs the WHOLE
handler loop as ONE dispatched call bounded by `deadline_seconds`. The chain had
started; no handler was queued or locked. When the call outlived the budget the
caller abandoned it and, for a chain with no SAFETY+BLOCKING handler, returned
"Chain skipped: exceeded its 20.00s dispatch budget" with nothing else. Every
handler that had already returned was discarded with it. Handlers run serially in
priority order, so anything after the overrun never ran.

No single handler overran. The total did.

## Per-handler timings (this repository, load average 20 to 33, worktree config)

Two full runs of every SessionStart handler's `matches()` plus `handle()` in
isolation (`untracked/scratch/time_session_start.py`). Totals were 43.8 s and 33.4 s
over 31 handlers; the budget is 20 s.

| handler                     | priority | run 1            | run 2  |
| --------------------------- | -------- | ---------------- | ------ |
| docs-qa-sweep               | 64       | 12.7 s           | 6.4 s  |
| gitignore-safety-checker    | 54       | 12.4 s           | 9.9 s  |
| secret-file-hygiene-checker | 62       | 8.5 s            | 8.6 s  |
| git-upstream-checker        | 56       | 3.0 s            | 3.2 s  |
| plan-qa-sweep               | 57       | 2.9 s            | 2.0 s  |
| tool-disable-advisor        | 65       | 1.2 s            | 1.2 s  |
| persistent-cron-assertor    | 70       | 0.50 s           | 0.52 s |
| every other handler         | -        | under 0.7 s each |        |

`persistent_cron_assertor` needed half a second but sits at priority 70, behind
about 30 s of sweeps.

## What spends the time

cProfile of the three slowest: about 18,000 paths per sweep (tracked plus
untracked-visible plus ignored, `untracked/` holds venvs and worktrees) each go
through `path_is_protected` / `protecting_pattern`, about 1 ms each, dominated by
`realpath`/`lstat` and glob matching. The four `git ls-files` calls behind
`scan_git_file_states` cost about 2 s in total. `gitignore_safety_checker`,
`secret_file_hygiene_checker` and `docs_qa_sweep` each repeat that per-path scan.

## Root cause

Two defects compounding: (1) a serial chain whose cheap, high-value handlers were
ordered behind repository-walking sweeps by priority number alone; (2) a budget
overrun threw away the output of handlers that had already finished.

## Change

- `HandlerTag.SLOW_SWEEP` (`constants/tags.py`): `HandlerChain.handlers` now sorts
  `(is slow-sweep, priority, name)`, so a tagged handler runs after every untagged
  one. Applied to gitignore_safety_checker, secret_file_hygiene_checker,
  docs_qa_sweep, plan_qa_sweep, git_upstream_checker, reference_repo_sweep.
- `core/chain.py`: a `_ChainProgress` record is shared with the loop thread. On a
  whole-chain timeout of a chain without a SAFETY+BLOCKING handler, `execute()`
  merges the finished handlers' results through the same
  `_assemble_final_result` the normal path now uses (extracted, not duplicated),
  and appends "Chain cut short: ...; the output of the N handler(s) that finished
  is kept". When nothing finished the old "Chain skipped" reply is unchanged.
  Fail-closed behaviour for SAFETY+BLOCKING chains is unchanged. The budget is
  unchanged.
- Release note 190.

The per-path protection scan itself was not optimised: it is the security matcher
shared with the PreToolUse guards, and changing it is out of proportion for this
ledger entry. It remains the real cost of the sweeps (see Unverified).

## Verification

- Red run first: 4 new tests failed (2 assertion failures on discarded output, 2
  `AttributeError: HandlerTag has no attribute SLOW_SWEEP`).
- Real chain with a 20 s budget under load 20 (`untracked/scratch/run_chain.py 20`):
  23 handlers finished, `persistent-cron-assertor` among them, sweeps after it,
  reply carried "Chain cut short: exceeded its 20.00s dispatch budget; the output
  of the 23 handler(s) that finished is kept". Before the change the same run
  would have returned only "Chain skipped".

## Unverified

- The deployed hook path through the relay and a real restarted session was not
  exercised; only `HandlerChain.execute` against the real SessionStart handlers.
- The sweeps still cost 30 s under load, so on a loaded host their advisories are
  still cut short. That is now a partial loss of advisories, not of the crons.
