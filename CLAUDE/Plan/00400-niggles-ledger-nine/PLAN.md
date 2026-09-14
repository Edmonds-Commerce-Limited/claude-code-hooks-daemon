# Plan 00400: niggles ledger nine

**Status**: In Progress
**Created**: 2026-09-14
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

The open niggles ledger. Small defects get recorded here the turn they are
found, so that noticing something and doing something about it are never the
same decision. Ledger eight ([Plan 00397](../Completed/00397-niggles-ledger-eight/PLAN.md))
is complete, so this one opens.

An entry is either fixed in place, ruled NOT A DEFECT with the evidence that
settles it, or graduated to its own plan when the fix turns out to be a ruling
rather than an edit.

## Goals

- Every niggle found is written down with the evidence that makes it checkable
  by someone who was not there.
- Each entry reaches a terminal state: fixed, ruled not-a-defect, or graduated.

## Non-Goals

- Fixing anything that needs an owner ruling — that graduates to its own plan.

## Tasks

### Phase 1: Entries

- [ ] ⬜ **N1**: The QA suite writes into the LIVE supervisor runtime directory.

  **Found**: while reading `untracked/supervise/decision.log` as forensic
  evidence for [Plan 00398](../00398-critical-compaction-blocked-by-the-idle-gate/PLAN.md).

  **Evidence.** Test-authored lines interleave with live supervisor decisions in
  the live log:

  ```text
  2026-09-14T09:44:47 supervisor active (dry-run (injects marker)); polling /workspace/untracked/context-sidecar every 2.0s; wrapping: ['echo', 'SUPERVISED_OK']
  2026-09-14T09:48:10 noop: session busy (composing) [red]
  2026-09-14T09:51:41 would-compact: red at 43% + idle -> would inject /compact
  ```

  `wrapping: ['echo', 'SUPERVISED_OK']` is a test fixture, not this session.
  Separately, the live sidecar directory holds a test-authored sidecar:

  ```json
  {"session_id": "socket-stdin-test", "window_size": 0, "pct": 0.0, "writer_pid": 345, "seq": 45277}
  ```

  It shares `writer_pid` and the `seq` counter with this session's real sidecar
  (`seq: 45318`), so the **daemon** minted it: a test opened the daemon socket
  with `session_id: "socket-stdin-test"` and the daemon wrote a sidecar for it
  into the live directory.

  **Impact is diagnostic, NOT behavioural — established, not assumed.** The
  decision path is protected by Plan 00166's own-session filter: `_scan_sidecars`
  skips any sidecar whose `session_id` is not in the learned set, the set is
  built by scanning `/proc` environs for `CLAUDE_CODE_SESSION_ID`, and it fails
  safe (empty set ⇒ act on nothing). `socket-stdin-test` can never be learned
  because no process in this container carries that id. Both live call sites
  (`claude-supervise.py:6021`, `:6708`) do pass `own_sessions=cached_own_session_ids()`
  — checked at the call sites, not inferred from the comment.

  So the cost is that the live `decision.log` is the primary forensic record for
  supervisor behaviour, and it is contaminated by test output. This session
  measured tick populations from that file; those particular counts survive
  because the test lines have a distinct shape, but that is luck rather than
  isolation.

  **Not yet ruled**: whether the fix belongs in the tests (point them at a tmp
  runtime dir) or in the daemon (refuse to mint a sidecar for a session id with
  `window_size: 0`). Needs a look at how the fixtures resolve the untracked dir
  before proposing either.

