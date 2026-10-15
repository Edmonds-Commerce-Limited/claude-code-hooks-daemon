# Task 2.6: result cache for docs-qa-sweep and plan-qa-sweep

Commit: 78a7fa47d (code, tests, release note 066); the PLAN.md tick and this report are in the follow-up commit.

## Assumptions (owner decisions I took, to be ruled on)

1. **A cache miss waits at most 1.0 s** (`DEFAULT_WAIT_SECONDS` in `utils/sweep_cache.py`) for the background sweep. A sweep that finishes in that time is reported this session; otherwise the handler reports "still running in the background" and the result is cached for the next session. This is a trade: a larger wait delivers more findings in-session but blocks the chain; two cold sweeps cost up to 2 s of chain.
2. **On a pending miss the previous cached result is shown, explicitly labelled "may be out of date"**, next to the notice. The alternative (show nothing) leaves a developer whose every session has edits permanently without findings. The stale result is never served as current: only an exact fingerprint match is a hit.
3. **The fingerprint covers every file in the project**, not just markdown, outside a prune list (`.git`, `node_modules`, `__pycache__`, `.venv`, tool caches anywhere; `untracked/` and `.claude/hooks-daemon/` at the project root only). Reason: `pointer-resolves` and the plan `path-existence` checks open non-markdown link targets, so a deleted `.py` file creates a new finding without touching any `.md`. The walk costs about 0.1 s on this repository (5.8k files).
4. Release note taken as 066; the coordinator renumbers on a clash.

## What changed

