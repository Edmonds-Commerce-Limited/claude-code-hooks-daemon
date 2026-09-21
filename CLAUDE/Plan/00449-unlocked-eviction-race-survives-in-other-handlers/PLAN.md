# Plan 00449: unlocked eviction race survives in other handlers

**Status**: Not Started
**Created**: 2026-09-21
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Plan 00437 named a defect class and fixed two instances of it. The v3.66.0
release review found at least six more, untouched.

The class, in `session_advice_counter.py`'s own words: handlers are
daemon-lifetime singletons, dispatch runs through
`loop.run_in_executor(None, ...)` whose default executor IS a
`ThreadPoolExecutor`, so an unlocked select-then-delete on a shared map is a
two-step race. Two threads reaching a full map can select the same key and the
second delete raises `KeyError`; `next(iter(...))` can raise `RuntimeError` if
the dict changes size mid-iteration. That argument is general — it applies
wherever the same two steps appear, and `dict.pop(k)` with no default raises
`KeyError` exactly as `del` does:

- `handlers/post_tool_use/goal_injection.py:763`
- `handlers/pre_tool_use/flaggable_work_advisor.py:234`
- `handlers/session_start/model_fallback_detector.py:372`
- `handlers/pre_tool_use/write_clobber_guard.py:125`
- `handlers/pre_tool_use/reference_repo_freshness.py:462`
- `handlers/user_prompt_submit/idle_housekeeping_advisor.py:178`
- `handlers/post_tool_use/command_hints.py:402` and
  `handlers/post_tool_use/recovery_cron_advisor.py:274`, which select a victim
  key and then act on it across several statements

**`write_clobber_guard` is the one that matters most.** It is a safety-band
handler at priority 16 whose own comment states it "fails CLOSED". An exception
escaping `_record` is not a fail-closed outcome — it is the guard disappearing
on a request that had nothing to do with clobbering.

**This is not a regression, and v3.66.0 did not make it worse.** The release
notes' claim — that the counter work "replaced two unlocked copies" — is
accurate as written. The extraction fixed two of eight-plus instances and left
the rest, which is why this is a follow-up rather than a release blocker. It is
filed because the class is now NAMED, and a named class with known surviving
instances is a different thing from one nobody has articulated: the next reader
of `session_advice_counter.py` meets a docstring making a general argument
beside code that applied it twice.

## Goals

- Every surviving instance either uses the shared counter, or a small locked
  bounded-FIFO map where the semantics differ, or is recorded as deliberately
  exempt with the reason stated.
- `write_clobber_guard` genuinely fails closed, including when its own
  bookkeeping is contended.
- Eviction order is FIFO everywhere and is pinned by a test, not left for a
  reader to infer from the method chosen.

## Non-Goals

- **No new abstraction beyond what the sites need.** Several keys are tuples
  and one value is a set, so `SessionAdviceCounter` does not fit all of them;
  the answer is a second small primitive or a local lock, not a framework.
- **No audit of every mutable handler attribute.** This plan covers the
  select-then-delete eviction shape the review enumerated, not all shared
  state.

## Tasks

### Phase 1: the safety-band handler

- [ ] ⬜ **Task 1.1**: RED — a concurrency test driving `write_clobber_guard`'s
  map from several threads at once against a map already at its cap, asserting
  no exception escapes. Drive CPython's switch interval to its floor; Plan
  00437 found the window is not observable otherwise.

- [ ] ⬜ **Task 1.2**: GREEN — make its eviction atomic, and confirm the
  fail-closed claim holds under contention.

### Phase 2: the remaining sites

- [ ] ⬜ **Task 2.1**: Migrate each remaining site to the shared counter where
  the semantics match; where they do not, use one locked bounded-FIFO map
  rather than a second hand-rolled copy per site.

- [ ] ⬜ **Task 2.2**: Pin FIFO order with a test at each site. The v3.66.0
  review found `popitem()` had silently inverted FIFO to LIFO in the extracted
  counter precisely because the bounding test asserted only the map's SIZE —
  LIFO satisfies a size assertion exactly as well as FIFO does.

### Phase 3: stop it recurring

- [ ] ⬜ **Task 3.1**: Decide whether this shape is worth a QA check, and
  record the decision either way. A rule matching `del m[next(iter(m))]` and
  `m.pop(next(iter(m)))` is cheap; the judgement is whether its false
  positives on genuinely single-threaded maps pay for it.

## Success Criteria

- [ ] The RED concurrency test observed failing before the change and passing
  after, for `write_clobber_guard` at minimum.
- [ ] No surviving unlocked select-then-delete on a handler-singleton map,
  except any recorded as exempt with a stated reason.
- [ ] A test pins FIFO eviction order at each migrated site.
- [ ] `llm_qa.py all` passes — read the `QA: N/35 PASSED` line and the
  per-gate markers, not the wrapper exit code, which has returned 0 over
  failing gates in this project before.
- [ ] Release-bound consequence recorded in the holding area, or an explicit
  statement that there is none.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00449-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
