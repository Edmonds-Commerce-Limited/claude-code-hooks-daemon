# Plan 00351: permission test skips everywhere including non root ci

**Status**: In Progress
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

- [x] ✅ **Task 1.1**: Predicate replaced with `os.geteuid() == 0`, landed alone
  on an otherwise clean tree so a CI failure is unambiguous about its cause.
  Locally it still skips — this container is root — which is correct behaviour
  and also why the change is **not verified here**. CI is the verification.
- [ ] ⬜ **Task 1.2**: Read what CI then reports. Treat a failure as the
  expected outcome rather than a surprise: the assertion has never been
  exercised, and `deploy_skills` has changed since it was written.

### Phase 2: Guard the class

- [ ] ⬜ **Task 2.1**: A `skipif` whose reason states something false is worse
  than one with no reason, because it answers the question that would otherwise
  be asked. Assert the root-case reason matches the condition that fires it.

  `test_skipif_reasons_match_their_conditions.py` parses each test module and
  pairs every `skipif` reason that blames *the process being root* with the
  condition that actually fires it, requiring the condition to read the
  process's own euid. Both the original predicate and its replacement are
  fixtures, so the check is shown to separate them rather than merely to pass.

- [ ] ⬜ **Task 2.2**: Swept — **no other `skipif` guards on a constant**. Ten
  sites: two now on `os.geteuid()`, three on `_RELAY_BINARY.exists()`, two on
  `shutil.which(...)`, two on `_PROJECT_CONFIG.exists()`, one on
  `_uv_available()`. Every one reads something that genuinely varies by
  machine.

  **The sweep this task originally described would not have caught the bug it
  came from.** `Path("/").stat().st_uid == 0` is a live call, not a literal —
  constant only in the semantic sense that `/` is owned by uid 0 everywhere. No
  import-time constant-folding flags it. What separates it from the nine
  sound guards is not constancy but that it asks a different question from the
  one its reason states, which is why Task 2.1 checks the reason–condition pair
  instead.

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
