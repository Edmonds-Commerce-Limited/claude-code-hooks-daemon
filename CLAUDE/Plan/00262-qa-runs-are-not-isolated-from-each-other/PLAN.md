# Plan 00262: QA runs are not isolated from each other

**Status**: Not Started
**Created**: 2026-08-19
**Owner**: Unassigned
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

Nothing stops a second `llm_qa.py` / `run_all.sh` run starting while one is
already in flight. Both write coverage to the same `untracked/qa/coverage.json`
and both drive the same `tests/` tree, so the two runs contend and neither
verdict can be trusted — in either direction. A contended run can fail a check
that is actually fine, and it can pass one that is not.

That matters more than an ordinary flake because this is a **gating** signal.
`CLAUDE.md` and `RELEASING.md` both make a green QA run a precondition for
committing and for releasing. A guard whose verdict is unreliable under a
condition nobody detects is worse than one that is merely slow: it converts a
blocking gate into a coin flip without ever saying so.

**This was found by causing it, not by auditing for it.** During Plan 00261 an
agent resumed after a compaction, started a QA run without checking whether one
was already running, and had two suites racing for ~7 minutes. Earlier in the
same session a `test_install_sh_end_to_end` failure from the same cause was
dismissed as a one-off — which is the real cost: a contended run teaches you to
discount failures.

## Goals

- A second QA run cannot silently race a first. Either it refuses with a message
  naming the live run, or it waits — decided in Task 1.2.
- The refusal explains itself well enough that the agent does the right thing
  (wait, or inspect the running one) rather than working around the lock.
- Read-only inspection of a run in progress stays possible.

## Non-Goals

- **Not** making QA runs safely parallel. Serialising is the goal; genuine
  parallelism would need per-run coverage files and test-fixture isolation, and
  buys nothing — the suite is already the long pole either way.
- **Not** a general job scheduler, and not a lock on individual QA tools invoked
  directly (`pytest`, `ruff`). The gate is the suite runner.

## Context & Background

Two facts that shape the design:

- `--read-only` in `llm_qa.py` does **not** run tools; it only summarises
  existing JSON (`scripts/qa/llm_qa.py:604` is the executing loop, guarded by
  `if not read_only`). So a lock belongs on the *executing* path only. Locking
  `--read-only` too would block the very command an agent would reach for to
  inspect a run already in progress.
- The coverage layer has no concurrency story at all: `pyproject.toml:114`
  records that coverage `parallel` mode is disabled because it "causes fork bomb
  when running pytest with `--cov`". So sharing one `coverage.json` between
  concurrent runs is not a small overlap to tidy up — concurrency was never
  supported here.

### The secondary finding, and why it is secondary

`tests/acceptance/test_install_sh_end_to_end.py:67-98` mutates the **shared**
repository's worktree registry: `_create_daemon_worktree` runs
`git worktree add --detach` against `REPO_ROOT` and teardown runs
`git worktree remove --force`; the upgrade test additionally `git clone`s from
the same repo. The test isolates `HOSTNAME` and `tmp_path` carefully but not
`.git/worktrees/`, so two concurrent runs of that file collide.

This is a **deliberate v3.11.0 trade-off, not an oversight** — Plan 00105 Task
1.3 added the clone helpers for the upgrade tests and explicitly records
`_create_daemon_worktree` as "retained for install tests where worktrees still
work". It has not been revisited since.

It is secondary because **Phase 1 largely subsumes it**: once the suite runner
refuses to run twice at once, the collision stops being reachable by the route
that actually bit us. What remains is the narrower case of someone invoking
`pytest` on that file directly, in parallel — which is why Phase 2 is scoped to
*decide*, and is explicitly allowed to conclude "leave it".

## Tasks

### Phase 1: serialise the suite runner

- [x] ✅ **Task 1.1**: RED — a test that starts a run while a lock is held and
  asserts the second does not proceed to execute tools. Must also assert that
  `--read-only` is unaffected. Delivered as
  `tests/unit/qa/test_llm_qa_run_lock.py` (7 tests). The contention test spawns
  a REAL second process, because `flock` is advisory per open-file-description
  and a same-process second acquire would prove nothing.
- [x] ✅ **Task 1.2**: Decide refuse-vs-wait — **refuse**, see Decision 1. No
  wait mode; dropped under YAGNI.
- [x] ✅ **Task 1.3**: GREEN — implemented in `scripts/qa/llm_qa.py` (the
  executing path only) and in the sibling shell runner, sharing ONE lock file so
  the two exclude each other (Decision 4). No stale-lock class exists by
  construction (Decision 2).
- [x] ✅ **Task 1.4**: The refusal names the live run's PID, points at
  `--read-only` for inspection, and states explicitly that a lock file on disk
  does NOT mean a lock is held — the sentence that stops someone deleting it.
  (Start time was dropped: the PID is what makes the holder checkable, and a
  second field invites the reader to reason about staleness, which is exactly
  the reasoning `flock` makes unnecessary.)

### Phase 2: decide on acceptance-test worktree isolation

- [ ] ⬜ **Task 2.1**: With Phase 1 landed, re-assess whether the shared
  `.git/worktrees/` mutation still warrants a change. Record the decision either
  way — including "leave it, Plan 00105's trade-off stands" — so the next person
  to notice does not re-derive this.

