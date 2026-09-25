# Plan 00449: unlocked eviction race survives in other handlers

**Status**: Complete
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

The Defence Before Fix sweep (the `unlocked-select-then-evict` semgrep rule,
cross-checked with a grep for bounded `len(self._x) >=` maps) counted **12
instances in 10 handlers**. That is the eight sites above, with
`model_fallback_detector` counting three, plus two the review missed:
`handlers/user_prompt_submit/git_context_injector.py:76` (a `min()` scan) and
`handlers/user_prompt_submit/standing_authorisations.py:377`. There were none
in `scripts/`. The two journalled sites also exposed a neighbouring defect:
`SideEffectJournal` shared one undo list across concurrent requests.

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

**Decided (unattended, 2026-09-24)**: fix every instance in this release
rather than treat it as a follow-up. A known defect is a known defect, whatever
its severity. Assumption: the owner's 'no known defects' instruction; the owner
can reverse this with one message.

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

- [x] ✅ **Task 1.1**: RED — a concurrency test driving `write_clobber_guard`'s
  map from several threads at once against a map already at its cap, asserting
  no exception escapes. Drive CPython's switch interval to its floor; Plan
  00437 found the window is not observable otherwise.
  `tests/unit/handlers/pre_tool_use/test_write_clobber_guard_concurrency.py`
  failed with `KeyError` and `RuntimeError` escaping `handle()` for a Read.

- [x] ✅ **Task 1.2**: GREEN — make its eviction atomic, and confirm the
  fail-closed claim holds under contention. The map is a `BoundedFifoMap`
  (`handlers/utils/bounded_fifo_map.py`). A second test shows the guard still
  DENIES a clobber after the contention.

### Phase 2: the remaining sites

- [x] ✅ **Task 2.1**: Migrate each remaining site to the shared counter where
  the semantics match; where they do not, use one locked bounded-FIFO map
  rather than a second hand-rolled copy per site. No remaining site is a
  per-session rate limit, so none fits `SessionAdviceCounter`. All eleven
  remaining instances use `BoundedFifoMap`. The journalled sites use its
  journal-aware `put`/`insert_if_absent`, which keeps a denied call's rollback
  exact. `SideEffectJournal` now keeps its undo records per thread (RED:
  `tests/unit/core/test_side_effect_journal.py::TestConcurrentCalls`).

- [x] ✅ **Task 2.2**: Pin FIFO order with a test at each site. The v3.66.0
  review found `popitem()` had silently inverted FIFO to LIFO in the extracted
  counter precisely because the bounding test asserted only the map's SIZE —
  LIFO satisfies a size assertion exactly as well as FIFO does.
  `tests/unit/handlers/test_eviction_sites.py` names the evicted entry at every
  site. `git_context_injector` pins "least recently injected", the policy its
  `min()` scan had.

### Phase 3: stop it recurring

- [x] ✅ **Task 3.1**: Decide whether this shape is worth a QA check, and
  record the decision either way. A rule matching `del m[next(iter(m))]` and
  `m.pop(next(iter(m)))` is cheap; the judgement is whether its false
  positives on genuinely single-threaded maps pay for it.

  **Decided (unattended, 2026-09-24)**: build it, and make it block. The rule
  is `scripts/qa/semgrep/unlocked-eviction.yaml` (id
  `unlocked-select-then-evict`), and the existing `semgrep` gate picks it up.
  It matches the inline and two-statement spellings, including a `min`/`max`
  victim, and stands down inside a `with <lock>:` block. Over `src/` and
  `scripts/` it reported the 12 real instances and no false positives, so a
  single-threaded map is a cost nobody has paid yet. If one appears, the fix
  is one constructor call. `tests/unit/qa/test_semgrep_unlocked_eviction.py`
  pins planted hits and clean spellings. Assumption: the owner's 'no known
  defects' instruction; the owner can reverse this with one message.

## Success Criteria

- [x] The RED concurrency test observed failing before the change and passing
  after, for `write_clobber_guard` at minimum.
- [x] No surviving unlocked select-then-delete on a handler-singleton map,
  except any recorded as exempt with a stated reason. None is exempt; the
  semgrep gate reports 0.
- [x] A test pins FIFO eviction order at each migrated site.
- [x] `llm_qa.py all` passes — read the `QA: N/35 PASSED` line and the
  per-gate markers, not the wrapper exit code, which has returned 0 over
  failing gates in this project before. CI green on main's HEAD `34c588dc`
  (run 36066507383), which includes this plan's delivered code.
- [x] Release-bound consequence recorded in the holding area, or an explicit
  statement that there is none:
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/23-concurrent-requests-no-longer-crash-handler-bookkeeping.md`.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00449-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- `5e3e784f` — Defence: the `unlocked-select-then-evict` semgrep rule and its
  fixture proof. The gate was red on 12 instances.
- `9c378f00` — Phase 1: `BoundedFifoMap`; `write_clobber_guard` RED→GREEN.
- `82adb915` — Phase 2: the other 11 instances, and the per-thread
  `SideEffectJournal`. The semgrep gate reports 0.
