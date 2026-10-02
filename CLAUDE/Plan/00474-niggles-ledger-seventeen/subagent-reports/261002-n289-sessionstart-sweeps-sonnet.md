# N289: SessionStart sweeps overrun the 20 s budget (sonnet)

## Phase 1: measurement

Method: a scratch script builds the real controller from this repository's
`.claude/hooks-daemon.yaml` (`_build_initialised_controller`), then times
`matches()` + `handle()` of every SessionStart handler in chain order for a
`source: startup` payload, in a fresh process each run (so process-lifetime
caches are cold). Three runs each, before and after.

Before (seconds per handler, three runs):

| handler                     | run 1 | run 2 | run 3 |
| --------------------------- | ----- | ----- | ----- |
| docs-qa-sweep               | 4.25  | 2.19  | 2.15  |
| gitignore-safety-checker    | 3.54  | 3.45  | 3.21  |
| secret-file-hygiene-checker | 3.33  | 3.45  | 3.42  |
| git-upstream-checker        | 2.27  | 2.28  | 2.17  |
| contract-staleness          | 1.18  | -     | -     |
| plan-qa-sweep               | 0.73  | 0.76  | 0.96  |
| version-check               | 0.46  | -     | -     |
| tool-disable-advisor        | 0.32  | 0.38  | 0.29  |
| reference-repo-sweep        | 0.00  | 0.00  | 0.00  |
| chain total                 | 16.7  | 12.7  | 13.2  |

The serial sum is 13 to 17 s on an idle process; the daemon adds its own
overhead (the coordinator saw 20.4 s), so the chain sits on the budget edge.

Profile (cProfile) of the three slowest: each sweeps about 18,000 repository
paths through `path_is_protected` / `protecting_pattern`. About half of that is
the glob matcher (`_glob_fullmatch`, a pure-Python reachability sweep built per
path per pattern), the other half is two `os.path.realpath` walks per path
(`has_symlink_loop` strict, then `realpath` non-strict), roughly 460,000 `lstat`
calls. `git_upstream_checker`'s 2.2 s is the additive `git fetch --all`, which
is network/IO bound and left alone.

## Is late output delivered?

No. `BoundedDispatcher.run` abandons the chain thread on timeout and only
attaches `_log_late_completion`, which logs "finished N s after its dispatch
budget expired". Nothing stores the result or injects it on a later event, and
`HandlerChain.execute` builds its reply from a `progress.snapshot()` (a deep
copy) taken at the cut-off. So a sweep that has not returned by the budget loses
its findings for that session, with no later delivery. Before this change the
reply said only "the output of the N handler(s) that finished is kept"; it did
not name the handlers that did not, so the drop was silent.

## Changes

1. `utils/path_exclusion.py`: `_literals_present` rejects a pattern before any
   sweep when one of its literal runs is not a substring of the path. This is a
   necessary condition for a full match (the sweeps only consume a literal by
   finding it), so answers are unchanged; a differential test compares against
   the unfiltered sweep.
2. `utils/realpath.py` + `utils/secret_file_matching.py`:
   `resolve_checking_loop` returns `(realpath, has_symlink_loop)` from one strict
   walk for an existing path and falls back to the two original calls otherwise.
   `protecting_pattern` uses it; a symlink loop is still protected by every
   pattern, and a NUL byte is still matched as spelled. Differential tests
   (exhaustive shapes plus 2,000 generated adversarial paths) check equality
   with the pair it replaces.
3. `core/chain.py`: `_ChainProgress.entered` records how many handlers the loop
   began; on a cut-off the "Chain cut short" and "Chain skipped" notes now end
   with `did not finish: <running handler and every one behind it> (their output is dropped)`.
4. Release note 210.

After (three runs): docs-qa-sweep 1.3 to 1.4 s, gitignore-safety-checker 1.5 to
1.6 s, secret-file-hygiene-checker 1.6 s, git-upstream-checker 2.2 to 2.3 s,
plan-qa-sweep 0.8 s. Chain total 8.3, 8.5, 8.6 s (was 12.7 to 16.7 s). The 20 s
budget is unchanged.

## Recommendations (not built)

- The remaining cost of the three path-scanning sweeps is the realpath `lstat`
  walk, repeated for the same ~18,000 paths by each of three handlers. A
  per-session shared scan result (computed once, read by all three) would remove
  two thirds of it. It touches the security matcher's callers, so it needs its
  own entry.
- If findings must survive a cut-off, the late result would have to be stored by
  the dispatcher and injected on a later event. That is a new delivery mechanism
  and was deliberately not built here; naming the dropped handlers is the
  minimum that keeps the loss from being silent.
- `git_upstream_checker`'s fetch is the largest single remaining item (2.2 s)
  and depends on the network.

## Tests

Red first: new tests failed (ImportError for `resolve_checking_loop`; chain
tests lacked the "did not finish" text). After: tests/unit/utils/test_realpath.py,
test_path_exclusion.py, test_secret_file_matching.py and tests/unit/core/test_chain.py:
818 passed.
