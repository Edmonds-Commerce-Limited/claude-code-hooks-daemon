# Plan 00415: config is invisible to the freshness guard

**Status**: Not Started
**Created**: 2026-09-15
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

`compute_source_fingerprint` hashes `.py` files and nothing else. It says so, in
its own docstring, deliberately: *"the fingerprint's contract is 'the code a
running Python process imported', not 'everything under this path'."* Measured
against that contract the function is correct, and this plan does not dispute
it.

Its CONSUMERS ask a different question. The acceptance harness and `smoke_test`
gate a **live dispatch** on the verdict — they use it to decide whether a probe
result can be trusted at all. But a running daemon binds *two* things at
startup, not one: it imports handler modules, and it resolves config at
`initialise()`/`register_all()`. That second binding is precisely why this
project requires a restart after editing `.claude/hooks-daemon.yaml`, and
nothing hashes that file.

So: edit config, skip the restart, and the guard reports FRESH while every
dispatch is graded against the config the daemon bound before the edit. The
failure is the expensive kind — no error, no crash, just a confidently wrong
verdict that a caller consumes as fact.

Not hypothetical. Ledger [00413](../Completed/00413-niggles-ledger-thirteen/PLAN.md) N14
is the evidence: enabling `mode: unattended` on `ask_user_question_blocker`
changed the outcome of three live acceptance probes. Had that edit been made
without a restart, the harness would have certified the run as trustworthy and
graded all three against a handler configured differently from the one on disk.

`describe_fingerprint_mismatch` already treats "cannot verify" as a staleness
RISK rather than "cannot tell", on the stated reasoning that *"a caller that
can't verify freshness must not silently trust a live-dispatch result either."*
That reasoning applies unchanged to the config half. It is the same argument; it
has simply never been extended to the second input.

## Goals

- A config edit without a restart makes the freshness check report STALE, for
  every consumer that gates a live dispatch on it.

- The mismatch message says WHICH input drifted — code or config — because the
  two send a reader to different places to find out what changed, even though
  the remedy (restart) is the same.

- The `.py`-only contract stays honest: nobody reading `compute_source_fingerprint`
  afterwards should be misled about what that particular function hashes.

## Non-Goals

- **Hot-reloading config.** The restart requirement is deliberate and stays.
  This plan detects the un-restarted state; it does not remove it.

- **Widening the fingerprint to "everything under the path".** The `.py` scope
  was a deliberate decision in Plan 00371. The fix here is an additional, named
  input — not the removal of a boundary.

- **Blocking on drift.** The existing consumers decide what to do with a stale
  verdict. This plan changes what the verdict KNOWS, not who is denied.

## Open questions

These need settling before implementation, and they are genuinely open:

- **Hash the file, or the resolved config?** These differ, and the difference
  matters. Hashing `hooks-daemon.yaml`'s bytes is simple, but reports STALE for
  a reformatted comment and misses env-var overrides and any merged config the
  daemon also binds. Hashing the RESOLVED model matches what was actually
  bound, but needs a canonical serialisation stable across runs and across
  Pydantic versions — an unstable one produces a guard that cries stale at
  random, which is worse than the gap it closes.

- **Extend the existing fingerprint, or report a second one alongside?** N17's
  own wording was "mix the resolved config into the identity fingerprint", but
  a single blended digest cannot say which half moved, which the second goal
  above wants. A separate `config_fingerprint` in the health payload keeps both
  answers and leaves 00371's documented contract intact — at the cost of every
  consumer having to check two things, and a consumer that checks only the old
  one is then silently no better off than today. That last point is the
  decisive one and should be weighed, not assumed away.

- **What does an unreadable config mean here?** `compute_current_project_fingerprint`
  deliberately falls back to defaults on a malformed config so a freshness CHECK
  never crashes on an already-broken config. Whatever is hashed must keep that
  property, and must not make "broken config" and "no config" hash alike if the
  daemon would treat them differently.

## Tasks

### Phase 1: Decide and build

- [ ] ⬜ **Task 1.1**: Settle the three open questions above with the owner. The
  second is load-bearing: it decides whether existing consumers need changing
  or inherit the fix for free.

- [ ] ⬜ **Task 1.2**: Read Plan 00371's non-goals and Plan 00395's own
  exclusion note before designing. Both deferred exactly this work, and each
  recorded a reason that deserves an answer rather than a rediscovery.

- [ ] ⬜ **Task 1.3**: Failing test first, and the test must not be the Detector
  (Defence Before Fix clause 3.2): a daemon whose config changed on disk without
  a restart reports STALE, and one whose config is untouched still reports FRESH
  across repeated runs. The second half guards against an unstable
  serialisation passing as a fix.

- [ ] ⬜ **Task 1.4**: Implement, and prove the determinism property explicitly
  — the same config resolved twice in separate processes hashes identically.

- [ ] ⬜ **Task 1.5**: Sweep the consumers: the acceptance harness, `smoke_test`,
  `bin/hooks-daemon check-source-fresh`, and the `_system`/`health` socket
  payload. A consumer left reading only the code fingerprint is the failure
  mode Task 1.1's second question is about, so this sweep is where that decision
  gets enforced rather than assumed.

## Success Criteria

- [ ] ⬜ Editing `.claude/hooks-daemon.yaml` without restarting makes the
  freshness check report stale, demonstrated end to end against a live daemon
  rather than only in unit tests.

- [ ] ⬜ Re-running the check with nothing changed reports fresh every time — no
  flapping from an unstable serialisation.

- [ ] ⬜ The reader of a stale verdict can tell whether code or config moved.

- [ ] ⬜ A malformed config still produces a verdict rather than a crash.

- [ ] ⬜ Full QA passes, the daemon is restarted, and CI is green.

## Delivery & Milestones

- Graduated from ledger [00413](../Completed/00413-niggles-ledger-thirteen/PLAN.md) N17,
  which was recorded with evidence but deliberately left unfixed: the remedy
  changes a safety mechanism every acceptance test gates on, and that ledger had
  already rewritten enough of that surface in one pass.

- Prior art, checked before filing: Plan 00371 built the fingerprint and placed
  config-only staleness in its non-goals; Plan 00395 recorded config drift as
  something it deliberately did not cover; Plan 00389 reconciles config after a
  `git pull` only, so a direct edit falls outside it. No live plan covers this.
