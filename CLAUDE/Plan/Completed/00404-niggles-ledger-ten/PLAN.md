# Plan 00404: niggles ledger ten

**Status**: Complete
**Created**: 2026-09-14
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

The open niggles ledger. Small defects get recorded here the turn they are
found, so that noticing something and doing something about it are never the
same decision. Ledger nine
([Plan 00400](../Completed/00400-niggles-ledger-nine/PLAN.md)) is complete, so
this one opens.

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

- [x] ✅ **N1**: One failed `chmod` costs every per-event socket, not one.

  **Found**: checking CI for
  [Plan 00403](../00403-upstream-issue-reporting-sop/PLAN.md)'s Task 1.1 commit
  `acc3eb93`. The run failed on Python 3.11 and passed on 3.12 and 3.13 — the
  asymmetry is what made it worth reading rather than re-running.

  **Evidence.** `_bind_event_sockets` binds each socket inside a per-socket
  guard, then secures it one line outside that guard:

  ```python
  except OSError as e:
      logger.error("Failed to bind per-event socket %s (%s): %s", ...)
      continue
  event_socket_path.chmod(0o660)      # <- not guarded
  ```

  A failure in step 1 of a two-step operation skips one event. The same kind of
  failure in step 2 — same path, one line later — propagates out of
  `_bind_event_sockets`, out of `start()`, and aborts daemon startup. CI caught
  it as:

  ```text
  src/claude_code_hooks_daemon/daemon/server.py:937: in _bind_event_sockets
      event_socket_path.chmod(0o660)
  E  FileNotFoundError: [Errno 2] No such file or directory:
     '/tmp/tmp8q5v1v2l/events-runnervmlun5p/subagent-start.sock'
  ```

  The window is not theoretical: this same method begins by `shutil.rmtree`-ing
  the events dir, so a second daemon starting concurrently for the same project
  deletes the socket between the bind and the chmod.

  **The contract it violates is already written down.** A sibling test states
  the rule — "binding still proceeds best-effort, matching every other
  per-socket failure in this method"
  (`test_bind_time_rmtree_failure_is_logged_not_swallowed`). The chmod was the
  one per-socket failure in the method that did not.

  **Cost, measured rather than assumed.** The reproduction failed
  `0 == 31 - 1`: one unsecurable socket took down **all 31**, silently dropping
  the daemon to the legacy socket for the rest of the session.

  **Fixed** — the chmod moved inside the same guard. A socket whose chmod did
  not land is skipped rather than served, because without it the socket carries
  umask-derived permissions instead of the intended `0o660`, and the legacy
  socket already covers every event. `_discard_unsecured_socket` closes the
  server and unlinks the path, since `asyncio` leaves a Unix socket file on
  disk when its server closes — otherwise the failure would leave behind the
  shape most likely to be mistaken for a working socket.

  **Pinned by**
  `test_a_chmod_failure_skips_one_socket_rather_than_aborting_startup`, which
  fails against the old code with `0 == 31 - 1` and asserts the unsecured file
  is gone.

## Success Criteria

- [x] ✅ Every entry reaches a terminal state: N1 fixed in place.
- [x] ✅ Each fixed entry is pinned by a test that fails against the old code —
  `test_a_chmod_failure_skips_one_socket_rather_than_aborting_startup` fails
  the unfixed code with `0 == 31 - 1`.
- [x] ✅ Every release-bound consequence is in the pending-release holding area:
  `UNRELEASED/release-notes/42-one-unsecurable-socket-no-longer-costs-them-all.md`.
  No config-change (the fix adds no options) and no truth-change (no documented
  behaviour became false — the documented contract was already "best-effort per
  socket", which is what the `chmod` was violating).
- [x] ✅ Full QA passes and CI is green — 30/30 checks locally, and CI green on
  Python 3.11, 3.12 and 3.13. 3.11 is the one that matters: it is the version
  whose timing exposed the race in the first place.

## Delivery & Milestones

- Opened because ledger nine is complete and a defect needed recording the same
  turn it was found. N1 came from reading a CI failure that passed on two of
  three Python versions rather than re-running it.
