# Plan 00398 — implementation and test review

Supporting document for [PLAN.md](PLAN.md). Holds the review of the Phase 2–4
implementation: what was checked against the code, what the tests pin, what ran
live, and the risks accepted rather than resolved.

Extracted from PLAN.md to keep the plan lean; this is the durable detail, not a
narrative log (that lives in `JOURNAL/`).

## Implementation review — verified, not accepted on report

The implementation arrived with a self-reported 29/29 pass. That was not taken
on trust; each claim below was checked against the code.

- **Stability is keyed on last-CHANGED, not first-non-empty.** `feed` diffs the
  buffer before/after and stamps `_last_changed_at` only on a real change;
  `is_abandoned` is False while empty or never-changed. A human typing
  continuously can never age into abandonment — the case the ruling depends on.
- **The latch resets at the TOP of `_evaluate_monitor`**, before every early
  return, so a stale/non-red/ambiguous tick cannot leave it armed for a later
  unrelated episode.
- **The flush sits inside `if not idle:` and BELOW the `reading.red` check**, so
  abandoned text is never submitted at low context — only when a compaction is
  actually wanted.
- **Clock sources agree**: `now_wall = time.time()` feeds both `is_abandoned`
  and the tick's other wall-clock timers.
- **Host-only, deliberately not ANDed with the worker's view** (unlike
  `input_line_empty`). The worker's recognizer resets on every hot-reload with
  no byte-history replay, so ANDing would silently reopen the unbounded gate for
  up to the full threshold after each reload — and indefinitely if no further
  human byte arrived. Correct, and the reasoning is at the call site.
- **`_last_action_ts` is deliberately NOT touched by the flush.** Touching it
  would arm the compact cooldown against the flush and delay the compaction it
  exists to unblock. CRITICAL bypasses cooldown, but the production incident's
  band was `[urgent]`, which does not — so this would have reproduced a milder
  form of the bug being fixed.

## Test review — the ruling's safety property is pinned

The tests were reviewed separately from the implementation, because a
self-reported pass count is worth nothing if the tests do not pin what the
ruling asked for.

The load-bearing one is `test_continuous_typing_never_reads_abandoned`: 200
keystrokes over 200s leave the box far older than the threshold and it still
never trips — the exact case a naive "non-empty for N seconds" timer gets wrong.
Supported by the just-under boundary, the clock restarting after a submit, and
`clear` resetting the stability clock. `TestRunWorkerClearsOwnRecognizer` pins
the two-tier reset that would otherwise hold the worker's own view non-empty
forever.

**The one case where this acts on LIVE human text, stated plainly**: a human who
sits re-reading their own unsent message for 120s without changing a character
will have it submitted, then the session compacts. That is the ruling as made,
not a gap — but it is the behaviour to revisit first if the threshold ever feels
wrong, so it is recorded here rather than left implicit in a test name.

## Live dogfooding: the change does not regress the normal path

The worker reloaded the implementation at **09:33:19** (pid `1089824`, start
time matching the file's mtime — checked with `ps`, per the hot-reload contract,
not inferred from the edit). It has been deciding live ever since. At 09:51 the
live session compacted:

```text
09:51:41 would-compact: red at 43% + idle -> would inject /compact
09:53:17 would-continue: compaction detected -> would inject continue
```

That is the ORDINARY idle path, not this plan's new branch — the flush lives
inside `if not idle:` and would have logged `abandoned_box_flush`. So it does
not exercise the feature. What it does show is that the new code still compacts
normally when the box is empty and the session settles, which the unit tests
cannot demonstrate. Recorded because it is easy to mis-cite this as evidence the
FIX works; it is evidence the fix does not BREAK what already worked.

## Residual risk, recorded rather than resolved

The host force-clears its own tracker on flush
(`on_input_line_flushed=activity.line.clear`). If the Enter did NOT clear the
real box, the tracker now reads empty while the box is not, and the next tick
could inject `/compact` into a non-empty box — the invariant the gate exists
for.

Judged acceptable and NOT blocking: the pre-existing `would-resubmit` path for
the supervisor's OWN line already presses Enter and proceeds identically, so
this is not a new class of risk, and a `/compact` that fails to land is already
caught by the AWAIT `[esc]` flush. Recorded because the alternative — never
clearing — reintroduces the unbounded gate this plan exists to close.

## Pre-existing interaction, surfaced not introduced

Plan 00183's dry-run "fires once per session" latch is shared across ALL
decision types. In dry-run an abandoned-box flush consumes that budget, so the
follow-on compact logs `dry-run already fired once this session` instead of a
second marker. Armed mode is unaffected; dry-run demos of this feature show the
flush but never the compact.
