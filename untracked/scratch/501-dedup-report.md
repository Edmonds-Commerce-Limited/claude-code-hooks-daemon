# Plan 00501 Task 7.3: observe-mode would-enter dedup

## Change

- `_SessionState.observed_fingerprint` (mirrors `blocked_fingerprint`; same per-session in-memory
  state, so it survives across Stop events identically).
- Observe branch: when unlatched, log the verdict; a WOULD_ENTER latches the current fingerprint.
  While latched, neither near-miss nor would-enter is logged. `restart_count()` is kept so the ring
  stays small.
- Latch cleared by: any HUMAN / GOAL_CLEARED / GOAL_MET transcript event (checked on events, not on
  `fed.resets`, because after `restart_count` the ring is empty and `feed` reports no reset), or a
  fingerprint that differs from the latched one (which also covers the repo-change reset).
- Act mode, thresholds and defaults untouched.

## Near-misses

Suppressed for a latched F. Once the loop is already reported, a near-miss on it is the same loop
re-counting from zero after `restart_count`, i.e. the churn that evicts evidence. Not sensible to keep.

## Tests

Added six tests in TestActMode region (once across many stops, re-arm on human prompt, goal met,
fingerprint change, near-miss silence, latch value). `test_invalid_checkpoint_re_anchors_at_eof`
asserted the old repeating behaviour (near-miss then second would-enter on one unchanged loop); it now
asserts silence, then a re-arm after a human prompt. 125 pass in the two target files; ruff and mypy
clean. Tests ran with PYTHONPATH pointing at the worktree src because the shared venv's editable
install points at main's src (source_tree_guard).

## hook_input at line 180

`matches(self, hook_input)` overrides the base-class abstract signature; the parameter cannot be
removed or renamed without breaking the override contract, so it is not genuinely dead. Left alone.
