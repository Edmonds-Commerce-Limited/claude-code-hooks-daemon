# Plan 00437: session advice counter is shared and locked

**Status**: Not Started
**Created**: 2026-09-18
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single Agent

## Overview

From ledger [00422](../00422-niggles-ledger-fifteen/NIGGLES.md) N5 row (c), one
of the three rows the v3.65.0 reviewers flagged as having teeth.

`teammate_reap_advisor._should_advise` and
`background_process_tracker._should_advise` are the same eight lines, with the
same two constants beside them: a per-session counter that rate-limits an
advisory to the first qualifying event and every Nth after it, with an eviction
that drops an arbitrary entry once the map reaches its cap.

The eviction is not atomic:

```python
if len(self._session_counts) >= _MAX_TRACKED_SESSIONS:
    del self._session_counts[next(iter(self._session_counts))]
```

Two threads reaching a full map can select the same key, and the second `del`
raises `KeyError`; `next(iter(...))` can also raise `RuntimeError` if the dict
changes size mid-iteration.

**The concurrency is real, not theoretical, and that was worth checking rather
than assuming.** The daemon is asyncio and has no thread pool of its own — but
`server.py:1443` dispatches through `await loop.run_in_executor(None, self.controller.dispatch, hook_input)`, and the default executor IS a
`ThreadPoolExecutor`. Handlers are daemon-lifetime singletons, so two
concurrent requests share one counter map across two worker threads.

Both halves of the row are therefore one fix: the duplication is why there are
two unlocked copies, and a single shared, locked helper removes both at once.

## Goals

- One implementation of the per-session advice counter, used by both handlers.
- Its mutation is atomic, so no concurrent pair of callers can raise.
- The rate-limit behaviour both handlers have today is unchanged: advise on the
  first qualifying event for a session, then every Nth.
- The eviction still bounds the map on a daemon-lifetime singleton.

## Non-Goals

- **Changing either handler's interval or what it advises.** This is the
  counter's mechanics, nothing about the advice.
- **Making handler state thread-safe generally.** Other handlers hold mutable
  state; this plan fixes the one the review named and leaves a pointer, rather
  than auditing every handler under the same heading.

## Tasks

### Phase 1: the shared counter

- [ ] ⬜ **Task 1.1**: RED — a test driving the counter from several threads at
  once against a map already at its cap, asserting no exception escapes and the
  map stays bounded. It must fail against the current unlocked code.

- [ ] ⬜ **Task 1.2**: GREEN — one `SessionAdviceCounter` with a lock around the
  read-modify-write, in a shared module both handlers import.

- [ ] ⬜ **Task 1.3**: Both handlers use it, and their existing rate-limit tests
  pass unchanged — that is the behaviour-preservation check.

## Success Criteria

- [ ] ⬜ The concurrency test observed RED before the change and GREEN after.
- [ ] ⬜ Neither handler carries its own copy of the counter or its constants.
- [ ] ⬜ `llm_qa.py all` passes.
- [ ] ⬜ N5 row (c) is marked done in ledger 00422, recording that the thread
  pool was verified rather than assumed.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00437-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
