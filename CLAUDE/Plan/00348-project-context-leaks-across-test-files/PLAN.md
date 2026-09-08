# Plan 00348: project context leaks across test files

**Status**: Not Started
**Created**: 2026-09-08
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single Agent

## Overview

`tests/unit/handlers/post_tool_use/test_goal_injection.py` leaves a patched
`ProjectContext.daemon_untracked_dir` behind. Whatever runs next sees that
file's `tmp_path` instead of its own, and two tests in
`tests/unit/core/test_project_context.py` fail with a directory belonging to a
test in a different file:

```
E  AssertionError: assert PosixPath('.../test_ledger_failure_never_bloc0/untracked')
                       == PosixPath('.../test_initialize_with_valid_con0/project/.claude/hooks-daemon/untracked')
```

Reproducing it takes two files and nothing else:

```bash
pytest tests/unit/handlers/post_tool_use/test_goal_injection.py \
       tests/unit/core/test_project_context.py
# 2 failed, 84 passed
```

Either file alone passes. The full suite passes too — 18619 tests, 0 failed —
which is why nothing has ever reported this.

## Why it matters more than two tests

**The failure accuses the wrong code.** It surfaces inside
`test_project_context.py`, a file that is correct and unchanged. This defect
was found while regression-testing Plan 00347, and the first hypothesis was
that Plan 00347 had broken something; it took a clean worktree at an earlier
commit to establish otherwise. Every future agent who trips this pays that
same cost, and one of them will "fix" the innocent file.

**It is silent, not flaky.** `pytest-randomly` shuffles the order, so the
combination is hit sometimes and not others — and the full-suite run currently
does not hit it at all. A green suite is therefore not evidence that this is
absent, which is the same shape as Plan 00347's root-vs-runner blind spot.

**Any test can be the victim.** The leaked state is on a process-wide
singleton, so the blast radius is not `test_project_context.py` — it is every
test that reads `ProjectContext` after `test_goal_injection.py` has run.

## Goals

- The two-file reproduction above passes.
- A test that patches `ProjectContext` cannot leave the patch behind, enforced
  by something other than reviewer attention.

## Non-Goals

- Removing `pytest-randomly`. Random ordering is what makes leaks findable at
  all; the leak is the defect, not the shuffling that exposes it.
- Reworking `ProjectContext`'s singleton design. Production initialises it once
  per process and never patches it, so there is no production defect here —
  widening this into a redesign would be scope creep with real risk.

## Tasks

### Phase 1: Reproduce, then find the actual mechanism

- [ ] ⬜ **Task 1.1**: A test that FAILS on the leak — the two-file order run
  as a subprocess, so it does not depend on the ambient run's ordering.
- [ ] ⬜ **Task 1.2**: Establish why the patch survives. `test_goal_injection`
  uses both `pytest.MonkeyPatch.context()` inside an autouse fixture and the
  function-scoped `monkeypatch` fixture, sometimes against the same attribute.
  Restore ORDER is the leading suspect — an outer context restoring the
  original before an inner one restores what it captured (the outer's patched
  value) leaves the patched value installed permanently. **Confirm it rather
  than assuming it**; the fix differs per mechanism, and a second candidate is
  that patching a `classmethod` via `getattr` restores a bound method rather
  than the descriptor.

### Phase 2: Fix it where it cannot recur

- [ ] ⬜ **Task 2.1**: Fix the leak identified in Task 1.2.
- [ ] ⬜ **Task 2.2**: Decide whether the repo-wide `reset_project_context`
  autouse fixture in `tests/conftest.py` should also restore the class's
  patchable attributes, not just `ProjectContext.reset()`. It already runs for
  every test, so it is the natural place for a backstop — but a backstop that
  hides a leaking fixture is worse than none, so it must be loud if it fires.

### Phase 3: Stop the class coming back

- [ ] ⬜ **Task 3.1**: Consider a check that a test module patching
  `ProjectContext` cannot leave the class mutated, along the lines of the
  session-scoped fingerprint idea: snapshot the patchable attributes before and
  after each module and fail the module that changed one. Weigh the runtime
  cost against a suite of 18,619 tests before committing to it.

## Success Criteria

- [ ] The two-file reproduction passes.
- [ ] Running every `tests/unit/handlers/**` file followed by
  `tests/unit/core/test_project_context.py` passes for all of them, not just
  the one file found here — the bisect found `test_goal_injection.py` first,
  which is not proof it is the only one.
- [ ] Full QA stays green, and the suite's runtime is not materially worse.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00348-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Found during Plan 00347's regression testing, and confirmed pre-existing on a
  clean worktree at `85a07f14` before any of that plan's changes.
