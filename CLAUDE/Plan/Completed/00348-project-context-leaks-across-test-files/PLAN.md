# Plan 00348: project context leaks across test files

**Status**: Complete
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

- [x] ✅ **Task 1.1**: `tests/integration/test_project_context_isolation.py`
  runs the pair in a SUBPROCESS, so it tests the ordering it names rather than
  reporting on whatever order `pytest-randomly` happened to pick.

- [x] ✅ **Task 1.2**: **Measured, not inferred.** Reading
  `ProjectContext.__dict__["daemon_untracked_dir"]` after the offending test
  showed a `classmethod` wrapping the *fixture's* lambda — so it is the
  FIXTURE's patch that survives, which rules the classmethod-descriptor theory
  out and confirms restore order:

  > A test-level `monkeypatch` patches an attribute the class's autouse fixture
  > has already patched. The fixture's context exits FIRST and restores the
  > original; the test-level undo then runs and faithfully restores what IT
  > recorded as the previous value — the fixture's lambda — which stays on the
  > class for the rest of the process.

  This also explains why only one test in that file leaked: the others patch
  `write_goal_signal`, a different attribute, so their unwind cannot collide.

### Phase 2: Fix it where it cannot recur

- [x] ✅ **Task 2.1**: Four tests converted from the function-scoped
  `monkeypatch` to a local `pytest.MonkeyPatch.context()` around just the call
  under test, which keeps the unwind properly nested. **The sweep found three
  more leakers than the diagnosis predicted** — `test_compaction_signal.py`,
  `test_context_sidecar.py` and `test_goal_ledger_stop_defence.py`, all the
  identical shape: patch `ProjectContext.daemon_untracked_dir` to raise, to
  prove a handler fails open. That is a recurring idiom, not three accidents.
- [x] ✅ **Task 2.2**: Decided **against** a backstop in `tests/conftest.py`.
  With every known leaker fixed and a check in place, a repo-wide restore would
  only ever mask the next one — and this defect's whole cost was that it was
  masked. Revisit if a leak recurs that the check cannot attribute.

### Phase 3: Stop the class coming back

- [x] ✅ **Task 3.1**: The parametrised regression test covers all four files,
  each as its own subprocess pair. A per-module fingerprint over the whole
  suite was **rejected on cost**: it would run for all 18,627 tests to catch a
  defect with four known instances, and the pair-check gives the same signal
  where the risk actually is.

## Success Criteria

- [x] The two-file reproduction passes.
- [x] Every `tests/unit/handlers/**` directory followed by
  `tests/unit/core/test_project_context.py` passes — and the sweep was widened
  to every `tests/unit/*` directory and `tests/integration` as well, since a
  process-wide singleton is not leaked only by handler tests. That caution paid
  for itself: three of the four leakers were outside the directory the original
  bisect landed in.
- [x] Full QA green — 26/26, 18627 tests, 95.2% coverage.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00348-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Found during Plan 00347's regression testing, and confirmed pre-existing on a
  clean worktree at `85a07f14` before any of that plan's changes.
- **The bisect's first answer was incomplete, and the plan was written
  expecting that.** One file reproduced the failure, and the success criterion
  deliberately demanded a sweep anyway. Three more leakers turned up — so the
  four-line fix this could have been would have left three quarters of the
  defect in place, still invisible, still ready to accuse the wrong file.