- `src/claude_code_hooks_daemon/utils/sweep_cache.py` (new): `tree_fingerprint` (sha256 of path, mtime_ns, size, inode of each file plus caller-supplied extras), `run_cached_sweep` (hit / compute on a daemon thread with bounded wait / pending), `pending_context`, `SweepOutcome.advisory`. Cache at `<daemon untracked dir>/sweep-cache/<sweep>.json`, written atomically; an unreadable or malformed file is a logged miss; concurrent requests for one fingerprint share one computation; a compute error inside the wait is re-raised to the caller (as before), after the wait it is logged.
- `handlers/session_start/docs_qa_sweep.py` and `plan_qa_sweep.py`: `handle()` fingerprints, then calls `run_cached_sweep`; the previous body moved to `_sweep()`. Docs extras: daemon version, date, `repr(policy)`, `repr(layout)`. Plan extras: version, date, `repr(policy)`, plan dir, exclude paths, HEAD sha, plan counter (the two git facts the plan sweep reads: last-commit dates and `hooksdaemon.latestPlanNumber`).
- Both handlers keep `SLOW_SWEEP` (still ordered last). Each has `_sweep_wait_seconds` so tests can set it.
- Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/066-qa-sweeps-cached-and-off-the-session-start-chain.md`.

## TDD: red output

Tests were written first. Before the handlers changed, with `sweep_cache` missing:

```
ModuleNotFoundError: No module named 'claude_code_hooks_daemon.utils.sweep_cache'
```

and with the handler tests added but the handlers unchanged (122 s, because the slow-sweep test blocked on the old synchronous path):

```
FAILED tests/unit/handlers/session_start/test_docs_qa_sweep.py::TestSweepCache::test_unchanged_inputs_reuse_the_cached_report - AssertionError: assert 2 == 1
FAILED tests/unit/handlers/session_start/test_docs_qa_sweep.py::TestSweepCache::test_slow_sweep_is_reported_pending_without_blocking_the_chain - AssertionError: assert 'background'
FAILED tests/unit/handlers/session_start/test_plan_qa_sweep.py::TestSweepCache::test_unchanged_inputs_reuse_the_cached_report - AssertionError: assert 2 == 1
FAILED tests/unit/handlers/session_start/test_plan_qa_sweep.py::TestSweepCache::test_slow_sweep_is_reported_pending_without_blocking_the_chain - AssertionError: assert 'background'
4 failed, 37 passed in 122.46s
```

(The invalidation tests passed pre-change because nothing was cached; they guard the new code.) After: 76 passed in 1.31 s across `test_sweep_cache.py`, `test_docs_qa_sweep.py`, `test_plan_qa_sweep.py`, `test_slow_sweep_tag.py`; 382 passed across the guidance-coverage, workspace-scope and session-actions tests that mention these handlers.

Invalidation tests (a stale cache must never hide a new finding): editing a scanned markdown file; fixing drift (the finding disappears); deleting a linked non-markdown file (dead link appears); a policy change; a new day and a new commit (plan sweep); adding, deleting, same-size-rewrite (mtime only) and extra-input changes at the fingerprint level; churn inside pruned directories does not invalidate, while a nested directory named `untracked` does.

## Measurement (same method as Task 1.2)

`chain_timing.py` from `/workspace/untracked/scratch/startup-profile/`: controller built on a clone of the repository (own process, never the live daemon), SessionStart handlers run sequentially without the dispatch budget. Host idle (load 1.6 to 2.9, versus 24 to 40 in Phase 1), so absolute numbers are lower than the Phase 1 table; the before and after rows below are on the same idle host. "Before" is a clone at 75fe038df, "after" is the same plus this change. Raw output: `untracked/scratch/before-chain.txt`, `after-chain-sleep.txt` (not committed; gitignored).

| SessionStart (this repository)   | before (3 rounds)     | after, cache hit     | after, cold miss      |
| -------------------------------- | --------------------- | -------------------- | --------------------- |
| docs-qa-sweep wall               | 8.01 / 3.30 / 3.41 s  | 0.09 to 0.14 s       | 1.09 s (bounded wait) |
| docs-qa-sweep CPU incl. children | 7.84 / 3.26 / 3.37 s  | 0.09 to 0.13 s       | 1.29 s                |
| plan-qa-sweep wall               | 1.58 / 1.20 / 1.44 s  | 0.10 to 0.13 s       | 1.13 s (bounded wait) |
| plan-qa-sweep CPU incl. children | 1.56 / 1.19 / 1.42 s  | 0.10 to 0.13 s       | 1.08 s                |
| Sequential chain total           | 12.67 / 5.80 / 6.46 s | 2.02 / 1.88 / 2.20 s | 4.99 s                |

Round 1 before includes a cold docs index. In the cold-miss column the sweep keeps running on its thread after the handler returns, so the chain does not wait for it; the remaining 5 s of that round are the other handlers plus a first-use cost, and that process's CPU is shared with the background sweep. A hit costs the fingerprint walk (about 0.1 s) and nothing else.

Cold-start note: the 4.99 s chain total is dominated by non-sweep handlers on a first run (about 1.6 to 2 s steady, more on a cold file cache); I did not separate them further.

## Known limits

- **A daemon restart is a miss.** Controller build rewrites `CLAUDE.md` and `.CLAUDE.md.pre-inject` (verified by diffing file stats before and after: those two files are the only change), which moves the fingerprint. Task 2.4 (skip the CLAUDE.md rewrite when the block is unchanged) removes that; until it lands, the first session after each daemon start is a cold miss (bounded to 1 s per sweep). Within a daemon's lifetime sessions hit.
- A sweep still in flight when a second request for the same fingerprint arrives makes that request wait up to 1 s too.
- The background compute runs with no dispatch-cancellation binding, so an expired chain budget does not cancel it (intended: its only side effect is the cache write and the docs index).
- Not covered: files changed within one filesystem timestamp tick that keep the same size and inode (mtime key); the fingerprint is stat-based, not content-based, matching how the docs corpus index already treats files.

## QA

`./scripts/qa/llm_qa.py changed`: the first run waited the full 600 s for the host-wide QA lock (held by other agents' runs) and exited 4 without running. Re-run with `FULL_QA_LOCK_WAIT_SECONDS=3000`; verdict recorded below.

QA verdict: PENDING (see the coordinator message for the final verdict and exit status).
