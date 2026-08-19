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

- [ ] ⬜ **Task 1.1**: RED — a test that starts a run while a lock is held and
  asserts the second does not proceed to execute tools. Must also assert that
  `--read-only` is unaffected.
- [ ] ⬜ **Task 1.2**: Decide refuse-vs-wait and record it in Technical
  Decisions. Refusing is FAIL FAST and gives the agent an immediate, actionable
  message; waiting is friendlier for a human at a terminal but can hang a hook
  or a CI step with no output. Consider refuse-by-default with an opt-in wait.
- [ ] ⬜ **Task 1.3**: GREEN — implement in `scripts/qa/llm_qa.py` around the
  executing loop, and in `run_all.sh` so the human-facing path is covered too.
  A stale lock (holder no longer alive) must not wedge the suite forever.
- [ ] ⬜ **Task 1.4**: The message must name the live run's PID and start time,
  and say what to do. A lock whose message is only "already running" invites an
  agent to delete the lock file.

### Phase 2: decide on acceptance-test worktree isolation

- [ ] ⬜ **Task 2.1**: With Phase 1 landed, re-assess whether the shared
  `.git/worktrees/` mutation still warrants a change. Record the decision either
  way — including "leave it, Plan 00105's trade-off stands" — so the next person
  to notice does not re-derive this.

### Phase 3: verification

- [ ] ⬜ **Task 3.1**: Full QA, daemon restart RUNNING.
- [ ] ⬜ **Task 3.2**: Verify by actually racing two runs, not only by unit
  test — the failure mode is a real concurrent process, and a mocked lock proves
  nothing about it.

## Technical Decisions

<!-- Task 1.2's refuse-vs-wait decision is recorded here when made. -->

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
