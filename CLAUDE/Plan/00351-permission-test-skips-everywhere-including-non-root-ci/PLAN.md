# Plan 00351: permission test skips everywhere including non root ci

**Status**: Not Started
**Created**: 2026-09-08
**Owner**: joseph
**Priority**: Low
**Recommended Executor**: Haiku
**Execution Strategy**: Single Agent

## Overview

`tests/claude_code_hooks_daemon/install/test_skills.py:140` guards
`test_deploy_skills_raises_if_target_not_writable` with:

```python
@pytest.mark.skipif(
    Path("/").stat().st_uid == 0, reason="Running as root - permission test not applicable"
)
```

The intent is "skip when running as root", because root ignores the directory
mode the test relies on. What it actually asks is **who owns `/`** — and on
every normal Linux system that is uid 0, whoever is running. So the condition is
a constant `True` and the test **never runs anywhere**.

That is not an inference from reading it. CI run 34192920901 reports
`SKIPPED [1] tests/claude_code_hooks_daemon/install/test_skills.py:140: Running as root - permission test not applicable`.
GitHub Actions runs as the unprivileged `runner` user, so the stated reason is
false there and the test should have executed. It skipped regardless.

The correct predicate is `os.geteuid() == 0`, which two other places already
use — `test_bootstrap_decision.py:198`, and `test_settings_deploy_lib.py:142`
added by Plan 00176 Task 2.0, which is how this was noticed. A single-site
slip, not a pattern.

Same class as Plan 00250 (wired in, correct-looking, never load-bearing), but
one line rather than a workflow, and blocking nothing — so it is filed rather
than fixed in passing.

## Goals

- The permission test executes on a non-root machine, and is skipped only when
  the process genuinely is root.
- Whatever it then reports is dealt with — a test that has never run once is as
  likely to be stale as correct.
- No other test guards on a constant.

## Non-Goals

- Making the test pass under root. Root bypasses the file mode, so there is
  nothing to assert there; skipping is right, the condition was not.

## Tasks

### Phase 1: Fix and see what it says

- [ ] ⬜ **Task 1.1**: Replace the predicate with `os.geteuid() == 0`. **Cannot
  be verified in this container**, which runs as root — the test is only
  observable executing on a non-root machine, so CI is the verification, not a
  local run. Land it alone so a failure is unambiguous about its cause.
- [ ] ⬜ **Task 1.2**: Read what CI then reports. Treat a failure as the
  expected outcome rather than a surprise: the assertion has never been
  exercised, and `deploy_skills` has changed since it was written.

### Phase 2: Guard the class

- [ ] ⬜ **Task 2.1**: A `skipif` whose reason states something false is worse
  than one with no reason, because it answers the question that would otherwise
  be asked. Assert the root-case reason matches the condition that fires it.
- [ ] ⬜ **Task 2.2**: Sweep `tests/` for `skipif` predicates that evaluate to a
  constant at import time; report rather than auto-fix.

## Success Criteria

- [ ] The permission test runs on CI (all three interpreters) rather than
  skipping
- [ ] Local `llm_qa.py all` still passes

## Dependencies

- Found while writing Plan 00176 Task 2.0's own root guard.
- Same class as Plan 00250, which is where the habit of reading CI's skip list
  came from.

## Risks & Mitigations

- **The test may fail once it runs.** That is the point, and why Task 1.2
  expects it. It may encode an assertion `deploy_skills` has outgrown.
- **Cannot be verified locally.** This container is root, so the fix is only
  observable on CI.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00351-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed from the CI skip list of run 34192920901, cross-checked against the two
  correct usages already in the repo.
