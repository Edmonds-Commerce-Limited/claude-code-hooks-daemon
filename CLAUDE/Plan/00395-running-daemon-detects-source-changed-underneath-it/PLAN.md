# Plan 00395: running daemon detects source changed underneath it

**Status**: Not Started
**Created**: 2026-09-13
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Direct

## Overview

A daemon loads its code once and serves it for the life of the process. When a
DIFFERENT session or process on the same filesystem upgrades or edits that
installation — a `/hooks-daemon upgrade`, a `git pull`, another agent editing a
handler — **the running daemon keeps serving the code it loaded at startup and
never says so.** Every safety handler in the process is then the OLD version,
and the only symptom is behaviour that silently does not match the tree.

The detection itself is already built and correct. What is missing is that
nothing invokes it while the daemon is alive.

## What already exists — this is a wiring gap, not a new capability

Plan 00371 shipped the whole primitive:

| Piece                                       | Where                                               |
| ------------------------------------------- | --------------------------------------------------- |
| `compute_source_fingerprint(*roots)`        | sha256 over every `.py` the daemon would load       |
| `compute_current_project_fingerprint(root)` | what a freshly-started daemon WOULD load            |
| `describe_fingerprint_mismatch(run, cur)`   | the comparison, with a `STALE DAEMON` diagnostic    |
| `DaemonController._source_fingerprint`      | recorded at startup, served over `_system`/`health` |
| `bin/hooks-daemon check-source-fresh`       | CLI verb wrapping the comparison                    |

Two facts establish the gap, both read out of the code rather than inferred:

1. **`_source_fingerprint` is assigned once** in `initialise()`
   (`controller.py:312`) and thereafter only READ (`controller.py:1120`, the
   health response). The daemon never recomputes it, so it cannot notice its own
   source moving.
2. **The only automatic caller is `scripts/qa/run_smoke_test.sh`**, which runs
   as part of a full QA sweep. Grepping every caller of
   `describe_fingerprint_mismatch` and `compute_current_project_fingerprint`
   returns `cli.py` and nothing else — no SessionStart handler, no dispatch
   path, no timer.

So a stale daemon is discovered only by running full QA or by a human typing the
CLI verb. Neither happens in the scenario that motivates this plan.

## Why the three adjacent plans do not cover it

Checked against the plan tree (and confirmed by the dedupe scout across 18 live
and 353 archived plans):

- **00386** — a stale CLONE reconciled at STARTUP, before the daemon runs.
- **00389** — a `git pull` performed IN THE CURRENT SESSION; advisory only, and
  its own index row records that it "sees an in-session pull only".
- **00371** — the startup fingerprint, built for QA acceptance probes.

This plan is the space between them: an already-running daemon noticing an
out-of-band change made by someone else.

## The cheap gate is a trap, and it was measured rather than assumed

Any live check needs a gate, because hashing every `.py` in the package on each
hook dispatch is far too expensive. The obvious gate is mtime. **It does not
work for the redeploy shapes that cause this bug**, and neither does inode
comparison. Measured directly — a `cp -p` over a file with different content:

```text
before cp -p:  mtime=1789311874  ctime=1789311874  ino=425451172
after  cp -p:  mtime=1789311874  ctime=1789311875  ino=425451172
content:       changed
```

mtime unchanged, inode unchanged, **ctime advanced**. `cp -p` and `rsync -a`
preserve mtime deliberately; no flag preserves ctime, because the kernel sets it
on any inode change. An mtime-gated check therefore fails silently at exactly the
moment it is needed — an installer-style redeploy — which is worse than no check,
because it reports freshness it did not verify.

**And the correct gate is cheap enough to need no cleverness.** Measured on this
package's 535 `.py` files:

```text
ctime sweep over all 535 files:  0.64 ms
full sha256 hash of all 535:     8.25 ms
```

So the honest gate costs about a thirteenth of the comparison it guards, and
0.64 ms is negligible against a hook dispatch. That removes the usual reason for
reaching for mtime or for a throttle: the design does not have to trade
correctness for cost, because the correct version is already cheap. These
numbers are a starting point for Task 2.3, not a substitute for measuring the
real integrated path.

