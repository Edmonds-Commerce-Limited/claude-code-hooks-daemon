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

## Success Criteria

- [ ] Every entry above reaches a terminal state (fixed / not-a-defect /
  graduated) with its evidence recorded.
- [ ] Any fix made here is covered by a test that fails against today's code.
- [ ] Full QA passes and CI is green.
- [ ] The plan is archived into the holding area (`Completed/`) with the README
  row and statistics updated in the same commit.

## Delivery & Milestones

- Opened when N1 was found while investigating Plan 00398.