### Phase 3: verification

- [ ] ⬜ **Task 3.1**: Full QA, daemon restart RUNNING.
- [x] ✅ **Task 3.2**: Verify by actually racing two runs, not only by unit
  test — the failure mode is a real concurrent process, and a mocked lock proves
  nothing about it. Verified with live processes in FOUR directions rather than
  inferring any of them:
  - Python holder → shell runner refused (exit 3), holder PID named
  - Shell holder → `llm_qa.py` refused (exit 3), holder PID named
  - Lock held → `--read-only` still succeeded (exit 0)
  - Holder SIGKILLed → next run proceeded, despite the lock file still on disk

## Technical Decisions

### Decision 1: refuse, do not wait — and no opt-in wait flag

**Context**: Task 1.2. A second run can either be refused immediately or queued
behind the first.

**Decision**: refuse, with exit code 3. No wait mode.

**Rationale**: refusing is what Core Standard 06 (FAIL FAST) asks for — the
caller learns immediately and can act. Waiting would silently convert a QA
invocation into an unbounded stall, and this runner is invoked from hooks, from
CI steps and from release gates, none of which want a command that produces no
output for an arbitrary period. An opt-in `--wait` was considered and dropped
under YAGNI: nothing needs it today, and it is trivial to add if something does.

### Decision 2: `flock`, not a PID file

**Context**: the obvious implementation is a PID file plus a liveness check.

**Decision**: `fcntl.flock` (Python) and `flock(1)` (shell), on one shared file.

**Rationale**: the kernel drops a `flock` when the holder exits, **including on
SIGKILL**. That removes the entire stale-lock class rather than adding cleanup
logic for it — and a guard that could wedge the suite permanently would be worse
than the race it prevents, because an agent would quickly learn to delete the
lock file, which reintroduces the race AND destroys the signal. The refusal
message therefore says explicitly that a lock file on disk does not mean a lock
is held.

The PID is still recorded, but only as a diagnostic so the refusal can name the
live run. It never decides anything; `flock` does.

### Decision 3: exit code 3, skipping 2

**Context**: `run_all.sh` already exits 2 for "cannot run" (venv resolver
missing).

**Decision**: "busy" is 3 in **both** entry points, and 2 is left alone.

**Rationale**: the two scripts are alternative front doors to the same suite, so
the same number must not mean two different things depending on which one the
caller used. 0 pass / 1 failed / 2 cannot run / 3 busy reads as a ladder.

### Decision 4: one lock file shared by both entry points

**Context**: `run_all.sh` does not delegate to `llm_qa.py` — it invokes the
per-tool scripts directly.

**Decision**: both acquire the SAME path, `untracked/qa/.llm_qa.lock`.

**Rationale**: they must exclude EACH OTHER, not merely themselves. A human
running `run_all.sh` while an agent runs `llm_qa.py` is precisely the cross-path
race worth preventing, and separate locks would permit it while appearing
guarded. `flock(1)` and `fcntl.flock` share the underlying kernel lock, so this
works across the language boundary — verified with real processes in both
directions, not inferred from symmetry.

**Bug caught while implementing this**: `exec {FD}> file` in bash truncates at
OPEN time, which happens BEFORE `flock` is attempted. A contending run would
therefore erase the holder's PID stamp and then report `pid=unknown` in the very
message that needs it. Fixed by opening append (`>>`) and truncating only after
the lock is held.

### Decision 5: the known limitation, stated rather than discovered later

**Context**: `daemon/server.py` (Plan 00127) already documents that `flock` is a
no-op on some filesystems — older NFS without lockd, some 9p configs.

**The limitation**: where that holds, this guard silently provides no mutual
exclusion and two runs race exactly as they do today.

**Why it is accepted**: the failure mode is **no worse than the status quo** —
the guard cannot make anything worse, it just stops helping. And the supported
deployment is the same one the daemon already assumes: a normal-disk bind mount
where `flock` works, including across PID namespaces.

**Honest difference from the daemon's case**, worth stating rather than glossing:
`server.py` degrades *loudly* there (two racing winners both reach
`start_unix_server` and the loser exits 1). This guard degrades *silently*. That
is acceptable for a QA runner and would not be for the daemon, but it means "the
lock is in place" must not be read as "concurrent runs are impossible on every
filesystem".

**No reuse of the daemon's implementation**: it is inline async code inside the
package, specific to protecting the socket-bind critical section, not a public
utility — and the shell entry point could not call a Python helper regardless.
Extracting one would couple the QA tooling to the package it tests, for ~15
lines that also have to exist twice across a language boundary anyway.

## Success Criteria

- [ ] A second concurrent suite run cannot silently race a first
- [ ] `--read-only` inspection still works while a run is in flight
- [ ] A stale lock does not wedge the suite
- [ ] The Phase 2 decision is recorded, whichever way it goes
- [ ] QA green, daemon restart RUNNING

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. Blow-by-blow lives in JOURNAL/. -->

- Filed from a self-inflicted incident during Plan 00261, plus a dedupe sweep
  confirming no live plan covers either finding.