The same trap is already documented for the ccy supervisor's worker reload
(`.claude/ccy/` contract: "A redeploy that preserves mtime can change the
CONTENT without advancing mtime"), so this is the second appearance of one root
cause and the fix should be shared rather than re-derived.

## The action on detection is ALREADY RULED — do not re-open it

The owner's standing ruling on this class of problem is **advise loudly, name the
command; never auto-restart, never auto-upgrade**. That is the behaviour Plans
00386 and 00389 shipped, and it applies here unchanged. This plan decides WHERE
the check runs, not what it does when it fires.

## The open question — where the check runs

1. **SessionStart handler.** Cheapest, reuses the CLI comparison as-is, one hash
   sweep per session. Catches "another session upgraded it since I last started"
   — but NOT the motivating case, because a session already in flight never
   re-checks. Useful, insufficient alone.
2. **Gated check on hook dispatch.** Stat a small set of sentinel paths, compare
   **ctime** (never mtime alone), and do the full hash only when something moved.
   Catches the mid-session case, which is the actual request. Cost must be
   measured, not assumed — it lands on the hot path.
3. **Periodic self-check in the daemon.** A timer recomputing the fingerprint
   every N seconds. Thorough and off the hot path, but adds a thread and can
   report staleness at a moment when nothing is listening.
4. **Writer announces instead of readers polling.** `scripts/upgrade.sh` and the
   install path signal any running daemon directly. Near-zero cost and exact,
   but only covers changes made THROUGH those scripts — a manual `git pull` or
   another agent's edit is missed.

These are not exclusive: 4 is the cheapest correct signal for the common case and
2 is the backstop for everything else. 1 is worth having regardless.

## Goals

- A daemon whose on-disk source has changed since it started says so, without
  being asked, while it is still running.
- The staleness gate is robust against mtime-preserving redeploys.
- The existing fingerprint comparison is reused, not reimplemented.
- On detection: advise loudly and name the restart command. Never self-restart.

## Non-Goals

- Auto-restarting or hot-reloading the daemon. Explicitly ruled out by the
  owner's standing position.
- Making config changes detectable. The fingerprint hashes `.py` files only; the
  project yaml is read solely to resolve `project_handlers.enabled`/`.path`, so
  toggling project handlers moves the fingerprint but ordinary config edits do
  not. Plan 00389 owns config drift — this plan must not silently half-cover it.
- Replacing Plan 00386's startup reconciliation or 00389's in-session pull
  advisory.

## Tasks

### Phase 1: Owner decision

- [ ] ⬜ **Task 1.1**: Owner picks the placement — option 1, 2, 3, 4, or a
  combination. The choice decides the test matrix and whether the hot path is
  touched at all.

### Phase 2: Build, once decided

- [ ] ⬜ **Task 2.1**: A failing test first: a daemon running against a tree
  whose source is then replaced **with mtime preserved** must be reported stale.
  That is the case an mtime gate passes wrongly, so it is the test that has to
  exist before any gate is written.
- [ ] ⬜ **Task 2.2**: Implement the chosen placement, reusing
  `describe_fingerprint_mismatch` rather than a second comparison.
- [ ] ⬜ **Task 2.3**: If the hot path is touched, MEASURE the per-dispatch cost
  and record the number. An unmeasured hot-path check is a regression waiting to
  be discovered by someone else.
- [ ] ⬜ **Task 2.4**: Pin that the advisory names the restart command and never
  restarts anything.
- [ ] ⬜ **Task 2.5**: Factor the ctime-based staleness gate so the ccy
  supervisor's worker reload can use the same one — same root cause, currently
  solved twice.

## Success Criteria

- [ ] A running daemon whose source is replaced out-of-band reports itself stale
  without being asked.
- [ ] It still reports stale when the replacement PRESERVED mtime, proven by a
  test that fails against an mtime-only gate.
- [ ] The advisory names the restart command and nothing restarts itself.
- [ ] If the hot path is touched, the added per-dispatch cost is measured and
  recorded in this plan.
- [ ] Every release-bound consequence is in the pending-release holding area, or
  this plan records why it has none.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

- Raised by the owner: the daemon detects when it is out of date, but not when
  it has been updated underneath it by another session on the same filesystem.
- Investigation found the capability already shipped in Plan 00371 and simply
  never wired to an automatic caller, which makes this a wiring plan rather than
  a new subsystem.
- The ctime-versus-mtime finding was measured in a scratch probe rather than
  taken from memory, because the whole plan turns on the gate being trustworthy.