- [x] ✅ **N2**: FIXED — a test whose result depended on the time of day, red on
  `main` and not noticed.

  **Found**: checking CI after pushing Plan 00398, which surfaced that the
  PREVIOUS commit on `main` (`c1f2ee82`) had already failed CI — across all
  three Python versions — and nobody had looked.

  **The failure**: `test_plan_qa_edit.py::TestHandleJournal::test_pure_append_is_silent`
  asserts a pure journal append produces no advisory. It appends an entry
  stamped `## 10:00` to a day-file named for TODAY, and leaves the clock free:

  ```text
  E  assert not ["Plan QA drift report:\n- [advise] journal-entry-future-dated ..."]
  ```

  CI ran at **09:24 UTC**, so `10:00` had not arrived yet and
  `journal-entry-future-dated` fired — correctly. My own full QA run passed the
  same test because it ran nearer 10:00. **The handler is right; the test was
  wrong**, and it fails any run starting more than 30 minutes (the check's
  tolerance) before 10:00 — roughly the first 40% of each day.

  **Why it survived**: the `_journal_file` helper already dodged one time-bomb
  by generating TODAY's date rather than hardcoding one, and its comment says
  so. Fixing the date dependence while leaving the TIME fixed swapped a bomb
  that fires once for one that fires daily, on a schedule nobody was watching.

  **Fix**: `journal_entry_future_dated._now` exists precisely so tests can pin
  it ("isolated so tests can pin it") and no test did. An autouse fixture on
  `TestHandleJournal` pins it to 23:59 today — late enough that every fixed
  entry time is in the past, while keeping the day-file name valid for
  `journal-dayfile-naming`, which accepts only today/yesterday. Added
  `test_future_dated_entry_advises_regardless_of_run_time`, which pins 09:24
  deliberately and asserts the finding DOES fire, so the behaviour CI caught by
  accident is now asserted on purpose.

- [ ] ⬜ **N3**: `cancel-in-progress: false` does NOT give every sha on `main` a
  CI result, and `qa.yml` asserts that it does.

  **Found**: checking CI before archiving Plan 00398, whose implementation
  commit turned out to have no CI evidence at all.

  **The claim, in `.github/workflows/qa.yml`**:

  ```yaml
  cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}
  # ... With this false, a later push QUEUES behind the
  # running job rather than killing it, so every sha on main gets a result.
  ```

  **The counter-example, observed live**:

  ```text
  09:56:49  e495227b  starts RUNNING
  10:00:53  ec18062d  created -> PENDING
  10:05:13  8867803e  created -> ec18062d CANCELLED, jobs: 0
  ```

  `gh run view 34830966652` reports `conclusion: cancelled`, `jobs: 0` — it
  never started.

  **Mechanism**: `cancel-in-progress: false` protects the run that is ALREADY
  RUNNING. GitHub permits only ONE pending run per concurrency group, so a newer
  arrival evicts the older pending one. A sha pushed while another run is in
  progress, and superseded before it starts, gets no result whatsoever. The
  guarantee holds for two concurrent pushes and fails from the third onward —
  which is why it reads as correct and survived review.

  **Why it matters, not merely tidy**: Plan 00359's release-slate gate requires
  HEAD's EXACT sha to be CI-green, and plan completion criteria cite specific
  commits. `ec18062d` is Plan 00398's implementation commit; citing it as
  delivery evidence would cite a run that does not exist.

  **Not ruled — the fix trades runner cost against evidence**:

  1. **Per-sha concurrency group on the default branch**
     (`group: qa-${{ github.ref }}-${{ github.sha }}`). Every sha gets its own
     group, so nothing queues and nothing is evicted. Guarantees the property
     the comment claims, at the cost of running CI for every sha in a rapid
     series.
  2. **Accept, and correct the comment.** A later green run covers the earlier
     content, so `main` is still verified — just not per-sha. Cheapest, but the
     release-slate gate and plan criteria keep wanting a specific sha.
  3. **Keep the behaviour, make the gap visible** — have the release-slate check
     report "this sha has no run" distinctly from "this sha failed", so the
     absence is never read as a pass.

  Whichever is chosen, the comment must stop asserting a guarantee the config
  does not provide.

## Success Criteria

- [ ] Every entry above reaches a terminal state (fixed / not-a-defect /
  graduated) with its evidence recorded.
- [ ] Any fix made here is covered by a test that fails against today's code.
- [ ] Full QA passes and CI is green.
- [ ] The plan is archived into the holding area (`Completed/`) with the README
  row and statistics updated in the same commit.

## Delivery & Milestones

- Opened when N1 was found while investigating Plan 00398.
